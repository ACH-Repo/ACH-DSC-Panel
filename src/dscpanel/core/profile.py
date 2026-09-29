"""What is particular to THIS plotter's data: DSC and SDT/TGA.

DSC-Panel is the first of a family of stacked-trace plotters on one
handling (PXRD and IR are next). The handling is shared; what a kind of
data wants differently - how F frames it, which analyses exist, which
decorators a figure starts with - is gathered here, so a sibling changes
this module rather than the handling code. (Christian, 2026-09-29: "keep in
mind this is a particular quirk of DSC/SDT data".)

UI-free: plain values.
"""

#: F frames everything at once (Christian, 2026-09-29: the two-step F -
#: x first, then y, as in MoloM's PXRD window - "is basically useless
#: here"). A spectra plotter, where the x range is the question, sets True.
FIT_STAGED = False
