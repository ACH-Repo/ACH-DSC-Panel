# Next requests (Christian)

Written down when they came in. Remove an item once it is done and logged in
PLAN.md.

---

2026-09-30, parked ("only when enough things to correct have piled up"):

1. In `Hbc_Tgs.dscpanel` the top page-margin blade jumps when moved and
   suddenly leaves far too much white space. Likely cause, not yet
   confirmed in his hands: the "ZIF-62" label hangs from CN-103's HIDDEN
   first up-scan, about 2.3 cm above the page, so the top margin "holds" it
   (`page_needs` counts every visible decorator) and a blade never goes
   below that - 2.26 cm. To decide: should a label whose curve is hidden,
   or one entirely off the page, count for a margin at all?

---

2026-10-08, to talk through in a new chat:

2. **Import analyses, with all their settings, from another session.**
   He has two sessions of the same source file, one of which lost its
   analyses. Wanted: a quick way to bring the analyses (or very similar
   ones) of one figure into another. Note: the session he was looking at
   (`CAU-Ga-H8TTPB_SDT.dscpanel`) still HOLDS its 10 analyses - it only
   could not find its file, and the missing-file handling of the same day
   brings them back once the file is found. Open questions: match curves
   by file (path, name, or contents), segment and signal; a panel
   analysis is measured again from its cursors/span, a file's own only
   gets its styling (`session._restore_analysis`); what if the curve
   already has one of the same model there? Analyses exist in IR-Panel and
   PXRD-Panel too - ask whether it is family-wide.

3. **Copy properties (Ctrl+C / Ctrl+V between objects).** His idea: any
   object's settings as a JSON string on the clipboard, pasted onto
   another object of the same kind; or Blender's way, a small pop-up menu
   at the pointer (like X: faces / edges / vertices) to choose what to
   paste, worked with the arrow keys and Enter.
   How reasonable: very. Ctrl+C already puts the selected LABELS on the
   clipboard as JSON of their own (`MainWindow.copy_selected`), and every
   kind already has its fields listed (the session's state, and each
   settings window's `FIELDS` / `INDIVIDUAL` - the per-object ones that
   must not be copied, like an analysis's cursors). Proposal to put to
   him: Ctrl+C copies any selection; Ctrl+V with objects of the same kind
   selected opens the pop-up - "Paste as new", "All settings", "Colour",
   "Text and font", "Sizes"... - and nothing selected pastes as now. No
   new key (Ctrl+Shift+V is "mirror vertically"; a QMenu at the pointer
   already does the arrow keys, Enter and first letters). One undo step;
   between tabs too, which would also answer item 2 (copy a curve's
   analyses, paste them onto the same file's curve in the other figure).
   Shared handling: ask whether it is family-wide.
