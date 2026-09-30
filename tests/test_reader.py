"""
The binary .tri reader against TRIOS's own .txt export of the same run.

The reader is this program's own. The rule from docs/TRI-FORMAT.md: never
trust a decode because it looks plausible, compare it value by value with an
export.
Measurement data is not committed, so these tests look for (.tri, .txt
export) pairs in the folders `tests/local_testdata.txt` and TRIOS_TESTDATA
name (see `conftest._local_entries`; a file named there stands for its
folder) and skip when there are none.

The rules that do not need a real file - the array layout, the flags, the
mass that is not one - are pinned on synthetic BYTES in the layout
TRI-FORMAT.md section 3 describes, which was read off the real files; they
are not a parser fixture for a format nobody has seen.
"""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from conftest import _local_entries, local_file
from dscpanel.core import trios_io

# Real files, named by a hash of their file name (`conftest.hashed_name`).
#: The DSC25 reference run: TRIOS 5.1.1, seven segments, 16 stored
#: analyses, a Full .txt export beside it.
DSC_REFERENCE = 'sha:b2303c243b22'
#: The SDT650 reference run: TRIOS 5.1.1, 39001 samples, and its export.
SDT_REFERENCE = 'sha:6ceef94fd7ce'
SDT_REFERENCE_TXT = 'sha:ac9b497e666c'


def _dirs():
    out, seen = [], set()
    for entry in _local_entries():
        folder = entry if os.path.isdir(entry) else os.path.dirname(entry)
        key = os.path.normcase(os.path.abspath(folder))
        if os.path.isdir(folder) and key not in seen:
            seen.add(key)
            out.append(Path(folder))
    return out


def _pairs():
    out = []
    for d in _dirs():
        txts = {p.stem.casefold(): p for p in d.glob('*.txt')}
        for tri in sorted(d.glob('*.tri')):
            txt = txts.get(tri.stem.casefold())
            if txt is not None:
                out.append(pytest.param(tri, txt, id=tri.stem))
    return out


PAIRS = _pairs()


def _tris():
    seen, out = set(), []
    for d in _dirs():
        for tri in sorted(d.glob('*.tri')):
            if tri.resolve() not in seen:
                seen.add(tri.resolve())
                out.append(pytest.param(tri, id=tri.stem))
    return out


TRIS = _tris()


def _read_export(txt):
    """[{'prog', 'columns': {name: (unit, values)}}] per step, from either a
    plain or a Full export, with a BLANK cell as NaN - `read_tri_text` drops
    a row with a blank in it, and those rows are exactly the ones a flagged
    sample makes. Column names as the reader names them (an SDT export's
    "Weight" in % is its "Weight Change", `trios_io._text_dim`)."""
    steps, block = [], None
    with open(txt, encoding='utf-8', errors='replace') as fh:
        lines = [ln.rstrip('\r\n') for ln in fh]
    k = 0
    while k < len(lines):
        ln = lines[k]
        if ln.lower() == '[step]':
            if k + 1 < len(lines) and lines[k + 1].startswith('Step name\t'):
                # Full export: Step name / Number of points / Variables /
                # Units, then 'Data point<TAB>...' rows at full precision
                prog = lines[k + 1].split('\t', 1)[1]
                dims = lines[k + 3].split('\t')[1:]
                units = lines[k + 4].split('\t')[1:]
                k += 5
                rows = []
                while k < len(lines) and lines[k].startswith('Data point'):
                    rows.append(lines[k].split('\t')[1:])
                    k += 1
            else:
                prog, dims, units = lines[k + 1], lines[k + 2].split('\t'), \
                    lines[k + 3].split('\t')
                k += 4
                rows = []
                while k < len(lines) and lines[k] and not lines[k].startswith('['):
                    rows.append(lines[k].split('\t'))
                    k += 1
            values = np.full((len(rows), len(dims)), np.nan)
            for r, parts in enumerate(rows):
                for c, cell in enumerate(parts[:len(dims)]):
                    if cell.strip():
                        values[r, c] = float(cell.replace(',', '.'))
            columns = {}
            for c, (name, unit) in enumerate(zip(dims, units)):
                name = trios_io._text_dim(name, unit)
                columns.setdefault(name, (unit.strip(), values[:, c]))
            steps.append({'prog': prog, 'columns': columns,
                          'rows': len(rows)})
            continue
        k += 1
    return steps


