# TA Instruments TRIOS `.tri` - binary format notes & re-derivation guide

Status: decoded and validated **2026-07-27** against TRIOS **5.1.1.46572**
(DSC25, file `OJ-12-DSC-2-07012026.tri`); partial-segment handling revised
and re-validated **2026-09-22** against that file and TRIOS **6.0.0.726**
(DSC25, `SES-2-ag-16092026.tri`). **2026-09-28**: the array layout
generalised (plain and flagged arrays are one layout, section 3), which is
what the "partial final segment" and the indium ramp's "missing" heat flow
were; SDT650 specifics (section 3b); the onset / endset record layout and
the analysed variable (section 5). Validated on every `.tri` on the
development machine (468: 340 DSC25, 127 SDT650, one empty) and every
`.tri`/`.txt` pair among them (section 6). Implemented in
`src/dscpanel/core/trios_io.py` (`read_tri_binary`) and checked by
`tests/test_reader.py`. Both came here from ACH-DSC-Plotter when that
program was retired (2026-09-28); this file is its `TRI-FORMAT.md`,
moved with them.
Helper names of the form `_tri_*` below are from the earlier inline reader
in `DSC_Plotter_clean.py`; the logic moved to `trios_io.py` under shorter
names (`_segments`, `_cache_for_chain`, ...).

This file exists because the layout was reverse-engineered, not published.
If a TRIOS update shifts an offset or a tag, **do not start from zero** -
everything below tells you what each constant means, how it was found, and
how to re-derive it in minutes. The single most important rule learned:

> **Never trust a decode because the output "looks plausible". Validate
> against a TRIOS `.txt` export of the same run, value by value.**
> (A wrong-but-plausible decode happened with Bruker `.raw`: the theta axis
> at +8 instead of the 2-theta axis at +16 gave a beautiful diffractogram
> with every peak at half its true angle.)

---

## 1. Big picture

A `.tri` is a serialized .NET object graph. We do **not** parse the graph
grammar. We fish out four kinds of structures by signature and verify
numerically:

```
[file metadata]  [seg1 step obj][seg1 arrays] ... [segN step obj][segN arrays]
                 [document region: calculated curves, later copies of
                  the final segment's flagged arrays, cached curves,
                  index arrays, analysis records and their points,
                  registry, display copies]
```

Everything is **little-endian**. Numeric data: signal arrays are float32,
cached analysis curves are float64, index arrays are uint32.

## 2. File metadata (start of file)

Length-prefixed key/value strings: `<len:u8><key><len:u8><value>`, keys are
lower-case ASCII (`instrumenttype`, `instrumentserialnumber`, `samplename`,
`operator`, `project`, `rundate`, `samplesize`, `samplepanmass`, ...).

* `samplesize` is the sample mass in **mg** (DSC). Heat Flow arrays are in
  **W**; TRIOS's "Heat Flow (Normalized)" (W/g) = W / mass_g.
* Implementation: `_tri_meta_string`, `_tri_sample_mass_g`.
* Re-derivation: hexdump the first 2 kB; the keys are readable ASCII.

## 3. Signal arrays (the measured data)

Every signal is one float32 column in **one layout**, plain or flagged
(`VALUE_TAG`, `_signal_array`):

```
<n:i32> 01 10 21 01 <size:u32> <m:i32> <m x u32 flags> 01 00 <n:i32> <n x f32>
   plain:   m = 0, size = 4     (the old 14-byte "signature"
                                 01 10 21 01 04 00 00 00 00 00 00 00 01 00)
   flagged: m = n, size = 4 + 4n
```

`<size>` is the byte LENGTH of `<m>` and the flag list, `4 + 4m`. The count
appears three times (before the tag, as `m` for a flagged array, and before
the values); the reader checks all of them and the size against each other
and assumes nothing about the length. Data (n x f32) follows immediately.

The object around an array, as far as it is used:

```
21 06 <objlen:u32> <signal id:16> 01 00 00 00 01 00 00 00 00
f2 21 01 04 00 00 00 00 00 00 00 01 00 <n:i32> 01 10 21 01 ...
```

