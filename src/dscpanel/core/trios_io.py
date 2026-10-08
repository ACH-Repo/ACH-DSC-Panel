# The TRIOS reader. Fix it in this file; the format is docs/TRI-FORMAT.md,
# and tests/test_reader.py checks it against TRIOS's own exports of real
# runs.

"""
trios_io.py -- read TA Instruments TRIOS measurements (DSC, SDT, TGA ...).

This program's one TRIOS reader. It takes either a native binary ``.tri``
or a TRIOS ``.txt`` export and returns the same structure, so the plotting
code never has to care which it was handed::

    data['head']     -> metadata (filename, sample name, operator, mass ...)
    data['numdata']  -> [ {prog, dims, units, nums (N x M ndarray)}, ... ]
    data['analyses'] -> { step_name: { model: [ {field: value}, ... ] } }

The binary layout is documented in TRI-FORMAT.md. Read that before changing
anything here; it also records how each constant was found, so a future TRIOS
release that shifts an offset can be re-derived rather than guessed at.

Three things this reader learned the hard way, all of which bit earlier
versions and are worth keeping in mind:

1. Segments are delimited by their *step objects* (the program strings
   "Ramp 10,00 \u00b0C/min to 250 \u00b0C"), NOT by a fixed number of arrays
   per segment. An
   analysis can attach a derived curve (a running integral, a polynomial fit)
   to one segment only, and a partial final segment can record fewer signals
   than the rest -- both break any fixed-stride chunking.

2. The signal list is stored in the file, so signals are looked up BY NAME.
   Index 2 is Heat Flow on a DSC25 but Sample Flow on an SDT650: hard-coding
   the index silently plots gas flow as heat flow.

3. Time is stored in seconds (TRIOS displays minutes) and Heat Flow in watts;
   the "(Normalized)" signals are per gram of sample.

4. Every array carries a 16-byte signal id, and arrays are named by it. The
   final segment of a run looked as if it stored only the raw sensors: no
   Temperature and no Heat Flow (see 5 for why). An earlier version guessed
   that segment's signals by shape and picked Set Point Temperature, which
   starts at the programmed 30 degC, not at the ~53 degC the sample had
   actually cooled to. The curve came out flattened and stretched back to
   30 degC.

5. An array can carry a FLAGS LIST, one uint32 per sample, in front of its
   values; a plain array is the same layout with an empty list. A signal
   with samples that hold no measurement is stored that way - the last
   samples of a run, and in some runs the first ones: Temperature, Heat
   Flow, Heat Flow Phase and Total Heat Capacity on a DSC25 (5 to 35
   samples), Temperature, Temperature Rate, Heat Flow, Weight Corrected Heat
   Flow and Temperature Difference on an SDT650 (25 to 50). Point 4's "raw
   sensors only" final segment, and the indium ramp with "no heat flow",
   were these arrays not being read. An earlier fix matched the flagged form
   by 8 fixed bytes, 01102101 080d0200, and the 080d0200 in it is the list's
   byte LENGTH, 4 + 4 * 33601: it found the arrays of a 33601-sample segment
   and of no other (a 39001-sample SDT run drew its Weight in kg as the heat
   flow). Flagged samples are NaN. SDT signals are also stored in SI units -
   Weight in kg, Weight Corrected Heat Flow in W/kg, the gas flows in L/s -
   and the file has no sample-size field: the sample mass is the reference
   the Weight Change (%) is taken against, when that is a mass at all (see
   `_mass_from_weight`). docs/TRI-FORMAT.md section 3 has the layout.
"""
from __future__ import annotations

import re
import struct
from collections import Counter
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# Binary layout constants (see TRI-FORMAT.md)
# --------------------------------------------------------------------------- #
# Every signal is a float32 column in ONE layout, plain or flagged:
#
#   <n:i32> 01 10 21 01 <size:u32> <m:i32> <m x u32 flags> 01 00 <n:i32> <n x f32>
#
# <size> is the byte length of what follows it up to the 01 00, 4 + 4 * m.
# A plain array has an empty list (m = 0, size = 4); its first 14 bytes are
# the old fixed signature 01102101 04000000 00000000 0100. A flagged array
# has one flag per sample (m = n). Nothing about the length is assumed: the
# three counts and the size are checked against each other (`_signal_array`).
VALUE_TAG = bytes.fromhex('01102101')
ARRAY_SIG = bytes.fromhex('0110210104000000000000000100')   # the plain case

# The flags on a RECORDED signal (DSC25 and SDT650, TRIOS 5.1.1, 5.11 and
# 6.0): 0 on a measured sample, 0x08000008 on a sample with no measurement
# in it (stored as 0.0). A list with 0x10 in it belongs to a curve TRIOS
# CALCULATED - the points of an analysis, an SDT run's Heat Flow
# (Normalized) and Weight (%) - and those sit in the document region, where
# one read as a signal would move the start of the analysis search past
# the analyses (the reference file went from 18 analyses to 0).
FLAG_CALCULATED = 0x10

# The tag that introduces a step (segment) object, just before its program name.
STEP_TAG = bytes.fromhex('07200134')

# Program verbs that begin a step name.
STEP_WORDS = ('Ramp', 'Equilibrate', 'Isothermal', 'Modulate', 'Jump', 'Mark',
              'Repeat', 'Abort', 'Increment', 'Sampling', 'Data storage')

PRINTABLE = re.compile(rb'[ -~\xc2\xb0\xb5\xc2\xb2\xc2\xb3]{6,}')

# Analysis models whose record layout has been decoded. Everything else in a
# file is still reported (name + cursors) but without its result fields.
ONSET_MODELS = ('Onset point', 'Endset point')
INTEGRAL_MODELS = ('Peak Integration (enthalpy)',)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _trapz(y, x):
    fn = getattr(np, 'trapezoid', None) or np.trapz
    return float(fn(y, x))


def _meta_string(raw, key):
    """Value of a .NET length-prefixed metadata string.

    The length is .NET's 7-bit encoded integer: one byte below 128, and
    above that seven bits a byte, low first, the high bit saying another
    follows - a procedure of several steps (`proceduresegments`) is
    longer than 127 bytes, and was read as missing when only a single
    byte was taken."""
    k = key if isinstance(key, bytes) else key.encode()
    j = raw.find(k)
    if j == -1:
        return None
    p = j + len(k)
    ln, shift = 0, 0
    while p < len(raw) and shift <= 28:
        byte = raw[p]
        p += 1
        ln |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    else:
        return None
    if p + ln > len(raw):
        return None
    return raw[p:p + ln].decode('utf-8', 'replace')


def _sample_mass_g(raw):
    """Sample mass in grams. TRIOS stores it in mg. None when the file has
    no such field (an SDT run: see `_mass_from_weight`)."""
    for key in ('samplesize', 'samplemass'):
        v = _meta_string(raw, key)
        try:
            return float(v.replace(',', '.')) / 1000.0
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def signal_list(raw, limit=400_000):
    """The instrument's signal list, as stored in the file header.

    TRIOS writes it as one '; '-joined run of names near the top. Returns them
    in acquisition order, which is the order the float32 arrays follow."""
    best = None
    for m in PRINTABLE.finditer(raw, 0, limit):
        s = m.group().decode('utf-8', 'replace')
        if s.count('; ') >= 4 and 'Temperature' in s:
            if best is None or len(s) > len(best):
                best = s
    if not best:
        return []
    return [x.strip() for x in best.split(';') if x.strip()]


