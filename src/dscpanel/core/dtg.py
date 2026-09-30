"""DTG: the derivative of a thermogravimetric mass curve.

Worked out here from the m% the file records; the derivative arrays TRIOS
stores are flagged "calculated" (TRI-FORMAT.md 3b) and are never read as a
signal.

* **Against time first.** The temperature jitters sample to sample and
  doubles back at a segment's start (CLAUDE.md, "a DSC curve is a
  PARAMETRIC curve"), so dividing by dT sample by sample would divide by
  noise. The slope is taken against TIME, and per degree it is that slope
  over the segment's heating rate, fitted once for the whole segment.
* **Smoothed by a local straight line**: at each sample, the least-squares
  slope of the samples within half the window either side. That is the
  Savitzky-Golay first derivative for a quadratic on even spacing, and it
  stays right where the spacing is not even and at the ends, where the
  window is simply cut short. The window is given in KELVIN of the ramp
  (`Scan.dtg_window`), turned into samples with the heating rate.
* **A loss is positive**: DTG = -dm/dt in %/min, and -dm/dt / |beta| in
  %/degC, whichever way the segment runs.

UI-free: numpy only.
"""

import numpy as np

#: The two units a DTG is drawn in.
PER_DEGREE = "%/\u00b0C"
PER_MINUTE = "%/min"
UNITS = (PER_DEGREE, PER_MINUTE)

#: The smoothing window a new DTG curve starts with, in kelvin.
WINDOW_K = 2.0
#: Below this heating rate (K/min) a segment is isothermal: no per-degree
#: derivative exists, and a window in kelvin means nothing.
ISOTHERMAL_RATE = 0.05
#: Half-width in samples where a window in kelvin cannot be converted.
FALLBACK_HALF = 5


def heating_rate(time_min, temp_c):
    """The segment's heating rate in K/min, fitted over its measured
    samples (a straight line through T(t)), or None."""
    if time_min is None or temp_c is None:
        return None
    t = np.asarray(time_min, dtype=float)
    T = np.asarray(temp_c, dtype=float)
    ok = np.isfinite(t) & np.isfinite(T)
    if ok.sum() < 3 or np.ptp(t[ok]) <= 0:
        return None
    slope = np.polyfit(t[ok], T[ok], 1)[0]
    return float(slope)


def half_window(time_min, rate, window_k):
    """Samples either side of each point that `window_k` kelvin spans."""
    t = np.asarray(time_min, dtype=float)
    steps = np.diff(t[np.isfinite(t)])
    steps = steps[steps > 0]
    if not len(steps) or rate is None or abs(rate) < ISOTHERMAL_RATE:
        return FALLBACK_HALF
    per_sample = abs(rate) * float(np.median(steps))       # kelvin
    if window_k <= 0 or per_sample <= 0:
        return 1
    return max(1, int(round(window_k / 2.0 / per_sample)))


def local_slope(x, y, half):
    """At every sample, the least-squares slope dy/dx of the samples within
    `half` either side (fewer at the ends). NaN where fewer than three
    measured samples are in reach."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    ok = np.isfinite(x) & np.isfinite(y)
    # Centre x and y (on the measured samples) before summing, or the
    # sums of squares lose every digit that matters to cancellation.
    if ok.any():
        x = x - np.mean(x[ok])
        y = y - np.mean(y[ok])
    w = ok.astype(float)
    xs = np.where(ok, x, 0.0)
    ys = np.where(ok, y, 0.0)

    def windowed(values):
        total = np.concatenate([[0.0], np.cumsum(values)])
        lo = np.clip(np.arange(n) - half, 0, n)
        hi = np.clip(np.arange(n) + half + 1, 0, n)
        return total[hi] - total[lo]

    count = windowed(w)
    sx, sy = windowed(xs), windowed(ys)
    sxx, sxy = windowed(xs * xs), windowed(xs * ys)
    with np.errstate(invalid="ignore", divide="ignore"):
        spread = sxx - sx * sx / count
        slope = (sxy - sx * sy / count) / spread
    bad = (count < 3) | ~(spread > 0) | ~np.isfinite(slope)
    slope[bad] = np.nan
    return slope


def dtg(time_min, temp_c, percent, unit=PER_DEGREE, window_k=WINDOW_K):
    """The DTG of a mass curve in `unit`, one value per sample, or None
    when it cannot be worked out (`missing` says why)."""
    if missing(time_min, temp_c, percent, unit) is not None:
        return None
    rate = heating_rate(time_min, temp_c)
    half = half_window(time_min, rate, float(window_k))
    per_minute = -local_slope(time_min, percent, half)
    if unit == PER_MINUTE:
        return per_minute
    return per_minute / abs(rate)


def missing(time_min, temp_c, percent, unit=PER_DEGREE):
    """What stops a DTG in `unit`, or None."""
    if percent is None or not np.isfinite(
            np.asarray(percent, dtype=float)).any():
        return "mass in this segment"
    if time_min is None or not np.isfinite(
            np.asarray(time_min, dtype=float)).any():
        return "time in this segment"
    if unit == PER_DEGREE:
        rate = heating_rate(time_min, temp_c)
        if rate is None or abs(rate) < ISOTHERMAL_RATE:
            return "heating rate (an isothermal segment has no %/\u00b0C)"
    return None


def factor(unit, rate):
    """What one %/degC of DTG is in `unit` (an offset converts by it)."""
    if unit == PER_DEGREE:
        return 1.0
    if rate is None or abs(rate) < ISOTHERMAL_RATE:
        return None
    return abs(rate)
