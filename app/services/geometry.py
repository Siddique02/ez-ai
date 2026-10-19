"""Pure geometry helpers for the takeoff.

These functions turn the raw measurement primitives the AI reads off a drawing
(wall-segment lengths, a roof pitch) into the dimensions the backend stores and
prices. They are deliberately free of any database, AI or trade-name knowledge:
a wall area is length x height and a 4:12 roof is steeper than its footprint by a
fixed factor, no matter what the drawing calls the material. Keeping this math in
one tested place is what makes the app behave the same on every user's PDF.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


# A single residential dimension (one wall run, one roof side) is never this
# long. A larger value almost always means a misread scale or a spec such as a
# "7/8 inch" plaster thickness captured as if it were a length.
MAX_PLAUSIBLE_DIMENSION_FT = 300.0


_PITCH_PATTERN = re.compile(
    r"""
    (?P<rise>\d+(?:\.\d+)?)      # rise, e.g. 4
    \s*(?::|/|\s+in\s+|\s+on\s+|\s+)\s*
    (?P<run>\d+(?:\.\d+)?)       # run, e.g. 12
    """,
    re.VERBOSE | re.IGNORECASE,
)


def slope_factor(pitch: str | float | None) -> float:
    """Return the factor that converts a horizontal area to a sloped one.

    A roof drawn as "4:12" rises 4 units for every 12 of run, so its true
    surface is sqrt(1 + (4/12)^2) ~= 1.0541 times its plan (footprint) area.
    An unreadable or missing pitch returns 1.0, i.e. no slope adjustment, so a
    caller never silently loses area.
    """
    if pitch is None:
        return 1.0

    if isinstance(pitch, (int, float)):
        rise, run = float(pitch), 12.0
    else:
        match = _PITCH_PATTERN.search(pitch)
        if match is None:
            return 1.0
        rise = float(match.group("rise"))
        run = float(match.group("run"))

    if run == 0:
        return 1.0

    return (1.0 + (rise / run) ** 2) ** 0.5


def sum_segments(segments: Iterable[float] | None) -> float | None:
    """Add up wall-run lengths, ignoring blanks and non-positive noise.

    The AI reports each exterior or interior wall run it traces as its own
    number. Their sum is the total wall length a finish must cover, which is the
    correct basis for stucco, drywall, siding or weep screed - never the
    building's overall length by width, which is a floor area.
    """
    if not segments:
        return None

    total = sum(value for value in segments if value and value > 0)
    return total if total > 0 else None


def is_implausible_dimension(value: float | None) -> bool:
    """True when a single dimension is non-positive or impossibly large."""
    if value is None:
        return False
    return value <= 0 or value > MAX_PLAUSIBLE_DIMENSION_FT