# --------------------------------------------------------------------------- #
# Binary reader
# --------------------------------------------------------------------------- #
def _arrays(raw):
    """Every float32 signal array: (tag_offset, values), in file order,
    plain or flagged (flagged samples NaN). `tag_offset` is where the
    array's leading count sits, which is what `_signal_id` counts back
    from. TRIOS's later copies are still in here; `_recordings` drops
    them."""
    out = []
    i = raw.find(VALUE_TAG, 4)
    while i != -1:
        values = _signal_array(raw, i)
        if values is not None:
            out.append((i - 4, values))
        i = raw.find(VALUE_TAG, i + 1)
    return out


def _signal_array(raw, i):
    """The values of the array whose tag is at `i`, flagged samples NaN, or
    None when the bytes there are not a recorded signal (see VALUE_TAG for
    the layout).

    Every length in the layout is checked against the others, so nothing
    about the array's size is assumed. What is NOT a recorded signal: a
    curve TRIOS calculated (its flags carry FLAG_CALCULATED), and, in most
    files, TRIOS's own copy of each flagged signal of the final segment,
    which has three more bytes between the count and the tag. Where a copy
    has no such gap (some real runs) it is read here and `_recordings`
    drops it."""
    n = len(raw)
    if i < 4 or i + 12 > n:
        return None
    count = struct.unpack_from('<i', raw, i - 4)[0]
    size, m = struct.unpack_from('<Ii', raw, i + 4)
    if not 0 < count < 50_000_000 or m not in (0, count) or size != 4 + 4 * m:
        return None
    body = i + 8 + size
    if (body + 6 + 4 * count > n
            or raw[body:body + 2] != b'\x01\x00'
            or struct.unpack_from('<i', raw, body + 2)[0] != count):
        return None
    values = np.frombuffer(raw, '<f4', count=count,
                           offset=body + 6).astype(float)
    if m:
        flags = np.frombuffer(raw, '<u4', count=m, offset=i + 12)
        if np.any(flags & FLAG_CALCULATED):
            return None
        values[flags != 0] = np.nan
    return values


def _is_copy(values, earlier):
    """True when `values` is TRIOS's later copy of the recording `earlier`:
    one sample longer, a 1.0 in front, and the rest the same bit for bit
    (NaN where the recording is flagged). Seen for every flagged signal of
    the final segment, in the document region after the last segment."""
    return (len(values) == len(earlier) + 1 and values[0] == 1.0
            and np.array_equal(values[1:], earlier, equal_nan=True))


def _recordings(raw):
    """`(arrays, copies)`: the recorded signal arrays, in file order, and how
    many later copies of them were left out.

    A copy carries its signal's id, so it would be named like the recording;
    worse, sitting in the document region, it would move `doc_start` - the
    start of the analysis search - past analyses that come before it, and a
    step-name string between the last segment and it would open a segment
    made of nothing but copies. So copies go before anything else looks at
    the arrays."""
    out, copies, last = [], 0, {}
    for off, values in _arrays(raw):
        sid = _signal_id(raw, off)
        earlier = last.get(sid)
        if earlier is not None and _is_copy(values, earlier):
            copies += 1
            continue
        last[sid] = values
        out.append((off, values))
    return out, copies


def _step_name(run):
    """The step name inside a printable run, without its .NET length byte.

    A step name is a length-prefixed .NET string, and the length byte is
    itself PRINTABLE whenever the name is 32..126 bytes long: ' ' for 32, '!'
    for 33, '"' for 34 and so on, so the regex swallows it with the name. Only
    ' ' and '!' used to be stripped, which worked for exactly the 32- and
    33-byte names of the files this was written on. Another run says "Ramp
    10.00 degC/min to 210.0000 degC" - 34 bytes, prefix '"' - so every
    heating step was invisible and its arrays were merged into the cooling
    segment before it: 3 segments read out of 7. The byte is recognised by
    what it IS, the length of the name that follows it (in UTF-8 bytes, which
    is how the degree sign counts two)."""
    if len(run) > 1 and run[0] <= len(run) - 1:
        name = run[1:1 + run[0]]
        if name.decode('utf-8', 'replace').startswith(STEP_WORDS):
            return name.decode('utf-8', 'replace').strip()
    return run.lstrip(b'!').decode('utf-8', 'replace').strip()


def _step_objects(raw, array_offsets):
    """(offset, program name) for each measured segment, in order.

    Segments are delimited by their step objects. The step tag is a good hint
    but not universal -- an "Isothermal 5,0 min" step can carry a different
    preamble -- so a candidate is accepted when it is a step-verb string that
    actually separates signal arrays. The procedure summary near the top of the
    file lists every step in ONE string, which lands before the first array and
    so collapses harmlessly into the opening boundary."""
    if not array_offsets:
        return []
    first, last = array_offsets[0], array_offsets[-1]
    cand = []
    for m in PRINTABLE.finditer(raw, 0, last):
        txt = _step_name(m.group())
        if not txt.startswith(STEP_WORDS):
            continue
        # a name is one step, not the whole procedure listing
        if txt.count(';') > 1:
            continue
        cand.append((m.start(), txt))
    # keep the boundaries that actually have arrays on both sides, plus the
    # opening one; drop near-duplicates (the same name written twice)
    steps = []
    for off, txt in cand:
        if off > first and not any(a > off for a in array_offsets):
            continue
        if steps and off - steps[-1][0] < 64 and txt == steps[-1][1]:
            continue
        steps.append((off, txt))
    # anything before the first array belongs to segment 1: keep only the last
    pre = [x for x in steps if x[0] <= first]
    post = [x for x in steps if x[0] > first]
    return (pre[-1:] if pre else []) + post


def _cache_for_chain(raw, q, max_back=8_000_000):
    """The cached analysed curve belonging to the chain whose index array
    starts at ``q``.

    Layout is <rows:int32><cols:int32> then rows*cols float64, and the block
    ends exactly where the index array begins -- that adjacency is the link
    between a cache and its analysis. Searching BACKWARDS from ``q`` for a
    header satisfying ``h + 8 + rows*cols*8 == q`` finds it directly.

    A forward scan that consumes blocks as it goes does NOT work: it locks onto
    the first plausible header and steps over later ones, which is how an
    earlier version of this reader found 4 caches where the file holds 8.

    Note the cache can be SHORTER than the segment it came from -- TRIOS
    stores the samples that have a heat flow, e.g. 2605 rows for a
    2640-sample segment whose last 35 heat-flow samples are flagged (NaN
    here) -- so comparisons against it must be prefix-wise."""
    n = len(raw)
    lo = max(0, q - max_back)
    for h in range(q - 8, lo, -4):
        r = struct.unpack_from('<i', raw, h)[0]
        c = struct.unpack_from('<i', raw, h + 4)[0]
        if not (50 < r < 5_000_000 and 1 <= c <= 8):
            continue
        if h + 8 + r * c * 8 != q:
            continue
        blk = np.frombuffer(raw, '<f8', count=r * c, offset=h + 8)
        if np.all(np.isfinite(blk)) and np.abs(blk).max() < 1e7:
            return blk.reshape(-1, c)
    return None