# export column -> (reader column, factor, tolerance). The tolerances are
# the export's own rounding plus float32: a plain export writes 4 decimals
# of a temperature and 6 significant figures of W/g; a Full export writes
# everything at full precision.
_COLUMNS = {
    'Time': ('Time', 1.0, 1e-4),
    'Temperature': ('Temperature', 1.0, 1e-4),
    'Heat Flow (Normalized)': ('Heat Flow (Normalized)', 1.0, 1e-5),
    ('Heat Flow', 'mW'): ('Heat Flow', 1000.0, 1e-6),
    'Weight Change': ('Weight Change', 1.0, 1e-3),
    ('Weight', 'mg'): ('Weight', 1.0, 1e-3),
    ('Cell Purge', 'mL/min'): ('Cell Purge', 1.0, 1e-6),
}


@pytest.mark.skipif(not PAIRS, reason='no .tri + .txt export pair on disk')
@pytest.mark.parametrize('tri,txt', PAIRS)
def test_every_segment_matches_the_export(tri, txt):
    """Every exported column the reader has, value by value, NaN-aware: an
    export's blank cell must be exactly the reader's NaN (a flagged sample),
    and a NaN where the export has a number is a failure. The row counts are
    equal: TRIOS's "2605 of 2640 samples" of a final segment were 35 rows
    whose heat flow is flagged, not rows it left out."""
    data = trios_io.read_tri(tri)
    ref = _read_export(txt)
    assert len(data['numdata']) == len(ref)
    compared = set()
    for j, (seg, step) in enumerate(zip(data['numdata'], ref)):
        i = {k: m for m, k in enumerate(seg['dims'])}
        n = seg['nums']
        assert len(n) == step['rows'], f'segment {j + 1}: rows'
        for name, (unit, want) in step['columns'].items():
            spec = _COLUMNS.get(name) or _COLUMNS.get((name, unit))
            if spec is None or spec[0] not in i:
                continue
            column, factor, tol = spec
            got = n[:, i[column]] * factor
            where = f'segment {j + 1} {name} [{unit}]'
            assert np.array_equal(np.isnan(got), np.isnan(want)), \
                where + ': blanks and NaN differ'
            both = np.isfinite(want)
            if both.any():
                assert np.abs(got[both] - want[both]).max() < tol, where
            compared.add(name)
    assert {'Time', 'Temperature'} <= compared
    assert compared & {'Heat Flow (Normalized)', 'Heat Flow'}


@pytest.mark.skipif(not PAIRS, reason='no .tri + .txt export pair on disk')
@pytest.mark.parametrize('tri,txt', PAIRS)
def test_partial_segment_starts_where_the_sample_is(tri, txt):
    """The regression that started the reader: the last segment's
    temperature must continue from where the previous segment's left off
    (the sample temperature is continuous), not jump to the programmed
    start. Measured samples only: a flagged one is NaN."""
    nd = trios_io.read_tri(tri)['numdata']
    for prev, seg in zip(nd, nd[1:]):
        ip = {k: m for m, k in enumerate(prev['dims'])}
        i = {k: m for m, k in enumerate(seg['dims'])}
        if 'Temperature' not in ip or 'Temperature' not in i:
            continue              # a segment that recorded no temperature
        before = prev['nums'][:, ip['Temperature']]
        after = seg['nums'][:, i['Temperature']]
        before, after = before[np.isfinite(before)], after[np.isfinite(after)]
        gap = abs(after[0] - before[-1])
        assert gap < 1.0, f"{seg['prog']}: starts {gap:.1f} K off the previous end"


