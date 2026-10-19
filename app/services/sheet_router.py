"""Decide which pages each extraction pass should read.

Classification is deterministic: it reads the sheet title/number from a page's
text and tags it with the trades that page serves. Routing is generous on
purpose - a page can feed several passes, general-notes pages feed all of them,
and if a pass matches no page it falls back to the whole PDF. So a misread page
can only add a few extra pages to a pass, never silently drop a trade.
"""

from __future__ import annotations

import re

# Each rule: a regex over the page text (case-insensitive) -> trade tags it adds.
# Residential sets often put MEP and openings ON the architectural floor plan,
# so the floor plan is tagged broadly, and keywords matter more than the sheet
# letter for A-sheets. S/E/M/P letters are trade-specific and trusted.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (r"\bfoundation\b|\bfooting\b|slab[-\s]?on[-\s]?grade", ("foundation", "structural")),
    (r"\bframing\b|\bshear\b|\brafter\b|\bjoist\b|structural", ("framing", "structural")),
    (r"roof\s*plan", ("roofing", "framing")),
    (r"\belevation", ("envelope", "roofing")),
    (r"\bsection\b|\bdetail", ("envelope", "framing")),
    (r"stucco|exterior\s*finish|finish\s*schedule", ("envelope",)),
    (r"floor\s*plan|\bflr\s*plan", ("floorplan", "interior", "openings")),
    (r"door\s*schedule|window\s*schedule|\bschedule\b", ("schedule", "openings")),
    (r"electrical|lighting|power\s*plan", ("electrical",)),
    (r"plumbing", ("plumbing",)),
    (r"mechanical|\bhvac\b", ("mechanical",)),
    (r"title\s*24|\bt24\b|\bcf1r\b|energy", ("energy", "mechanical")),
    (r"general\s*note|specification|\bcode\b|cover\s*sheet", ("general",)),
    # Sheet-number letters in a title block (trade-specific ones only).
    (r"\bS-?\d", ("structural",)),
    (r"\bE-?\d", ("electrical",)),
    (r"\bM-?\d", ("mechanical",)),
    (r"\bP-?\d", ("plumbing",)),
]

# The trade tags each pipeline group wants. "general" is added to every group.
GROUP_TRADES: dict[str, set[str]] = {
    "foundation": {"foundation", "structural"},
    "framing": {"framing", "structural", "roofing"},
    "envelope": {"roofing", "envelope"},
    "interior": {"interior", "floorplan"},
    "openings": {"openings", "schedule", "floorplan"},
    "mep": {"electrical", "plumbing", "mechanical", "energy", "floorplan"},
}


def classify_pages(page_texts: list[str]) -> list[set[str]]:
    """Tag every page with the trades it serves, from its text."""
    classifications: list[set[str]] = []
    for text in page_texts:
        tags: set[str] = set()
        for pattern, trade_tags in _RULES:
            if re.search(pattern, text, re.IGNORECASE):
                tags.update(trade_tags)
        classifications.append(tags)
    return classifications


def pages_for_group(
    classifications: list[set[str]],
    group_name: str,
    total_pages: int,
) -> list[int]:
    """Page indices to send to one group, with a whole-PDF fallback.

    Returns every page whose tags the group wants, plus general-notes pages.
    If nothing matches (or the group is unknown, or classification was empty),
    returns all pages, so the pass is never starved of its sheets.
    """
    wanted = GROUP_TRADES.get(group_name)
    if not wanted or not classifications:
        return list(range(total_pages))

    selected = [
        index
        for index, tags in enumerate(classifications)
        if tags & wanted or "general" in tags
    ]
    # A match that is only general-notes pages is not enough to trust; fall back.
    has_real_match = any(
        classifications[i] & wanted for i in selected
    )
    if not selected or not has_real_match:
        return list(range(total_pages))
    return selected