def _chain_caches(raw, doc_start):
    """{chain_offset: cache} for every analysis chain in the file."""
    out = {}
    for ch in _analysis_chains(raw, doc_start):
        blk = _cache_for_chain(raw, ch['chain'])
        if blk is not None:
            out[ch['chain']] = blk
    return out


def _repair_partial(seg, caches, mass_g):
    """Pin the signals of a segment whose array count does not match the list.

    A partial segment records a different subset of signals, in an order that
    is neither a prefix nor a fixed shift of the full list -- on the reference
    file its Temperature sits at array 12 and Heat Flow at 15, with several
    other arrays spanning a plausible temperature range. Guessing by shape
    picks the wrong one. An analysis cache resolves it exactly: the cached
    column equals the segment's own samples bit for bit."""
    vals = seg['raw_signals']
    for blk in caches:
        # col 0 is the x channel (temperature); a later column is the analysed
        # signal, stored normalized (W/g) where the raw array is in watts.
        ref = blk[:, 0]
        for a in vals:
            if len(a) < len(ref) or not _cache_eq(ref, a):
                continue
            if _is_temperature(a):
                seg.setdefault('pinned', {})['Temperature'] = a
                if blk.shape[1] > 1 and mass_g:
                    sig = blk[:, 1] * mass_g
                    for b in vals:
                        if len(b) >= len(sig) and _cache_eq(sig, b):
                            seg['pinned']['Heat Flow'] = b
                            break
            break
    return seg.get('pinned', {})


def _is_temperature(a):
    a = a[np.isfinite(a)]                # a flagged array's NaN samples
    return (a.size > 2 and -200.0 < float(a.min())
            and float(a.max()) < 2000.0 and float(a.max() - a.min()) > 2.0)


def _signal_id(raw, tag_off):
    """The 16-byte id of the signal an array holds.

    It sits 38..22 bytes before the array's leading count and is the same for
    one signal in every segment of a file (Temperature, Heat Flow T1, ...), so
    it names an array exactly, whatever its position in the segment."""
    return bytes(raw[tag_off - 38:tag_off - 22])


def _learn_ids(raw, groups, names):
    """{signal id: name}, learned from the segments that store the full list.

    In a full segment the first len(names) arrays follow the signal list in
    order, so position gives the name. Returns None when there is no full
    segment or two segments disagree -- then the ids cannot be trusted and the
    caller falls back to the older position/shape logic."""
    ids = {}
    for g in groups:
        if len(g) < len(names):
            continue
        row = [_signal_id(raw, off) for off, _ in g[:len(names)]]
        if len(set(row)) != len(row):
            return None
        for sid, nm in zip(row, names):
            if ids.setdefault(sid, nm) != nm:
                return None
    return ids if len(ids) == len(names) else None


def _learn_aliases(full, names):
    """{name: [other names]} for signals that are one array stored twice.

    TRIOS writes the displayed signals as copies of the sensor they come from:
    Temperature is Sample Sensor Temperature and Heat Flow is the selected
    Heat Flow T1, bit for bit. A partial final segment stores only the
    sensors, so this is what lets its Temperature and Heat Flow be recovered
    exactly. An alias is accepted only when the two arrays are identical in
    EVERY full segment and actually vary (two all-zero arrays are equal
    without being the same signal)."""
    out = {}
    for a in names:
        for b in names:
            if a == b:
                continue
            same = [np.array_equal(sg[a], sg[b]) and float(np.ptp(sg[a])) > 0
                    for sg in full if a in sg and b in sg]
            if same and all(same):
                out.setdefault(a, []).append(b)
    return out


def _segments(raw):
    """Split the signal arrays into per-segment records.

    Boundaries come from the step objects, so a segment carrying an extra
    analysis curve, or a partial final segment with a shorter signal list, is
    still delimited correctly."""
    # Later copies are dropped silently: they are part of the format, not a
    # problem with the file, and the note line is for problems.
    arrs, _copies = _recordings(raw)
    if not arrs:
        raise ValueError('no TRIOS signal arrays found (not a .tri?)')
    names = signal_list(raw)
    steps = _step_objects(raw, [off for off, _ in arrs])
    if not steps:                       # fall back to one segment
        steps = [(0, 'segment')]

    bounds = [p for p, _ in steps]
    groups = [[] for _ in steps]
    for tag_off, vals in arrs:
        k = sum(1 for b in bounds if b <= tag_off) - 1
        groups[max(k, 0)].append((tag_off, vals))

    doc_start = max(off for off, _ in arrs)
    ids = _learn_ids(raw, groups, names) if names else None

    segs = []
    for g, (_, prog) in zip(groups, steps):
        if not g:
            continue
        vals = [v for _, v in g]
        if ids:
            # Name every array by its signal id. Exact in every segment,
            # including a partial one, which stores a different subset in a
            # different order. Arrays with an unknown id are curves an
            # analysis (running integral, polynomial fit) attached to the
            # segment, not recorded signals. A second array with a known id
            # is a copy the copy check did not catch; the first one, in
            # signal-list order, is the recording.
            by_name = {}
            unknown = 0
            for off, v in g:
                nm = ids.get(_signal_id(raw, off))
                if nm is None:
                    unknown += 1
                else:
                    by_name.setdefault(nm, v)
            sig = {nm: by_name[nm] for nm in names if nm in by_name}
            exact = True
            twice = len(g) - len(by_name) - unknown
            if unknown:
                print(f"[trios_io] segment '{prog[:34]}': dropped {unknown} "
                      "analysis-generated curve(s) appended after the "
                      "recorded signals.")
            if twice:
                print(f"[trios_io] segment '{prog[:34]}': {twice} signal(s) "
                      "stored twice; the first of each was kept.")
        elif names and len(vals) >= len(names):
            # No usable ids: map by position when the counts line up. Extra
            # arrays at the end are analysis curves and are dropped.
            sig = dict(zip(names, vals[:len(names)]))
            exact = True
            if len(vals) > len(names):
                print(f"[trios_io] segment '{prog[:34]}': dropped "
                      f"{len(vals) - len(names)} analysis-generated curve(s) "
                      "appended after the recorded signals.")
        else:
            # A partial segment without ids is not a prefix of the list, so
            # its signals have to be identified by shape (_resolve_signals).
            sig = {}
            exact = False
        segs.append({'prog': prog, 'signals': sig, 'raw_signals': vals,
                     'exact': exact, 'names': names, 'ids': ids})

    # Fill signals a partial segment did not store from the sensor they are a
    # copy of (see _learn_aliases).
    full = [s['signals'] for s in segs
            if s['exact'] and len(s['signals']) == len(names)]
    aliases = _learn_aliases(full, names) if full else {}
    for s in segs:
        if not s['exact'] or len(s['signals']) == len(names):
            continue
        filled = []
        for nm in names:
            if nm in s['signals']:
                continue
            src = next((b for b in aliases.get(nm, ()) if b in s['signals']),
                       None)
            if src is not None:
                s['signals'][nm] = s['signals'][src]
                filled.append(f'{nm} = {src}')
        s['signals'] = {nm: s['signals'][nm] for nm in names
                        if nm in s['signals']}
        missing = [nm for nm in names if nm not in s['signals']]
        note = f"; filled {', '.join(filled)}" if filled else ''
        gone = f"; not recorded: {', '.join(missing)}" if missing else ''
        print(f"[trios_io] segment '{s['prog'][:34]}' is partial "
              f"({len(s['raw_signals'])} of {len(names)} signals stored)"
              f"{note}{gone}.")
    return segs, doc_start