@pytest.mark.skipif(not TRIS, reason='no .tri on disk')
@pytest.mark.parametrize('tri', TRIS)
def test_recovered_analyses_sit_on_their_scan(tri):
    """Every decoded analysis must lie on the scan it is attributed to: its
    cursors inside that scan's temperature range, and TRIOS's stored onset
    between its two cursors. A record read from the wrong offset fails this
    (one run had an onset at 0 degC on a scan spanning 54-248 degC). And the
    construction TRIOS stored is its own: the middle point IS the result,
    and the flat cursor is where the baseline tangent starts - the first
    point of an onset, the last of an endset."""
    data = trios_io.read_tri(tri)
    nd = data['numdata']
    for models in data['analyses'].values():
        for model, lst in models.items():
            for a in lst:
                d = nd[a['segment'] - 1]
                T = d['nums'][:, d['dims'].index('Temperature')]
                lo, hi = float(np.nanmin(T)), float(np.nanmax(T))
                val = lambda k: float(a[k].split()[0])
                if model in ('Onset point', 'Endset point'):
                    flat, c1 = val('Onset cursor x'), val('Transition cursor x')
                    c0 = flat
                    res = val('Endset x' if 'End' in model else 'Onset x')
                    assert min(c0, c1) <= res <= max(c0, c1), (model, a)
                    pts = a.get('construction')
                    if pts is not None:
                        assert len(pts) == 3
                        assert pts[1][0] == pytest.approx(res, abs=1e-4)
                        end = pts[-1] if 'End' in model else pts[0]
                        assert end[0] == pytest.approx(flat, abs=1e-3)
                elif model.startswith('Peak Integration'):
                    c0, c1 = val('Baseline cursor x'), val('Baseline cursor x1')
                else:
                    continue
                assert lo <= c0 <= hi and lo <= c1 <= hi, (model, a, lo, hi)
                for key, value in a.items():
                    if key not in ('segment', 'construction'):
                        assert isinstance(value, str), (key, value)


def _num(text):
    return float(str(text).split()[0].replace(',', '.'))


def _matched(tri, txt):
    """[(binary entry, export entry)] for every onset / endset the .tri and
    its export both hold, matched by model and result."""
    binary = trios_io.read_tri(tri)['analyses']
    export = trios_io.read_tri_text(txt)['analyses']
    ours = [(m, e) for ms in binary.values() for m, es in ms.items()
            for e in es]
    theirs = [(m, e) for ms in export.values() for m, es in ms.items()
              for e in es]
    out = []
    for model, entry in ours:
        if model not in ('Onset point', 'Endset point'):
            continue
        key = 'Endset x' if 'End' in model else 'Onset x'
        for other_model, other in theirs:
            if other_model == model and key in other and \
                    abs(_num(other[key]) - _num(entry[key])) < 6e-4:
                out.append((entry, other))
                break
    return out


@pytest.mark.skipif(not PAIRS, reason='no .tri + .txt export pair on disk')
@pytest.mark.parametrize('tri,txt', PAIRS)
def test_onset_and_endset_cursors_are_named_as_trios_names_them(tri, txt):
    """For an endset TRIOS's "Onset cursor x" is the FLAT cursor, stored
    SECOND (+132), and "Transition cursor x" the one stored first (+86).
    The reader took +0 for the first cursor, which for an endset is a
    point of the construction (the DSC reference run: 93.8469 where the
    cursor is 93.465), and gave the two the other way round; its Python
    endset then came out 13 K off. The analysed variable is the export's
    too."""
    variables = {'Heat Flow (Normalized) vs. Temperature':
                 'Heat Flow (Normalized)',
                 'Weight vs. Temperature': 'Weight Change'}
    for ours, theirs in _matched(tri, txt):
        for name in ('Onset cursor x', 'Transition cursor x'):
            assert _num(ours[name]) == pytest.approx(_num(theirs[name]),
                                                     abs=6e-4), name
        said = theirs.get('Analysed variables')
        if said in variables:
            assert ours.get('variable') == variables[said]


