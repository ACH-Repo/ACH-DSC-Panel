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