def _resolve_signals(seg, mass_g):
    """Return an ordered {name: array} for one segment, plus derived columns."""
    if seg['exact']:
        sig = dict(seg['signals'])
    else:
        vals = seg['raw_signals']
        sig = {}
        t = vals[0]
        sig['Time'] = t
        pinned = seg.get('pinned') or {}
        sig.update(pinned)
        if 'Temperature' not in sig:
            temps = [a for a in vals[1:] if _is_temperature(a)]
            if temps:
                sig['Temperature'] = max(temps,
                                         key=lambda a: float(a.max() - a.min()))
        if 'Heat Flow' not in sig:
            hf = [a for a in vals
                  if a is not t and a is not sig.get('Temperature')
                  and a.size > 2 and float(np.abs(a).max()) < 50.0
                  and float(np.abs(a).mean()) < 1.0]
            if hf:
                sig['Heat Flow'] = max(hf, key=lambda a: float(a.std()))
        how = ('pinned exactly by an analysis cache' if pinned
               else 'identified by shape -- UNVERIFIED, check against a .txt '
                    'export before quoting numbers from this segment')
        print(f"[trios_io] segment '{seg['prog'][:34]}': {len(vals)} arrays vs "
              f"{len(seg['names'])} named signals; {how}.")

    out = {}
    if 'Time' in sig:
        out['Time'] = sig['Time'] / 60.0                 # seconds -> minutes
    for k, v in sig.items():
        if k != 'Time':
            out[k] = v * SI_TO_UNITS.get(k, 1.0)

    # A normalized heat flow is what a plot actually wants on the y axis:
    # watts over the sample mass, for DSC and SDT alike. TRIOS's own export
    # of an SDT run says so (0.4163 W/g = 2.0107 mW / 4.830 mg); "Weight
    # Corrected Heat Flow" divides by the weight LEFT at each moment
    # instead, and is only the fallback when there is no mass - and not even
    # then when the recorded weight is not positive, because divided by a
    # negative weight it is the heat flow upside down.
    if 'Heat Flow' in out and mass_g:
        out['Heat Flow (Normalized)'] = out['Heat Flow'] / mass_g
    elif ('Weight Corrected Heat Flow' in out
          and _weight_is_positive(out.get('Weight'))):
        out['Heat Flow (Normalized)'] = out['Weight Corrected Heat Flow']
    return out


# Signals a .tri stores in SI that UNITS names otherwise (SDT650). Checked
# on two real runs: Heat Flow (W) / Weight (kg) equals Weight Corrected Heat
# Flow to 1e-4, so that one is W/kg; both gas flows read 1/600 L/s, the
# instrument's 100 mL/min purge.
SI_TO_UNITS = {
    'Weight': 1e6,                          # kg -> mg
    'Weight Corrected Heat Flow': 1e-3,     # W/kg -> W/g
    'Sample Flow': 60_000.0,                # L/s -> mL/min
    'Balance Flow': 60_000.0,
    # A DSC25's purge is in L/s too: the reference file's Full export
    # writes it in mL/min, exactly 60000 times the stored value.
    'Cell Purge': 60_000.0,
}


# How far Weight / (Weight Change / 100) may wander over a segment and still
# be ONE reference mass: 1e-4 of it. On every SDT run it was checked on
# (124 with a mass) it wanders by under 3.2e-7 of it, and it equals
# the export's Sample Mass to the 6 figures the reader writes.
MASS_SPREAD = 1e-4


def _mass_from_weight(sig):
    """`(grams, why_not)`: the sample mass from an SDT segment's Weight (mg)
    and Weight Change (%), which is the reference the percentage is taken
    against - the same at every sample.

    `(None, None)` when the segment has not both. `(None, reason)` when it
    has both and they do not describe a sample mass: a ratio that is not
    positive at every sample - three real runs record -99.9 mg against a
    Weight Change of +99.99 %, and TRIOS's own normalised curve is upside
    down with them - or one that is not constant. Golden rule 4: such a file
    has NO sample mass, and the panel says so where one would be used. Both
    may end slightly below zero TOGETHER when the sample is all gone
    (a sample that sublimes: 16.67 to -0.19 mg, 99.98 to -1.11 %); the
    ratio is still the one mass, 16.6726 mg."""
    w, pct = sig.get('Weight'), sig.get('Weight Change')
    if w is None or pct is None:
        return None, None
    ok = np.isfinite(w) & np.isfinite(pct) & (np.abs(pct) > 1.0)
    if ok.sum() < 3:
        return None, None
    w, pct = w[ok], pct[ok]
    ratio = w / (pct / 100.0)
    if not np.all(ratio > 0):
        return None, ('the recorded Weight ({:.6g} to {:.6g} mg) and Weight '
                      'Change ({:.6g} to {:.6g} %) have opposite signs'
                      .format(float(w.min()), float(w.max()),
                              float(pct.min()), float(pct.max())))
    mass = float(np.median(ratio))
    spread = float(ratio.max() - ratio.min())
    if spread > MASS_SPREAD * mass:
        return None, ('Weight / Weight Change is not one reference mass '
                      '({:.6g} to {:.6g} mg)'.format(float(ratio.min()),
                                                     float(ratio.max())))
    return mass / 1000.0, None


def _weight_is_positive(w):
    """True when a segment's Weight (mg) is recorded and positive wherever
    it is recorded."""
    if w is None:
        return False
    w = w[np.isfinite(w)]
    return bool(w.size) and bool(np.all(w > 0))


UNITS = {
    'Time': 'min', 'Temperature': '\u00b0C', 'Heat Flow': 'W',
    'Heat Flow (Normalized)': 'W/g', 'Weight': 'mg', 'Weight Change': '%',
    'Weight Corrected Heat Flow': 'W/g', 'Temperature Rate': '\u00b0C/min',
    'Sample Flow': 'mL/min', 'Balance Flow': 'mL/min',
    'Temperature Difference': '\u00b0C',
    # As TRIOS's own signal list names them (the [Signal List] of an SDT
    # export: "Set Point (degC)", "Power Requested (W)").
    'Set Point': '\u00b0C', 'Power Requested': 'W', 'Power Delivered': 'W',
    'Cell Purge': 'mL/min',
}