def test_the_endset_is_read_flat_cursor_second():
    """The DSC reference run's one endset, against its export (Transition
    cursor x 93,465, Onset cursor x 116,637, Endset x 108,024): with the flat
    cursor handed to the Python construction first it agrees with TRIOS to
    0.05 K; it used to say 95.12."""
    path = local_file(DSC_REFERENCE)
    if path is None:
        pytest.skip('the DSC reference run is not on this machine')
    data = trios_io.read_tri(path)
    (endset,) = [e for ms in data['analyses'].values()
                 for m, es in ms.items() for e in es if m == 'Endset point']
    assert _num(endset['Transition cursor x']) == pytest.approx(93.465, abs=5e-4)
    assert _num(endset['Onset cursor x']) == pytest.approx(116.637, abs=5e-4)
    assert _num(endset['Endset x']) == pytest.approx(108.024, abs=5e-4)
    assert _num(endset['Endset x (python)']) == pytest.approx(108.024, abs=0.1)
    assert endset['variable'] == 'Heat Flow (Normalized)'
    # TRIOS's construction, in degC and W/g: the flat point is on the curve
    # side of the baseline tangent, the transition point at the curve's
    # height at the transition cursor.
    (p0, p1, p2) = endset['construction']
    assert p1[0] == pytest.approx(108.0241, abs=1e-4)
    assert p2[0] == pytest.approx(116.637, abs=1e-3)
    seg = data['numdata'][endset['segment'] - 1]
    T = seg['nums'][:, seg['dims'].index('Temperature')]
    q = seg['nums'][:, seg['dims'].index('Heat Flow (Normalized)')]
    at = int(np.nanargmin(np.abs(T - 93.4654)))
    assert p0[1] == pytest.approx(q[at], abs=2e-3)     # W/g, not W


def test_the_sdt_reference_run_is_read_whole():
    """The SDT reference run (SDT650, TRIOS 5.1.1, 39001 samples) is the file
    that showed the flagged tag was a byte count: it found 8 of 13 signals and
    drew the Weight, in kg, as the heat flow. Read by the layout, all 13 are
    there, the mass is TRIOS's own 21.54732 mg to 1e-6, derived and said so,
    and the two onsets TRIOS made on the WEIGHT say so."""
    path = local_file(SDT_REFERENCE)
    if path is None:
        pytest.skip('the SDT reference run is not on this machine')
    data = trios_io.read_tri(path)
    (seg,) = data['numdata']
    names = trios_io.signal_list(Path(path).read_bytes())
    assert len(names) == 13 and set(names) <= set(seg['dims'])
    assert len(seg['nums']) == 39001
    T = seg['nums'][:, seg['dims'].index('Temperature')]
    assert np.isnan(T[38976:]).all() and np.isfinite(T[:38976]).all()
    assert data['head']['mass_source'] == 'derived from the weight'
    assert float(data['head']['Sample Mass'].split()[0]) == \
        pytest.approx(21.54732, abs=1e-4)
    found = [(m, e) for ms in data['analyses'].values()
             for m, es in ms.items() for e in es]
    onsets = [e for m, e in found if m == 'Onset point']
    assert [e['variable'] for e in onsets] == ['Weight Change'] * 2
    assert sorted(_num(e['Onset x']) for e in onsets) == \
        pytest.approx([415.587, 476.281], abs=5e-4)
    for e in onsets:
        # the construction's y is the weight in %, as the curve is there
        assert 97.0 < e['construction'][0][1] < 100.0
    (peak,) = [e for m, e in found if m.startswith('Peak Integration')]
    assert peak['variable'] == 'Heat Flow (Normalized)'
    assert _num(peak['Enthalpy (normalized)']) == pytest.approx(71.246, rel=1e-3)


