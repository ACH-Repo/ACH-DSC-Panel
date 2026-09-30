"""What is particular to THIS plotter's data: DSC and SDT/TGA.

This program is the first of a family of stacked-trace plotters on one
handling. The handling is shared; what a kind of data wants differently -
how F frames it, which analyses exist, which decorators a figure starts
with - is gathered here, so a sibling changes this module rather than the
handling code.

UI-free: plain values.
"""

#: F frames everything at once: a two-step F - x first, then y - is of
#: no use for DSC. A spectra plotter, where the x range is the question,
#: sets True.
FIT_STAGED = False