# --------------------------------------------------------------------------- #
# Analyses
# --------------------------------------------------------------------------- #
def _cache_eq(a, b):
    for off in range(0, 65):
        m = min(len(a), len(b) - off)
        if m < 50:
            break
        probe = min(m, 200)
        if np.abs(a[:probe] - b[off:off + probe]).max() < 1e-6:
            if np.abs(a[:m] - b[off:off + m]).max() < 1e-6:
                return True
    return False


def _analysis_chains(raw, doc_start):
    """Locate every user-added analysis in the document region.

    Each is stored as a chain
        [cached analysed curve (f64)] [row-index array (u32 0,1,2,...)] [record]
    The record holds the cursor positions as float64 at fixed offsets; the
    cached curve repeats the analysed segment's own float32 samples exactly,
    which is what ties an analysis to its scan (the .txt export only names the
    step *program*, and three segments can share one).

    Returns [{model, cursors, stored, points, chain, variable}] in creation
    order: `cursors` in the record's order (an endset's transition cursor
    first), `stored` TRIOS's result at +16, `points` TRIOS's construction as
    (x, y) pairs for an onset, endset or Tg (y in TRIOS's display unit of
    the analysed curve, see RECORD_Y_SCALE), `variable` the analysed curve's
    16-byte signal id or None. Other results are NOT read back -- they are
    recomputed from the curve by trios_analysis.
    """
    n = len(raw)
    needle = struct.pack('<8I', *range(8))
    known = ('Onset point', 'Endset point', 'Peak Integration (enthalpy)',
             'Glass transition', 'Peak height', 'Signal min', 'Signal max',
             'Signal change', 'Curve Y at X', 'Curve X at Y', 'Statistics',
             'Polynomial', 'Running Integral', 'Oxidation temperature',
             'Area under the curve', 'Find peaks')

    chains = []
    pos = raw.find(needle, doc_start)
    while pos != -1:
        k = 8
        while pos + 4 * k + 4 <= n and struct.unpack_from('<I', raw, pos + 4 * k)[0] == k:
            k += 1
        if k >= 200:
            chains.append((pos, pos + 4 * k))
        pos = raw.find(needle, pos + 4 * k)

    out, seen = [], set()
    named = headed = 0
    starts = [c[0] for c in chains] + [n]
    for ci, (q, e) in enumerate(chains):
        win = raw[e:min(e + 2500, starts[ci + 1])]
        model = next((m for m in known if (' - ' + m).encode() in win), None)
        if model is None:
            continue
        named += 1
        # The record's float64 fields start at a FIXED offset behind a fixed
        # header; see _record_start. Field layout (TRI-FORMAT.md section 5):
        #   onset / endset   : TRIOS's construction, three (x, y) points at
        #                      +0, +16, +32 (+16 is the RESULT), and the two
        #                      cursors as (x, curve y) at +86 and +132 - for
        #                      an onset the flat one first, for an endset
        #                      the transition first
        #   integration      : +0 first baseline cursor, +96 second
        #   glass transition : four (x, y) PAIRS at +0, +16, +32, +48
        #   the rest         : +0 cursor, +132 second cursor
        # +16 is deliberately not used as a cursor -- it is TRIOS's own answer.
        rec = _record_start(raw, e)
        if rec is None:
            continue                  # a display copy, not the record itself
        headed += 1
        off1 = 0
        if model.startswith('Peak Integration'):
            off2 = 96
        elif model == 'Glass transition':
            # A Tg record is four points down the transition, not a cursor
            # pair with a result between them: onset cursor, onset, end,
            # end cursor, each as (x, y) at a 16-byte stride. Reading +132
            # as the second cursor (the tangent-model layout) gave 0.0, which
            # is why the Tg drawing could not be written before.
            off2 = 48
        elif model in ONSET_MODELS:
            # Not +0: that is the construction's first point, which is the
            # flat cursor for an onset but a point on the inflection tangent
            # for an endset (the reference file: 93.8469 where the cursor
            # is 93.4654).
            off1, off2 = 86, 132
        else:
            off2 = 132
        c0 = struct.unpack_from('<d', raw, rec + off1)[0]
        c1 = struct.unpack_from('<d', raw, rec + off2)[0]
        stored = struct.unpack_from('<d', raw, rec + 16)[0]
        points = None
        if model == 'Glass transition':
            points = [struct.unpack_from('<2d', raw, rec + off)
                      for off in (0, 16, 32, 48)]
        elif model in ONSET_MODELS:
            points = [struct.unpack_from('<2d', raw, rec + off)
                      for off in (0, 16, 32)]
        ok = [np.isfinite(v) and -200.0 < v < 2000.0 for v in (c0, c1)]
        if model in ONSET_MODELS + INTEGRAL_MODELS and not all(ok):
            print(f"[trios_io] skipped a '{model}' record whose cursors are not "
                  f"temperatures ({c0:.4g}, {c1:.4g}); the record layout may "
                  "have changed, see TRI-FORMAT.md section 5.")
            continue
        if not ok[1]:
            c1 = float('nan')         # a one-cursor model (Peak height, ...)
        key = (model, round(c0, 4), None if not ok[1] else round(c1, 4))
        if key in seen:
            continue
        seen.add(key)
        out.append({'model': model, 'cursors': (c0, c1),
                    'stored': stored, 'points': points, 'chain': q,
                    'variable': _record_variable(raw, rec, starts[ci + 1])})
    if named and not headed:
        print('[trios_io] found analyses but no record with the known header; '
              'this TRIOS version may store them differently (TRI-FORMAT.md '
              'section 5). Analyses were not recovered.')
    return out


# Every analysis record's float64 fields start exactly 30 bytes after its index
# array ends, behind this header (identical in TRIOS 5.1.1 and 6.0, for all 14
# analysis models tried):
#     01 00 01 00 <u32> 0f 2f 01 <u32> 10 2f 02 <u32> <u32> <u32>
# The display copies of an analysis carry a different header (24 2f 01 ...) and
# no fields. An earlier version searched byte by byte for the first pair of
# plausible temperatures instead; it matched 4 bytes early whenever a cursor's
# low mantissa bytes, read together with the header's last u32 (2), happened to
# decode as -2.0, and drew that analysis at 0 degC.
RECORD_HEAD = 30
REC_TAG0 = bytes.fromhex('01000100')     # at +0
REC_TAG1 = bytes.fromhex('0f2f01')       # at +8
REC_TAG2 = bytes.fromhex('102f02')       # at +15


# TRIOS's own ids for the curves it CALCULATES (not in the signal list, so
# not learned from the segments like the recorded ones). The same in every
# file tried, DSC25 and SDT650, TRIOS 5.1.1 to 6.0.
# The names are this reader's: the Weight (%) curve is its "Weight Change".
CALCULATED_IDS = {
    bytes.fromhex('2f85cc58bf1cb343a3f97135b826d88a'): 'Heat Flow (Normalized)',
    bytes.fromhex('ba6bb3c0fdeeab47935c906a39544545'): 'Weight Change',
}