@pytest.mark.parametrize('name,mass', [
    # SDT runs in open pans: the mass derived from the weight
    ('sha:5f9cf91d758e', 27.3594),
    ('sha:06ac54ff3719', 28.1122),
    ('sha:05d84cbf2b9d', 35.7817),
    # SDT runs whose recorded weight is negative: no mass
    ('sha:76aeb809d9b5', None),
    ('sha:4a9933231194', None),
    ('sha:16d2f754d99d', None),
])
def test_a_negative_weight_is_no_sample_mass(name, mass):
    """Three real runs record a Weight of about -99 mg against a Weight
    Change of +99.99 %: Weight / Weight Change is a NEGATIVE mass, TRIOS's
    own normalised curve is upside down with it, and so was the reader's.
    Golden rule 4: such a file has no sample mass, and no normalised heat
    flow either - not even Weight Corrected Heat Flow, which is the heat
    flow divided by that same negative weight. Both segments are whole
    since the flagged arrays are read (the isothermal was "8 of 13")."""
    path = local_file(name)
    if path is None:
        pytest.skip('{} is not on this machine'.format(name))
    data = trios_io.read_tri(path)
    assert len(data['numdata']) == 2
    for seg in data['numdata']:
        assert {'Temperature', 'Heat Flow', 'Weight', 'Weight Change'} <= \
            set(seg['dims'])
    if mass is None:
        assert 'Sample Mass' not in data['head']
        for seg in data['numdata']:
            assert 'Heat Flow (Normalized)' not in seg['dims']
    else:
        assert float(data['head']['Sample Mass'].split()[0]) == \
            pytest.approx(mass, abs=1e-4)
        assert data['head']['mass_source'] == 'derived from the weight'


def test_an_sdt_export_names_its_percentage_weight_change():
    """TRIOS's text export of an SDT run calls its % column "Weight", which
    the panel took for milligrams (99.7 mg) or divided by the mass (462 %).
    The reader names it as the binary does: "Weight Change" is %, "Weight"
    is mg."""
    assert trios_io._text_dim('Weight', '%') == 'Weight Change'
    assert trios_io._text_dim('Weight', 'mg') == 'Weight'
    assert trios_io._text_dim('Temperature', '%') == 'Temperature'
    path = local_file(SDT_REFERENCE_TXT)
    if path is None:
        pytest.skip('the SDT reference export is not on this machine')
    data = trios_io.read_tri_text(path)
    (step,) = data['numdata']
    assert step['dims'] == ['Time', 'Temperature', 'Heat Flow (Normalized)',
                            'Weight Change']
    assert step['units'][-1] == '%'
    assert step['nums'][0, -1] == pytest.approx(99.71)
    # its analyses name the curve they were made on as the binary does:
    # both onsets and the endset "Weight vs. Temperature", the integration
    # nothing (the export does not say)
    found = [(m, e.get('variable')) for ms in data['analyses'].values()
             for m, es in ms.items() for e in es]
    assert sorted(found, key=str) == sorted(
        [('Onset point', 'Weight Change'), ('Onset point', 'Weight Change'),
         ('Endset point', 'Weight Change'),
         ('Peak Integration (enthalpy)', None)], key=str)


def test_record_is_read_at_its_fixed_offset():
    """The audited run's trap, rebuilt byte for byte: the header ends in
    the u32 2, and a cursor of 60.799126 degC (a float32 widened to
    float64) begins with 00 00 00 c0. Read 4 bytes early, those 8 bytes are the float64 -2.0, a
    'plausible temperature', and so was the second cursor. Only the fixed
    offset reads 60.80 / 86.03.

    An onset's cursors are read at +86 and +132, where
    TRIOS keeps them as (x, curve y); +0 is the construction's first point,
    which for an ONSET has the flat cursor's x too (so both are written)."""
    head = bytes.fromhex('01000100 03000000 0f2f014d000000 102f0244000000 '
                         '03000000 02000000'.replace(' ', ''))
    assert len(head) == trios_io.RECORD_HEAD
    rec = bytearray(160)
    struct.pack_into('<d', rec, 0, float(np.float32(60.799126)))
    struct.pack_into('<d', rec, 16, 76.7355)
    struct.pack_into('<d', rec, 86, float(np.float32(60.799126)))
    struct.pack_into('<d', rec, 132, float(np.float32(86.031845)))
    raw = (b'\x00' * 16 + struct.pack('<300I', *range(300)) + head + bytes(rec)
           + b'\x40x - Ramp 10 - Onset point')
    (ch,) = trios_io._analysis_chains(raw, 0)
    assert ch['model'] == 'Onset point'
    assert ch['cursors'] == pytest.approx((60.799126, 86.031845), abs=1e-4)
    assert ch['stored'] == pytest.approx(76.7355)
    assert ch['variable'] is None          # no point arrays behind it