so the signal id sits at bytes -38..-22 of the leading count (`_signal_id`).

* **Flags** (seen on every array of every file here, DSC25 and SDT650,
  TRIOS 5.1.1, 5.11 and 6.0): `0` on a measured sample, `0x08000008` on a
  sample that holds no measurement (its value is stored as 0.0). The reader
  returns a flagged sample as **NaN**. TRIOS's exports agree cell for cell:
  every blank cell of every export here is exactly one of these (section 6).
* **Which arrays are flagged**: the signals whose samples at an END of the
  run hold nothing. The last samples of the final segment - on a DSC25
  Temperature, Heat Flow Phase and Total Heat Capacity 5 samples and Heat
  Flow 35; on an SDT650 Temperature, Heat Flow and Temperature Difference
  25, Temperature Rate 33, Weight Corrected Heat Flow 50 - and in some runs
  the first samples of the first segment as well (five DSC25 runs here,
  the same 4 to 5 in Temperature and 34 to 35 in Heat Flow). Every other
  array of the run is plain.
* **A flag list with `0x10` in it belongs to a curve TRIOS CALCULATED**
  (`FLAG_CALCULATED`): an analysis's points (1 to 5 samples, flags `0x10`),
  an SDT run's Heat Flow (Normalized) in W/kg (`0x10` / `0x08000010`) and
  its Weight (%) (`0x10`). They sit in the document region. Read as a signal,
  one moves `doc_start` - the start of the analysis search - past the
  analyses: OJ-12 went from 18 analyses to 0, CN-81 from 3 to 0. Rejected.
  (Calculated curves mostly also have 3 bytes `00 00 00` between the leading
  count and the tag, which the count check rejects on its own; the analysis
  points do not.)
* **Later copies.** TRIOS writes each flagged signal of the final segment
  again in the document region, one sample LONGER with a `1.0` in front and
  the rest bit for bit the recording (NaN where it is flagged). Some carry
  the 3-byte gap (CN-81); many have none (220 of the 340 DSC25 runs here,
  90 of the 127 SDT650 runs, the DESY ones among them), and those read as
  arrays with the recording's id.
  `_recordings` drops them first (`_is_copy`: same id, n + 1, `1.0`, equal
  rest), before the step objects, the id naming or `doc_start` see them.
* **History: the 33601-sample tag.** Round 25 matched flagged arrays by 8
  fixed bytes, `01 10 21 01 08 0d 02 00`; `08 0d 02 00` is the size field,
  `4 + 4 * 33601`, so it found the flagged arrays of a 33601-sample segment
  (the KC files it was written on, not on this machine) and of nothing else.
  CN-81 (39001 samples: `68 61 02 00`) came out with 8 of its 13 signals, no
  learned ids, and the shape fallback drew its **Weight array, in kg,** as
  the heat flow and its Set Point as the temperature. No DSC file here ever
  matched it.
* Arrays repeat **per segment** in Signal-List order. In our files:
  index 0 = Time (**seconds**; TRIOS displays minutes), 1 = Temperature (°C),
  2 = Heat Flow (**W**), then ~22 more (Tzero, purge, board temps, ...).
  25 signals/segment here; **derive it, don't hardcode it**.
* **Each array carries a 16-byte signal id** (above). The id is the same for
  one signal in every segment of every file (Temperature = `9e919cf7
  a66f5648 92f86e58 68f792f5` in TRIOS 5.1.1 and 6.0, DSC25 and SDT650).
  Arrays are named by it: the id -> name map is learned positionally from
  the full segments (`_learn_ids`), then applied to every segment, so
  position no longer matters anywhere.
* **There is no "partial final segment".** Until 2026-09-28 the final
  segment of every DSC25 run seemed to store 21 of 25 arrays, without
  Temperature, Heat Flow, Heat Flow Phase and Total Heat Capacity - which are
  exactly its four flagged arrays. `_learn_aliases` filled Temperature from
  Sample Sensor Temperature and Heat Flow from Heat Flow T1 (bit-identical in
  every full segment); that and the analysis-cache pin (section 5c) remain
  as fallbacks for a file whose ids cannot be learned, and no file here
  needs them now (0 partial segments in the 467 readable files here, from
  1 or 2 in every DSC25 file and 1 in every SDT650 file).