# How far behind a record's fields its point arrays may start (seen: +851 to
# +1343; the record's name strings sit in between).
POINTS_WINDOW = 4000

# A record's y values are in TRIOS's DISPLAY unit of the analysed curve, and
# this turns them into the unit of the reader's column of that name. Checked
# on every onset/endset record in the files tried, by the record's
# "curve y at the cursor" (+94, +140) against the curve there: Heat Flow
# (Normalized) in W/g (764 cursors, within 6e-4 relative, the nearest sample
# being up to 0.04 K off), Weight Change in % (366, within 2e-5), Heat Flow
# in mW (a run with no sample mass: 8 cursors, exactly 1000 x watts).
RECORD_Y_SCALE = {'Heat Flow': 1e-3}          # mW -> W


def _record_variable(raw, rec, stop):
    """The 16-byte signal id of the curve an analysis was made ON, or None.

    Behind every record come the analysis's points as two small CALCULATED
    arrays (flags 0x10, VALUE_TAG layout): x, then y, each carrying the id of
    its signal. x is Temperature's id; y's id is the analysed variable - the
    thing TRIOS's export calls "Analysed variables: Weight vs. Temperature".
    Decoded on an SDT run where two onsets were made on the weight and the
    integration on the heat flow."""
    n = len(raw)
    stop = min(stop, rec + POINTS_WINDOW, n)
    found = []
    i = raw.find(VALUE_TAG, rec)
    while i != -1 and i < stop and len(found) < 2:
        if i + 12 <= n:
            count = struct.unpack_from('<i', raw, i - 4)[0]
            size, m = struct.unpack_from('<Ii', raw, i + 4)
            body = i + 8 + size
            if (0 < count < 100_000 and m == count and size == 4 + 4 * m
                    and body + 6 <= n and raw[body:body + 2] == b'\x01\x00'
                    and struct.unpack_from('<i', raw, body + 2)[0] == count):
                flags = np.frombuffer(raw, '<u4', count=m, offset=i + 12)
                if np.all(flags & FLAG_CALCULATED):
                    found.append(_signal_id(raw, i - 4))
        i = raw.find(VALUE_TAG, i + 1)
    return found[1] if len(found) == 2 else None


def _record_start(raw, e):
    """Offset of the record fields for the index array ending at ``e``, or None
    when what follows is not a record header."""
    if (raw[e:e + 4] == REC_TAG0
            and raw[e + 8:e + 11] == REC_TAG1
            and raw[e + 15:e + 18] == REC_TAG2
            and e + RECORD_HEAD + 140 <= len(raw)):
        return e + RECORD_HEAD
    return None


def _attribute(blk, segs_xy):
    """Which segment was this analysis run on?

    The cache's x column repeats that segment's own float32 samples bit for
    bit, so an exact (prefix-wise) comparison names the scan -- including
    between repeat scans whose results differ by less than 0.02 K and which no
    geometric reconstruction can separate.

    Returns None for a cache-less record; the caller reuses the previous
    attribution, which is the order TRIOS writes them in."""
    if blk is None:
        return None
    ref = blk[:, 0]
    for j, (T, _) in enumerate(segs_xy):
        if len(T) >= len(ref) and _cache_eq(ref, T):
            return j
    return None


def attach_analyses(data, path, cache_by_chain=None, doc_start=None,
                    raw=None, ids=None):
    """Recover the analyses from a .tri and recompute their results.

    Populates ``data['analyses']`` in the same shape the .txt export gives, so
    the annotation helpers work identically for either source. Values
    are recomputed from the curve (see trios_analysis), not read back from the
    binary -- only the model, the cursors and the scan attribution come from
    the file. `doc_start` (where the last recorded array starts), `raw` and
    `ids` (the learned {signal id: name}) are passed by `read_tri_binary`,
    which has them already.

    Besides the '<value> <unit>' strings, an entry can carry two keys that
    are NOT text: `segment` (int, 1-based) and `construction` (a list of
    [x, y] floats, see below). And `variable`, the name of the analysed
    curve ('Heat Flow (Normalized)', 'Weight Change'), when the record says
    it."""
    if raw is None:
        raw = Path(path).read_bytes()
    if doc_start is None:
        arrs, _copies = _recordings(raw)
        if not arrs:
            return data
        doc_start = max(off for off, _ in arrs)
    chains = _analysis_chains(raw, doc_start)
    if not chains:
        return data

    if cache_by_chain is None:
        cache_by_chain = _chain_caches(raw, doc_start)

    # (numdata index, temperature) of every segment that has one; the
    # attribution counts in this list, so it is mapped back to numdata
    # (an index into it used to be taken for a numdata index directly).
    with_t = []
    for j, d in enumerate(data['numdata']):
        if 'Temperature' in d['dims']:
            with_t.append((j, d['nums'][:, d['dims'].index('Temperature')]))
    segs_xy = [(T, None) for _j, T in with_t]

    last = None
    for ch in chains:
        k = _attribute(cache_by_chain.get(ch['chain']), segs_xy)
        j = with_t[k][0] if k is not None else None
        if j is None:
            j = last
        else:
            last = j
        if j is None or j >= len(data['numdata']):
            continue
        d = data['numdata'][j]
        i = {k: m for m, k in enumerate(d['dims'])}
        if 'Time' not in i or 'Temperature' not in i:
            continue
        # The analysed variable, when the record's points name it: the curve
        # the Python check is run on, and the unit of the construction's y.
        sid = ch.get('variable')
        variable = None
        if sid is not None:
            variable = CALCULATED_IDS.get(sid) or (ids or {}).get(sid)
        y_name = variable if variable in i else (
            'Heat Flow (Normalized)' if variable is None else None)
        if (ch['model'].startswith('Peak Integration')
                and y_name != 'Heat Flow (Normalized)'):
            y_name = None       # an enthalpy in J/g needs the curve in W/g
        t = d['nums'][:, i['Time']]
        T = d['nums'][:, i['Temperature']]
        Q = d['nums'][:, i[y_name]] if y_name in i else None
        # A flagged sample is NaN, and one NaN inside a window turns every
        # least-squares tangent into NaN: the check runs on the samples
        # that hold a measurement.
        keep = np.isfinite(t) & np.isfinite(T)
        if Q is not None:
            keep &= np.isfinite(Q)
            Q = Q[keep]
        t, T = t[keep], T[keep]
        c0, c1 = ch['cursors']
        info = _recompute(ch['model'], t, T, Q, c0, c1, ch.get('stored'),
                          ch.get('points'),
                          y_unit=UNITS.get(variable or 'Heat Flow (Normalized)',
                                           ''))
        info['Model'] = ch['model']
        if variable:
            info['variable'] = variable
            if ch.get('points'):
                # TRIOS's own construction, as numbers (never text: nothing
                # may list it as a result). x in degC; y in the unit of the
                # reader's column called `variable` - W/g, % for the weight,
                # W for Heat Flow (the record has TRIOS's display unit, mW).
                # Only with a known variable: without one the unit of y is
                # not known either.
                scale = RECORD_Y_SCALE.get(variable, 1.0)
                info['construction'] = [[float(x), float(y) * scale]
                                        for x, y in ch['points']]

        info['segment'] = j + 1
        data['analyses'].setdefault(d['prog'], {}) \
            .setdefault(ch['model'], []).append(info)
    return data