def test_an_endset_record_hands_python_the_flat_cursor_first():
    """Record order for an endset: transition cursor at +86, flat at +132.
    The fields name them as TRIOS's export does, and the construction is
    TRIOS's three points."""
    info = trios_io._recompute('Endset point', None, None, None, 93.4654,
                               116.6373, stored=108.0241,
                               points=[(93.85, 0.331), (108.0241, 0.2304),
                                       (116.6373, 0.2629)])
    assert list(info)[:2] == ['Transition cursor x', 'Onset cursor x']
    assert info['Transition cursor x'].startswith('93.4654')
    assert info['Onset cursor x'].startswith('116.6373')
    assert info['Endset x'].startswith('108.0241')
    assert 'Endset x (python)' not in info       # nothing to recompute on


def test_signal_ids_name_arrays_in_a_partial_segment():
    """Unit-level: a segment missing Temperature and Heat Flow gets them from
    the sensor arrays that equal them in every full segment."""
    full = [{'Time': np.arange(5.), 'Temperature': np.array([1., 2, 3, 4, 5]),
             'Sensor': np.array([1., 2, 3, 4, 5]), 'Zero': np.zeros(5),
             'Also zero': np.zeros(5)}] * 2
    al = trios_io._learn_aliases(full, list(full[0]))
    assert al['Temperature'] == ['Sensor']
    # two all-zero arrays are equal without being one signal
    assert 'Zero' not in al and 'Also zero' not in al


# ------------------------------------------- the array layout, in bytes
def _array(values, flags=None, sid=b'\x11' * 16, gap=b''):
    """One signal object in the layout of TRI-FORMAT.md section 3:
    21 06 <len> <id> 01000000 01000000 00 f22101 04000000 00000000 0100
    <n> [gap] 01102101 <size> <m> <m flags> 0100 <n> <n float32>."""
    n = len(values)
    flags = [] if flags is None else list(flags)
    body = (struct.pack('<i', n) + gap + trios_io.VALUE_TAG
            + struct.pack('<Ii', 4 + 4 * len(flags), len(flags))
            + struct.pack('<{}I'.format(len(flags)), *flags)
            + b'\x01\x00' + struct.pack('<i', n)
            + np.asarray(values, '<f4').tobytes())
    pre = (sid + bytes.fromhex('0100000001000000' '00' 'f22101'
                               '04000000' '00000000' '0100'))
    return b'\x21\x06' + struct.pack('<I', len(pre) + len(body)) + pre + body


def test_one_layout_plain_or_flagged_whatever_the_length():
    """The round-25 tag 01102101 080d0200 was a byte COUNT: 0x20d08 =
    4 + 4 * 33601, so it matched a 33601-sample flagged array and nothing
    else. Plain and flagged are one layout, the length is read, and a
    flagged sample (0x08000008) is NaN."""
    plain = np.arange(7, dtype=float)
    flagged = np.array([52.98, 52.97, 52.96, 0.0, 0.0])
    raw = (b'\x00' * 64 + _array(plain) + b'\x00' * 9
           + _array(flagged, [0, 0, 0, 0x08000008, 0x08000008])
           + b'\x00' * 9 + _array(np.ones(39001), [0] * 39001))
    arrays = trios_io._arrays(raw)
    assert [len(v) for _off, v in arrays] == [7, 5, 39001]
    assert np.array_equal(arrays[0][1], plain)
    assert np.allclose(arrays[1][1][:3], flagged[:3], atol=1e-5)
    assert np.isnan(arrays[1][1][3:]).all()