* **"TRIOS displays only 2605 of the final segment's 2640 samples"** was the
  same thing: the last 35 samples' Heat Flow is flagged (and Temperature's
  last 5). The export has all 2640 rows, with those cells blank; the analysis
  cache holds the 2605 samples that have a heat flow. The reader returns all
  2640 with NaN there; the panel trims the trailing rows where Temperature or
  Heat Flow is NaN (`model._trim_empty_ends`, the end only, so sample indices
  keep counting from the segment's start).
* History, so it is not repeated: the version before 2026-09-22 guessed the
  final segment's signals by shape ("widest temperature range") and picked
  **Set Point Temperature**. That array starts at the *programmed* 30 °C,
  while the sample had only cooled passively to ~53 °C, so the 50 K/min
  up-scan was drawn flattened and stretched back to 30 °C.
* Re-derivation if the layout changes: search the file for the first
  Temperature value shown in the `.txt` export (as f32 **and** f64, at all
  byte alignments - `np.frombuffer` at offsets 0..3/0..7). Around the hit,
  look for `<count>` ints bracketing a byte pattern; decode every length
  field in it rather than matching it (the lesson of the 33601 tag).
* Units the reader converts to (`SI_TO_UNITS`, `UNITS`): Time s -> min;
  Cell Purge (DSC25) L/s -> mL/min (OJ-12's Full export: exactly x 60000);
  the SDT ones in 3b. Signals it leaves as stored, with an empty unit: the
  DSC's Delta T / Delta Tzero (V), Heat Flow Phase (rad), Total Heat Capacity
  and the uncalibrated sensors.

## 3b. SDT650 (TGA + DSC) specifics

Checked on CN-81 (TRIOS 5.1.1, one 39001-sample ramp, with its export), the
six DESY runs (TRIOS 5.1.1, a ramp and a 3000-sample isothermal each, no
export) and 66 further SDT `.tri`/`.txt` pairs on the development machine.

* **SI units.** Weight in **kg** (x 1e6 -> mg), Weight Corrected Heat Flow
  in **W/kg** (x 1e-3 -> W/g), Sample Flow and Balance Flow in **L/s**
  (x 60000 -> mL/min, the instrument's 100 mL/min purge), Heat Flow in W,
  Weight Change in %, Set Point, Temperature Difference in °C, Power
  Requested / Delivered in W (TRIOS's own [Signal List] of the export names
  these units).
* **No sample-size field.** The sample mass is the reference Weight Change
  is taken against: `Weight / (Weight Change / 100)`, constant to 3.2e-7 of
  itself over every segment of the 124 SDT runs here that have one, and
  equal to the export's Sample Mass to the 6 figures the reader writes in
  all 67 pairs (CN-81: 21.547323 mg against the export's 21.54732 mg; Heat
  Flow divided by TRIOS's own normalised array gives the same).
  `_mass_from_weight` derives it, and `head['mass_source']` says `'derived
  from the weight'` (a sample-size field is `'recorded'`). It refuses a
  ratio that is not positive at every sample, or that wanders by more than
  1e-4 of itself (`MASS_SPREAD`).
* **A negative weight is no mass.** CN-112_119, CN-122_123 and CN-130_131
  (DESY, 2025) record a Weight of -99.9 / -99.5 / -92.1 mg against a Weight
  Change of +99.99 to +100.6 %. The ratio is a negative "mass", TRIOS's own
  normalised curve is upside down with it, and Weight Corrected Heat Flow
  (Heat Flow / Weight) is upside down too. The reader refuses both: such a
  file has NO sample mass and no Heat Flow (Normalized), and says why. Their
  OPEN siblings (CN-119, CN-123, CN-131) are positive and normal. What
  counts is the SIGN OF THE RATIO, not of the weight: CN-H2bdc sublimes
  away and ends at -0.19 mg and -1.11 % together, and its ratio is one
  mass, 16.6726 mg, at every sample.
* Heat Flow (Normalized) is **Heat Flow / sample mass**, as TRIOS's export
  writes it (to its 6 significant figures in all 67 SDT pairs), not Weight
  Corrected Heat Flow, which divides by the weight LEFT at each sample and
  is only the reader's fallback when there is no mass but a positive weight.
* **The text export** calls its percentage column "Weight" with the unit %
  (and 4 exports here carry a second "Weight" in mg). `read_tri_text` names
  the % one "Weight Change", as the binary does, so "Weight" is always mg.
* The DESY isothermals were "partial (8 of 13)" because their five flagged
  arrays (3000 samples: size field `e4 2e 00 00`) did not match the
  33601-sample tag. Their later copies have no gap (section 3).
* Zinc calibration runs on the SDT (`Zinc(2)`, `Zinc(3)`, 2025) list
  "Temperature Difference" TWICE with two ids; naming by signal name keeps
  the first. Not resolved.

## 4. Step objects (segment names)

Each segment's program string (`Ramp 10,00 °C/min to 250,000 °C`) sits in a
step object **between the previous segment's arrays and this segment's
first array** (for segment 1: between the metadata and the arrays, ~31 kB
gap). Preceded by tag bytes `07 20 01 34 ... 00` - we don't parse the
tag; we regex the last `Ramp|Equilibrate|Isothermal|...`-prefixed printable
run in that window (`_step_objects`).

**The name is a .NET length-prefixed string, and the length byte is part of
the printable run.** For a name of 32..126 bytes the length byte is itself a
printable character: `20` (' ') for 32, `21` ('!') for 33, `22` ('"') for 34.
This section used to list the `21` as the last tag byte; it is the length of
`Ramp 10,00 °C/min to 250,000 °C`, which is 33 bytes (the degree sign counts
two), and every step name in OJ-12, SES-2 and SES-4 happens to be 33 bytes.
CN-119 (DSC25, 2024) has `Ramp 10.00 °C/min to 210.0000 °C`, 34 bytes, prefix
`22`: stripping only ' ' and '!' left `"Ramp ...`, which is not a step verb,
so every heating step was invisible and its arrays were merged into the
cooling segment before it - 3 segments read out of 7, with the wrong names.
`_step_name` now recognises the byte by its VALUE (the length of what
follows), whatever character it happens to be. Verified: all three CN-119
runs match their `.txt` exports segment by segment.

CN-119 also shows that a `.tri` can hold NO analyses while its export has
several: the audit trail at the end of the file records each analysis being
performed and then deleted, after the export was written. An empty
`analyses` for such a file is correct.

## 5. Analyses (onsets, integrations) - the part the `.txt` cannot give you

Every user-added analysis is stored (after the last segment's arrays) as a
**chain of three structures, in this order**:

```
[cache]  <rows:int32><cols:int32> then rows*cols float64   (optional)
[index]  uint32 row indices 0,1,2,3,...                    (always)
[record] float64 fields + 16-byte GUID + step-name string  (always)
```

1. **Cache** - the analyzed curve, copied. For Onset analyses: 2 columns
   `(Temperature, Heat Flow normalized W/g)`. For Peak Integration: 4
   columns `(Temp, HF·1000, Time_s, Temp)`. Crucially the cache holds the
   segment's **own float32 samples** (as f64), so `cache == segment` is an
   *exact* float comparison for the right segment and never for any other
   (different runs differ in sensor noise). **This is the attribution
   mechanism**: cache → segment (`_tri_match_cache`, `_cache_eq`).
   The cache block's data ends *exactly* at the index array's first byte -
   that arithmetic identity is how cache and analysis are linked.
2. **Index array** - consecutive uint32 (a row-selection into the cache;
   may be a few rows shorter than the segment). Found by searching for
   `00 00 00 00 01 00 00 00 02 00 00 00 ...` (`struct.pack('<8I', *range(8))`)
   and expanding. Runs shorter than 200 are ignored.
3. **Record** - its float64 fields start **exactly 30 bytes** after the
   index array ends, behind a fixed header (`_record_start`, `RECORD_HEAD`):
   `01 00 01 00 <u32> 0f 2f 01 <u32> 10 2f 02 <u32> <u32> <u32>`. Same in
   TRIOS 5.1.1 and 6.0, for all 14 analysis models in OJ-12. Display copies
   start `24 2f 01 ...` instead and are skipped by that check.
   **Do not search for the record by value.** Until 2026-09-22 the reader
   scanned byte by byte for the first pair of plausible temperatures. On
   SES-4 it matched 4 bytes early: the header's last u32 (`02 00 00 00`)
   followed by a cursor of 60.799 °C (a widened float32, so its float64 starts
   `00 00 00 c0`) reads as the float64 **-2.0**, and so did the second cursor.
   -2.0 is a plausible temperature; the onset was drawn at 0 °C.
   Field offsets (float64, relative to record start):
   * **Onset/Endset point** (re-decoded 2026-09-28): TRIOS's own tangent
     CONSTRUCTION as three (x, y) points, then the two cursors:

     | Offset | Onset | Endset |
     | :-- | :-- | :-- |
     | `+0/+8` | P0: flat cursor x, y on the baseline tangent | P0: on the inflection tangent, at the curve's y at the transition cursor |
     | `+16/+24` | P1: the intersection; x IS the result | P1: same |
     | `+32/+40` | P2: on the inflection tangent, at the curve's y at the transition cursor | P2: flat cursor x, y on the baseline tangent |
     | `+86/+94` | first cursor (x, curve y): the FLAT one | first cursor: the TRANSITION one |
     | `+132/+140` | second cursor: the transition one | second cursor: the flat one |

     TRIOS's export calls the flat cursor "Onset cursor x" for BOTH models
     (for an endset: "Transition cursor x 93,465 / Onset cursor x
     116,637"). Until 2026-09-28 the reader took `+0` as the first cursor,
     which is right for an onset (P0 has the flat cursor's x) and wrong for
     an endset (OJ-12: 93.8469 where the cursor is 93.4654), named the two
     the other way round, and handed Python the transition cursor as the
     flat one - its endset came out at 95.12 against TRIOS's 108.024 (now
     108.057). The old note "`+32`/`+86` hold repeats" was wrong.
     Verified: P1.x equals the stored result in all 571 onset/endset/Tg
     records on the development machine; the cursor names and values
     equal the export's for all 177 onsets and 42 endsets an export lists
     (DSC25 and SDT650); an endset is no longer resting on one record.
   * **The unit of a record's y is TRIOS's DISPLAY unit of the analysed
     curve**, checked by the cursors' "curve y" (+94, +140) against the
     curve at the cursor: Heat Flow (Normalized) in **W/g** (764 cursors,
     within 6e-4 relative, the nearest sample being up to 0.04 K away),
     the weight in **%** (366 cursors, within 2e-5), Heat Flow in **mW**
     (CN-33, a DSC25 run without a sample mass, analysed on the unnormalised
     curve: 8 cursors, exactly 1000 x the stored watts). The reader returns
     the construction as `entry['construction'] = [[x degC, y], ...]` with y
     in the unit of its own column `entry['variable']` (`RECORD_Y_SCALE`:
     mW -> W). A `.txt` export stores no construction at all.
   * **Glass transition**: its four points (below) are the same kind of
     construction: P0 on the onset tangent at the onset cursor, P1 the
     onset, P2 the end, P3 on the end tangent at the end cursor; the three
     tangents are P0P1, P1P2 and P2P3.
   * Peak Integration: `+0` baseline cursor x0, `+96` baseline cursor x1.
     **The result values (enthalpy, peak T) are NOT stored in the record**
     - TRIOS recomputes them. We do the same (`_tri_integral_results`,
     linear baseline in time; reproduces TRIOS to ~0.1-0.4 %).
   * **Glass transition** (decoded 2026-09-23 on OJ-12, TRIOS 5.1.1): NOT a
     cursor pair with a result between them. Four **(x, y) pairs** at a
     16-byte stride, all float64:
     `+0/+8` onset cursor, `+16/+24` **onset**, `+32/+40` **end**,
     `+48/+56` end cursor. Reading `+132` as the second cursor (the
     tangent-model layout) yields 0.0, which is why Tg looked undecodable.
     The onset point's y matches the curve to 2e-5 W/g; the end point's y is
     0.025 W/g off it, because it lies on the END TANGENT rather than on the
     data. **Midpoint** is not stored and is not the mean of onset and end
     (78.849 vs 78.911): it is the temperature at which the curve crosses
     the half height between the two stored y values, which reproduces
     TRIOS's exported `Midpoint 78,911 °C` exactly. `+336` holds 78.248,
     unidentified - do not use it as the midpoint.
     Implemented in `_tg_fields`.
   * `+235`: the analysis's 16-byte GUID (also listed in a 72-byte-stride
     registry of all analyses, ~entry: GUID + 2 more GUIDs + `02 00...`).
   * ~`+390` onward: length-prefixed string
     `"<filename> - <step name> - <model name>"` - the **model** is read
     from here (` - Onset point`, ` - Peak Integration`, ` - Endset point`).
     The step *name* is ambiguous (three segments can share it) - that's
     precisely why the caches are needed.
   * **The analysed variable** (decoded 2026-09-28, `_record_variable`):
     about +850 to +1350 behind the record fields come the analysis's
     points as two small CALCULATED arrays (section 3 layout, flags `0x10`,
     no gap): x, then y, each with its signal's 16-byte id at -38..-22. x is
     Temperature's id; **y's id is the analysed curve** - what the export
     calls "Analysed variables: Heat Flow (Normalized) vs. Temperature" or
     "Weight vs. Temperature". The calculated curves have fixed ids
     (`CALCULATED_IDS`): `2f85cc58 bf1cb343 a3f97135 b826d88a` Heat Flow
     (Normalized), `ba6bb3c0 fdeeab47 935c906a 39544545` Weight (%) (the
     reader's "Weight Change"); a recorded signal's id is named through the
     learned id map (CN-33's analyses on "Heat Flow"). The reader returns
     it as `entry['variable']`, and `read_tri_text` sets the same key from
     an export's "Analysed variables" line (its "Weight" is the reader's
     "Weight Change"). Verified against every export that states
     it: 159 "Heat Flow (Normalized) vs. Temperature" and 60 "Weight vs.
     Temperature" records, all agreeing. On an SDT run most onsets and
     endsets are on the WEIGHT (CN-81: both onsets; its integration is on
     the heat flow), and a Python check run on the heat flow for them was
     16 K off; it now runs on the variable.

Second-and-later analyses on an **already-cached curve store no cache**.
Instead, right before their index array: the step-name string plus
`<rows:u32>` = the analyzed curve's row count (u32 at `index_start-4`).
Match by unique segment length; fall back to the most recent cache.

**Display copies**: each analysis also appears 2-3 more times in the file
(chart annotation objects) with the same strings but *without* the float
fields at the record offsets. The record-structure check (plausible
temperatures at `+0` and `+16`/`+96`) rejects them; a `(model, cursor
values)` dedupe set catches stragglers.

## 5b. Fallback attribution ("Option B") when the cache is missing

`_tri_attribute_geometric` runs only when no cache matched. Order of evidence:

1. **Step-name filter** (applied by the caller, from the record's
   `"<file> - <step> - <model>"` string). Exact and reliable - it alone
   isolates a uniquely-named segment (e.g. the only 50 °C/min ramp).
2. **Peak Integration → area test.** Integrate between the stored baseline
   cursors on each candidate; the analysis was drawn around a real feature,
   so a wrong segment integrates to ~0. Decisive on the reference file
   (13.261 vs 6.193 J/g; 1.761 vs 0.014 J/g). Accepted when the winner is
   ≥1.5× the runner-up. **No "already used" filter** - two integrations on
   one up-scan is normal.
3. **Onset/Endset → creation order**, *not* geometry.

> **Do not re-add tangent-reconstruction ranking for onsets.** It was built,
> and measured against known-good attributions: it reproduces the onset to
> ~0.1 K yet still ranked the *wrong* segment first (repeat up-scans of one
> sample differ by ~0.02 K, far under the reconstruction error) and ranked
> the correct 50 K/min segment **last of seven**. A confident-sounding wrong
> answer is worse than an honest "order-based guess". Measured accuracy with
> caches artificially disabled: **3/5**, vs **5/5** through the cache path.
> Every fallback decision prints its reasoning.

## 5c. The cache search must run BACKWARDS from the chain (learned twice)

A cache is linked to its analysis by adjacency: its float64 block ends exactly
where the chain's index array begins, i.e.

    header_offset + 8 + rows*cols*8 == index_array_start

So the way to find it is to scan **backwards** from the chain start testing that
identity. A forward scan that walks the document region consuming blocks as it
finds them does NOT work -- it locks onto the first plausible header and steps
over later ones. On the reference file the forward scan finds 4 caches where
there are 8, and every cache-less analysis then inherits the previous
attribution, silently piling everything onto segment 1.

Two further points that both cost a debugging cycle:

* **The cache can be SHORTER than its segment.** TRIOS stores the samples
  that have a heat flow: 2605 rows for a segment holding 2640 samples, whose
  last 35 heat-flow samples are flagged (section 3). Comparisons must be
  prefix-wise (`cache[:n]` against `array[:n]`), not equal-length; a
  segment whose FIRST samples are flagged is matched at an offset
  (`_cache_eq` tries 0..64).
* That same cache is what pinned a partial segment's signals exactly. On
  the reference file it identified segment 7's Temperature as array 12 and
  its Heat Flow as array 15 -- a mapping that is neither a prefix nor a fixed
  shift of the signal list, and which no shape heuristic recovers (three
  other arrays span an equally plausible temperature range). Since the
  flagged arrays are read (2026-09-28) segment 7 is not partial and this
  is a fallback no file here reaches.

With the backward search in place: all 7 segments match the export, and all 8
recovered analyses attribute to the correct scan, including telling apart
repeat up-scans whose onsets differ by 0.016 K.

## 6. Validation protocol (do this after ANY re-derivation)

Export the same run from TRIOS as `.txt` (tab-separated) and check:

1. every segment: `max|Δ|` of Time/Temp/HF columns ≤ export rounding
   (~5e-5 °C, ~5e-7 W/g), the same number of rows, and every BLANK cell of
   the export exactly where the reader has NaN (a flagged sample) - a NaN
   where the export has a number is a failure too. `read_tri_text` drops a
   row with a blank cell, so the comparison reads the export itself
   (`tests/test_reader.py::_read_export`). 2026-09-28: all 164 DSC25 and 67
   SDT650 pairs on the development machine pass this;
2. every analysis: cursor values match the `[Analysis]` blocks; onset
   results match exactly; enthalpy within ~0.5 %;
3. attribution: at least one analysis must sit on a segment that is
   *uniquely* determined (e.g. the only 50 °C/min ramp) - it must land there.

The test harness used originally is easy to rebuild: read both files with
`read_tri()` (it dispatches binary vs text by content) and diff.

## 7. How the layout was found (method recap, for the next model)

1. Hexdump first 256 bytes → readable .NET length-prefixed metadata.
2. Search the binary for the **first data values from the `.txt` export**
   (f32/f64, all byte alignments) → found the arrays and the cached-curve
   blocks; block sizes ÷ 8 = clean row counts → dtype and shape.
3. Search for **int32 == known row counts** (13210, 13200, 2605) → found
   the array tag (count appears twice around a fixed signature) and the
   cache headers `(rows, cols)`.
4. Locate analyses by searching for their **known result values** (f64
   with ±5e-4 tolerance, since the `.txt` rounds to 3 decimals).
5. **Byte-diff two records of the same model** (two Onset points): the
   only differences were the float fields, one 16-byte GUID, and a single
   ASCII digit inside the step-name string → proved the record layout and
   that the record itself does NOT reference the segment by id.
6. The chain arithmetic (`cache_end == index_start`, record right after
   the index) fell out of the offsets; the cache's float-exact equality
   with exactly one segment supplied the attribution.
7. Validate per §6. (First attempt had two bugs caught this way: wrong
   temp column for 2-col caches, and the seg-3/5 heater-vs-sample-temp
   mixup on the irregular final segment.)

## 8. Known limitations / untested territory

* Endset-point records: decoded in section 5 and verified on 42 endsets
  with an export (2026-09-28). The earlier "same offsets as Onset
  (`+0/+16/+132`)" was wrong for the first cursor (section 5).
* **Every onset, endset and Tg record on the development machine was made
  on a HEATING segment** (surveyed 2026-09-28: 422 onsets, 147 endsets, 3
  glass transitions with a known variable). The construction's layout in
  section 5 - flat point first for an onset, last for an endset - is
  therefore unverified on a cooling segment, and so is which cursor TRIOS
  stores first there. The panel's own analyses take the flat side by
  acquisition order (`measure.acquisition_order`), and only DRAW a
  stored construction segment by segment, so its order does not matter
  for the drawing; a cooling record would be worth one look.
* **The indium ramp (corrected 2026-09-28).** This section used to say that
  the RAMP segment of `Indium-03082026(1).tri` (DSC25 calibration, TRIOS
  6.0, 13 signals, 4801 points) stores only 9 of its signals, without
  Temperature and Heat Flow, and that nothing could fill them. They were
  there all along, as flagged arrays (section 3): Temperature, Heat Flow,
  Heat Flow Phase and Total Heat Capacity, the last 5 / 35 / 5 / 5 samples
  flagged. Read, the ramp matches the run's export (4801 rows, blanks
  exactly on the flags) and the melt integrates to **28.56 J/g at
  158.17 °C from the .tri alone**, pointing UP in the stored Heat Flow: the
  files are recorded EXO DOWN, which the audit trail and the export header
  say independently.
  What the old note measured is still true and still a warning: `Heat Flow
  = -254.8 * Delta T` on the isothermal segment (correlation -1.000), a
  Delta-Tzero sensitivity of 63.4 µV/K (type E), and a reconstruction
  (`Ts = T0 - dT0/S`, `q = -dT/(S R)`) from constants fitted at one point
  gave 24.5 J/g against 28.5 - a plausible-looking wrong curve, exactly
  what this file warns about. It is not needed.
* **A segment that really records no heat flow** has not been seen since
  the flagged arrays are read. The reader would return it without the
  signal, and the panel reports it (`Scan.missing_for`,
  `loader.segments_without_heat_flow`).
* MDSC (modulated), isothermal-only, and multi-procedure files: untested.
  The signals-per-segment derivation assumes each segment stores the same
  signal list.
* A signal list that names one signal twice (SDT `Zinc(2)`, `Zinc(3)`:
  "Temperature Difference", two ids) keeps the first; the segment counts as
  partial.
* The final-segment Temp/HF heuristics without ids or an analysis cache are
  best-effort (a warning is printed); no file here reaches them now.
* **The flag semantics are inferred**: every recorded array here carries
  only `0` and `0x08000008`, and "any nonzero flag is NaN" is confirmed by
  the exports' blanks. `0x10` has only ever been seen on calculated curves;
  among those, OJ-12's segment-1 analysis curve has `0x08000000`.
* The 33601-sample KC files the round-25 tag was written for are not on the
  development machine; the general layout has not been run on them.
* If a user analyzed curve A, then B, then A again, and the third analysis
  stored no cache and its row count is ambiguous, the "most recent cache"
  fallback would mis-attribute. Not observed; the row-count reference has
  always been present in cache-less records so far.