def _analysis_fn(name):
    """Find an analysis routine whether it is vendored into this file or lives
    in a sibling trios_analysis module. No import of `sys` -- the vendoring
    step strips module headers, so this has to work on globals alone."""
    fn = globals().get(name)
    if fn is not None:
        return fn
    try:
        import trios_analysis
    except ImportError:
        try:
            from achdsc import trios_analysis
        except ImportError:
            return None
    return getattr(trios_analysis, name, None)


def _tg_fields(T, Q, points, y_unit='W/g'):
    """Glass-transition results from the four points TRIOS stored.

    The record holds (x, y) for the onset cursor, the ONSET, the END and the
    end cursor. The onset and end points are TRIOS's own tangent construction,
    so they are reported as they stand; the midpoint is the half-height
    crossing between them, which is what "Midpoint type: Half height" means
    and is NOT the mean of the two (0.06 K apart on the reference file).

    Validated on the reference file (TRIOS 5.1.1, 50 K/min up-scan): the
    crossing comes out at 78.911 degC and TRIOS's own export says 78,911
    degC. The onset point's y matches the curve to 2e-5 W/g; the end point's
    y is 0.025 W/g off the curve, as it must be, because it sits on the END
    TANGENT rather than on the data.
    """
    if not points or len(points) != 4:
        return {}
    (cur0, _y0), (on_x, on_y), (end_x, end_y), (cur1, _y1) = points
    for value in (cur0, on_x, end_x, cur1):
        if not np.isfinite(value) or not -200.0 < value < 2000.0:
            return {}
    out = {'Onset cursor x': f'{cur0:.4f} \u00b0C',
           'End cursor x': f'{cur1:.4f} \u00b0C',
           'Onset x': f'{on_x:.4f} \u00b0C',
           'End x': f'{end_x:.4f} \u00b0C',
           'Step height': f'{end_y - on_y:.4f} {y_unit}'.rstrip()}
    if Q is None:
        return out
    order = np.argsort(T)
    ts, qs = np.asarray(T)[order], np.asarray(Q)[order]
    lo, hi = min(on_x, end_x), max(on_x, end_x)
    window = (ts >= lo) & (ts <= hi)
    if window.sum() >= 2:
        half = 0.5 * (on_y + end_y)
        tw, qw = ts[window], qs[window]
        if qw[-1] < qw[0]:            # np.interp needs an increasing x
            tw, qw = tw[::-1], qw[::-1]
        out['Midpoint'] = f'{float(np.interp(half, qw, tw)):.4f} \u00b0C'
    return out


def _python(fn, *args, **kwargs):
    """An analysis routine's result, or {} when it cannot be computed.

    One analysis that cannot be recomputed (too few samples, a degenerate
    fit) must not cost the file ALL its analyses: `read_tri_binary` catches
    whatever `attach_analyses` raises, and loses the lot."""
    if fn is None or any(a is None for a in args):
        return {}
    try:
        with np.errstate(all='ignore'):
            return fn(*args, **kwargs) or {}
    except (ValueError, FloatingPointError, np.linalg.LinAlgError,
            IndexError, ZeroDivisionError):
        return {}


def _recompute(model, t, T, Q, c0, c1, stored=None, points=None,
               y_unit='W/g'):
    """Cursor positions -> result fields, using the analysis routines.

    Emitted as '<value> <unit>' strings so the annotation helpers parse them
    exactly as they parse a .txt export. `c0, c1` are the cursors in the
    RECORD's order (`_analysis_chains`): for an endset the transition cursor
    comes first. `Q` is None when the segment has no curve to recompute on;
    then only what the record itself holds is reported."""
    out = {}
    if model == 'Glass transition':
        fields = _tg_fields(T, Q, points, y_unit)
        if fields:
            return fields
        # No usable points: fall through to the two cursors, so the analysis
        # is still reported rather than lost.
    if model in ('Onset point', 'Endset point'):
        endset = 'End' in model
        # TRIOS's names, from its export: "Onset cursor x" is the cursor on
        # the FLAT side for both models - for an endset the one stored
        # second (the reference file: Transition cursor x 93,465, Onset
        # cursor x 116,637).
        flat, transition = (c1, c0) if endset else (c0, c1)
        if endset:
            out['Transition cursor x'] = f'{transition:.4f} \u00b0C'
            out['Onset cursor x'] = f'{flat:.4f} \u00b0C'
        else:
            out['Onset cursor x'] = f'{flat:.4f} \u00b0C'
            out['Transition cursor x'] = f'{transition:.4f} \u00b0C'
        k = 'Endset x' if endset else 'Onset x'
        # TRIOS's own answer is stored in the record at +16 and is exact, so it
        # is what gets reported. The Python reconstruction is kept alongside for
        # comparison -- it agrees to ~0.2 K on a clean step but is only an
        # approximation of TRIOS's internal tangent algorithm. It takes the
        # flat cursor first: that is the one its baseline tangent is fitted
        # at (an endset passed transition-first came out as the onset).
        if stored is not None:
            out[k] = f'{stored:.4f} \u00b0C'
        r = _python(_analysis_fn('onset_point'), T, Q, flat, transition,
                    kind='endset' if endset else 'onset')
        if k in r and np.isfinite(r[k]):
            out[k + ' (python)'] = f'{r[k]:.4f} \u00b0C'
            if stored is None:
                out[k] = f'{r[k]:.4f} \u00b0C'
    elif model.startswith('Peak Integration'):
        out['Baseline cursor x'] = f'{c0:.4f} \u00b0C'
        out['Baseline cursor x1'] = f'{c1:.4f} \u00b0C'
        r = _python(_analysis_fn('peak_integration'), t, T, Q, c0, c1)
        if r:
            out['Enthalpy (normalized)'] = \
                f"{abs(r['Enthalpy (normalized)']):.4f} J/g"
            out['Peak temperature'] = f"{r['Peak temperature']:.4f} \u00b0C"
    else:
        out['Cursor x'] = f'{c0:.4f} \u00b0C'
        out['Cursor x1'] = f'{c1:.4f} \u00b0C'
    return out