@pytest.mark.parametrize('damage', ['size', 'count', 'second count', 'm'])
def test_the_lengths_of_an_array_are_checked_against_each_other(damage):
    """Nothing about an array's size is assumed: its leading count, the flag
    list's length and byte size, and the count before the values must all
    agree, or it is not an array."""
    blob = bytearray(_array([1.0, 2.0, 3.0], [0, 0, 0]))
    tag = bytes(blob).find(trios_io.VALUE_TAG)
    if damage == 'size':
        struct.pack_into('<I', blob, tag + 4, 4 + 4 * 2)
    elif damage == 'count':
        struct.pack_into('<i', blob, tag - 4, 4)
    elif damage == 'second count':
        struct.pack_into('<i', blob, tag + 8 + 16 + 2, 2)
    else:
        struct.pack_into('<i', blob, tag + 8, 2)
    assert trios_io._arrays(b'\x00' * 64 + bytes(blob)) == []


def test_a_calculated_curve_is_not_a_signal():
    """A list with 0x10 in it is a curve TRIOS CALCULATED - an analysis's
    points, an SDT run's Heat Flow (Normalized) - which sits in the document
    region; read as a signal it moved the start of the analysis search past
    the analyses (the DSC reference run: 18 analyses to 0)."""
    raw = (b'\x00' * 64 + _array([1.0, 2.0, 3.0], [0x10, 0x10, 0x10])
           + b'\x00' * 9 + _array([1.0, 2.0], [0x10, 0x08000010]))
    assert trios_io._arrays(raw) == []


def test_a_later_copy_is_not_a_recording():
    """TRIOS writes each flagged signal of the final segment again in the
    document region, one sample longer with a 1.0 in front. With no gap
    before its tag (some SDT runs, many DSC25 runs) it reads as an array,
    carries the signal's id, and would move the analysis search past
    everything before it."""
    rec = np.array([323.758, 323.774, np.nan])
    flags = [0, 0, 0x08000008]
    other = _array([5.0, 6.0, 7.0], sid=b'\x22' * 16)
    raw = (b'\x00' * 64 + _array(rec, flags) + b'\x00' * 9 + other
           + b'\x00' * 9 + _array(np.r_[1.0, rec], [0] + flags))
    assert len(trios_io._arrays(raw)) == 3
    arrays, copies = trios_io._recordings(raw)
    assert copies == 1 and [len(v) for _o, v in arrays] == [3, 3]


def test_a_mass_from_the_weight_must_be_one():
    """Weight / Weight Change is the sample mass only when it is positive -
    the two of one sign at every sample - and the same at every sample;
    otherwise there is none, and the reason is given. A sample that is all
    gone ends slightly BELOW zero in both (a sample that sublimes: 16.67
    mg to -0.19 mg, 99.98 % to -1.11 %), which is still one mass."""
    pct = np.array([100.0, 99.5, 99.0, 98.0])
    good = {'Weight': pct / 100.0 * 21.5, 'Weight Change': pct}
    mass, why = trios_io._mass_from_weight(good)
    assert mass == pytest.approx(0.0215) and why is None
    gone = np.array([99.98, 50.0, 2.0, -1.11])
    mass, why = trios_io._mass_from_weight(
        {'Weight': gone / 100.0 * 16.67, 'Weight Change': gone})
    assert mass == pytest.approx(0.01667) and why is None
    negative = {'Weight': -good['Weight'], 'Weight Change': pct}
    mass, why = trios_io._mass_from_weight(negative)
    assert mass is None and 'opposite' in why
    wandering = {'Weight': good['Weight'] * np.array([1, 1, 1, 1.01]),
                 'Weight Change': pct}
    mass, why = trios_io._mass_from_weight(wandering)
    assert mass is None and 'not one reference mass' in why
    assert trios_io._mass_from_weight({'Weight': pct}) == (None, None)