def read_tri_binary(path):
    """Native TRIOS ``.tri`` reader. Works for DSC, SDT and TGA files."""
    raw = Path(path).read_bytes()
    mass_g = _sample_mass_g(raw)
    mass_source = 'recorded' if mass_g else None
    segs, doc_start = _segments(raw)

    why_not = None
    if not mass_g:
        # An SDT file has no sample-size field; its Weight Change (%) is
        # taken against the sample mass, so that is where it is read - from
        # the first segment that has both, and BEFORE a partial segment is
        # repaired, because the repair pins its heat flow by the mass.
        for seg in segs:
            if not seg['exact']:
                continue
            mass_g, why_not = _mass_from_weight(_resolve_signals(seg, None))
            if mass_g:
                mass_source = 'derived from the weight'
            if mass_g or why_not:
                break
    if not mass_g:
        print('[trios_io] no sample mass {}; heat flow left un-normalised.'
              .format('found' if not why_not else '(' + why_not + ')'))

    cache_by_chain = _chain_caches(raw, doc_start)
    if any(not sg['exact'] for sg in segs):
        caches = list(cache_by_chain.values())
        for sg in segs:
            if not sg['exact']:
                _repair_partial(sg, caches, mass_g)

    names = [s['prog'] for s in segs]
    progs = [f'{nm} #{j + 1}' for j, nm in enumerate(names)]

    numdata = []
    for j, seg in enumerate(segs):
        sig = _resolve_signals(seg, mass_g)
        if not sig:
            continue
        dims = list(sig.keys())
        cols = [sig[d] for d in dims]
        m = min(len(c) for c in cols)
        numdata.append({
            'prog': progs[j],
            'dims': dims,
            'units': [UNITS.get(d, '') for d in dims],
            'nums': np.column_stack([c[:m] for c in cols]),
        })

    head = {'Filename': Path(path).stem}
    for key in ('instrumenttype', 'samplename', 'operator', 'project',
                'rundate', 'samplesize', 'instrumentname',
                'proceduresegments'):
        v = _meta_string(raw, key)
        if v:
            head[key] = v
    if mass_g:
        head['Sample Mass'] = f'{mass_g * 1000:g} mg'
        # 'recorded' (the file's sample-size field) or 'derived from the
        # weight' (an SDT run: Weight / Weight Change), so a program can say
        # which - the second is an inference, however exact.
        head['mass_source'] = mass_source

    data = {'head': head, 'numdata': numdata, 'analyses': {}}
    try:
        attach_analyses(data, path, cache_by_chain, doc_start, raw,
                        ids=segs[0].get('ids') if segs else None)
    except Exception as e:                       # never let this break a plot
        print(f'[trios_io] analyses not recovered: {type(e).__name__}: {e}')
    return data


# --------------------------------------------------------------------------- #
# Text reader (TRIOS .txt export)
# --------------------------------------------------------------------------- #
def _text_dim(name, unit):
    """An export column's name as the binary reader names that signal."""
    if name.strip() == 'Weight' and unit.strip() == '%':
        return 'Weight Change'
    return name


def read_tri_text(path):
    """TRIOS ``.txt`` export -> the same structure as read_tri_binary."""
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    text = text.replace('\u00c2', '')          # cp1252-read-as-utf8 mojibake

    data = {'numdata': [], 'analyses': {}}
    matches = list(re.finditer(r'\n\[([\w\s]+)\]\n', text))
    sections = []
    if matches:
        sections.append(('head', text[:matches[0].start()]))
        for k, m in enumerate(matches):
            end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
            sections.append((m.group(1), text[m.end():end]))
    else:
        sections.append(('head', text))

    for name, body in sections:
        body = body.strip('\n')
        # TRIOS writes two different text schemas: the plain export uses
        # '[step]', the Full export '[Step]' plus '[Header]' / '[Parameters: x]'.
        if name.lower() == 'step':
            lines = body.split('\n')
            if len(lines) < 4:
                continue
            dims, units = lines[1].split('\t'), lines[2].split('\t')
            # An SDT export calls its percentage "Weight" too, with the unit
            # '%' (and some carry a second "Weight" in mg beside it). The
            # binary reader's names are the signal list's - "Weight" is mg,
            # "Weight Change" is % - and a consumer must not have to read the
            # unit to know which it was handed: one export's 99.7 % came out
            # as 99.7 mg, and as 462 % of a 21.5 mg sample.
            dims = [_text_dim(d, u) for d, u in zip(dims, units)] \
                + dims[len(units):]
            rows = []
            for ln in lines[3:]:
                parts = ln.strip().replace(',', '.').split('\t')
                if len(parts) != len(dims) or '' in parts:
                    continue
                try:
                    rows.append([float(p) for p in parts])
                except ValueError:
                    continue
            if rows:
                data['numdata'].append({
                    'prog': lines[0], 'dims': dims, 'units': units,
                    'nums': np.array(rows, dtype=float)})
        elif name == 'Analysis':
            counts, analysis = Counter(), {}
            for ln in body.split('\n'):
                parts = ln.rstrip('\n').split('\t')
                if len(parts) < 2:
                    continue
                key, val = parts[0], parts[1]
                analysis[f'{key}{counts[key]}' if counts[key] else key] = val
                counts[key] += 1
            said = analysis.get('Analysed variables', '')
            if ' vs. ' in said:
                # The analysed curve, named as the binary reader names it
                # (`attach_analyses`): the weight an SDT onset is made on is
                # TRIOS's Weight (%), the reader's "Weight Change".
                y = said.split(' vs. ', 1)[0].strip()
                analysis['variable'] = 'Weight Change' if y == 'Weight' else y
            if 'Analyzed step' in analysis and 'Model' in analysis:
                full = analysis['Analyzed step']
                prog = full.split(' - ', 1)[1] if ' - ' in full else full
                analysis['prog'] = prog
                data['analyses'].setdefault(prog, {}) \
                    .setdefault(analysis['Model'], []).append(analysis)
        elif name == 'Procedure':
            kv = {}
            for ln in body.split('\n'):
                parts = ln.split('\t')
                if len(parts) == 2:
                    kv[parts[0]] = parts[1]
            data['Procedure'] = kv
        else:
            kv = {}
            for ln in body.split('\n'):
                parts = ln.split('\t')
                if len(parts) == 2:
                    kv[parts[0]] = parts[1]
            if name == 'head':
                data['head'] = kv
            else:
                data[name] = kv

    # The sample mass is what a W/g axis is made of, and every consumer looks
    # for it in `head` -- but TRIOS writes it in [Procedure] in a plain export
    # and in [Sample] in a Full one, so it is folded in from wherever it
    # turned up. Without this a .txt-only file has no mass, and a plotter
    # either refuses it or invents one.
    head = data.setdefault('head', {})
    for section in ('Procedure', 'Sample'):
        block = data.get(section) or {}
        for key in ('Sample Mass', 'Sample Name', 'Pan Type', 'Project Name',
                    'Operator'):
            if block.get(key) and not head.get(key):
                head[key] = block[key]
    if head.get('Sample Mass'):
        head.setdefault('mass_source', 'recorded')     # as the export says
    if not head.get('samplename'):
        head['samplename'] = (head.get('Sample name')
                              or head.get('Sample Name') or '')
    return data


def read_tri(path):
    """Read a TRIOS measurement: native ``.tri`` binary or ``.txt`` export.

    Dispatch is by content, not extension -- TRIOS binaries begin with NUL
    bytes and carry an 'instrumenttype' key, the text export starts with
    'Filename'."""
    with open(path, 'rb') as f:
        head = f.read(64)
    is_binary = b'\x00' in head[:16] or b'instrumenttype' in head
    return read_tri_binary(path) if is_binary else read_tri_text(path)
