"""Per-trade ("per-sheet") analysis: several focused passes instead of one.

The single call must hold an entire plan set in attention and cover every trade
at once, which is why whole trades go missing and two runs of the same plan
disagree. This pipeline instead asks the model a narrow question several times -
"only the foundation", "only the MEP" - over the same drawings. Each pass has
less to track, so coverage goes up and run-to-run drift goes down.

The cost is one model call per group instead of one per job. That trade (more
tokens for more completeness) is why this is opt-in via settings.analysis_mode.

Only the orchestration here is unit-tested (with the model calls mocked); the
extraction quality itself must be checked with a live run and the eval harness.
"""

from __future__ import annotations

import contextvars
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.tracing import observe
from app.schemas.ai import AIAnalysisResponse, ConfidenceLevel, DetectedItem
from app.services.ai_service import (
    _ANALYSIS_INSTRUCTIONS,
    build_input_content,
    request_items,
)
from app.services.pdf_pages import encode_subset, extract_page_texts, page_count
from app.services.sheet_router import classify_pages, pages_for_group


@dataclass(frozen=True)
class ExtractionGroup:
    name: str
    focus: str


# Disjoint slices of the scope. Together they cover the same trades the single
# call is asked for; apart, each pass can concentrate on one of them.
EXTRACTION_GROUPS: tuple[ExtractionGroup, ...] = (
    ExtractionGroup(
        "foundation",
        "Extract ONLY foundation and concrete scope: continuous footings and "
        "grade beams (linear feet), slab-on-grade measured separately for house, "
        "garage and porch, slab reinforcing, under-slab vapor barrier, sand or "
        "base course, and isolated pads.",
    ),
    ExtractionGroup(
        "framing",
        "Extract ONLY structural framing: exterior and interior wall framing "
        "(one face, via wall_segments), gable framing, ceiling joists, floor "
        "joists, roof framing and sheathing, and shear panels or anchor bolts "
        "that are actually tagged on the plans - not rows from a manufacturer "
        "schedule.",
    ),
    ExtractionGroup(
        "envelope",
        "Extract ONLY the exterior envelope: roofing or shingles measured per "
        "roof with its pitch, roof underlayment, gutters and downspouts, "
        "exterior stucco or siding (via wall_segments) with openings_sqft, weep "
        "screed, insulation, and roof or gable vents.",
    ),
    ExtractionGroup(
        "interior",
        "Extract ONLY interior finishes: drywall or gypsum board for walls and "
        "ceilings (via wall_segments and height), wet-area tile backer, flooring "
        "and floor coverings, baseboard, and paint.",
    ),
    ExtractionGroup(
        "openings",
        "Extract ONLY doors and windows. Count each tagged symbol on the floor "
        "plans and join it to its schedule row for the size. Do not emit a "
        "schedule row that has no symbol on the plan.",
    ),
    ExtractionGroup(
        "mep",
        "Extract ONLY MEP scope: plumbing fixtures (water closets, lavatories, "
        "showers, tubs, kitchen and utility sinks, water heater, hose bibbs), "
        "electrical (service and panels, receptacles, lights, switches, smoke "
        "and carbon-monoxide alarms), and HVAC (heat pump, mini-split or FAU, "
        "exhaust fans, range hood, dryer exhaust).",
    ),
)


def _confidence_rank(confidence: ConfidenceLevel | None) -> int:
    order = {
        ConfidenceLevel.HIGH: 3,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.LOW: 1,
    }
    return order.get(confidence, 0)


def _is_better(candidate: DetectedItem, current: DetectedItem) -> bool:
    """Prefer the richer duplicate: one with a quantity, then higher confidence."""
    candidate_key = (
        candidate.quantity is not None,
        _confidence_rank(candidate.confidence),
    )
    current_key = (
        current.quantity is not None,
        _confidence_rank(current.confidence),
    )
    return candidate_key > current_key


def _dedupe_key(name: str | None) -> str:
    """A name key that ignores word order and punctuation.

    "Water Closets (Ultra Flush)" and "Ultra Flush Water Closets" are the same
    fixture reported by two passes; both reduce to the same key so merge keeps
    one. Each word is kept whole and sorted, so unrelated items stay distinct.
    """
    words = re.findall(r"[a-z0-9]+", (name or "").casefold())
    return " ".join(sorted(words))


def merge_items(groups: list[list[DetectedItem]]) -> list[DetectedItem]:
    """Flatten the passes into one list, keeping the best of any duplicate name.

    The groups are disjoint by design, so collisions are rare, but a wall could
    be named the same way by two passes. Keying on the order-insensitive name
    keeps one copy and prefers the better-measured one, preserving first-seen
    order.
    """
    best_by_name: dict[str, DetectedItem] = {}
    order: list[str] = []
    for group_items in groups:
        for item in group_items:
            key = _dedupe_key(item.item_name)
            if key not in best_by_name:
                best_by_name[key] = item
                order.append(key)
            elif _is_better(item, best_by_name[key]):
                best_by_name[key] = item
    return [best_by_name[key] for key in order]


def _group_page_content(
    file_path: str,
    group_name: str,
    classifications: list[set[str]],
    total_pages: int,
    full_content: dict,
):
    """The input for one pass: its routed pages, or the whole PDF as a fallback."""
    if not classifications:
        return full_content
    indices = pages_for_group(classifications, group_name, total_pages)
    if len(indices) >= total_pages:
        return full_content  # no narrowing to be had; reuse the full encode
    return encode_subset(file_path, indices, Path(file_path).name)


def _run_group(group: ExtractionGroup, file_content: dict) -> list[DetectedItem]:
    instructions = (
        f"{_ANALYSIS_INSTRUCTIONS}\n\nFOCUS FOR THIS PASS:\n{group.focus}"
    )
    result = request_items(
        file_content,
        instructions,
        f"Extract the {group.name} takeoff items from this blueprint.",
    )
    return result.items


@observe(name="analyze-blueprint-pipeline")
def analyze_blueprint_pipeline(file_path: str) -> AIAnalysisResponse:
    full_content = build_input_content(Path(file_path))

    # Route pages so each pass reads only its sheets. On any failure (e.g. a
    # scanned PDF with no text), classifications stay empty and every pass gets
    # the whole PDF - no worse than before.
    classifications: list[set[str]] = []
    total_pages = 0
    if settings.page_routing:
        try:
            texts = extract_page_texts(file_path)
            total_pages = len(texts)
            classifications = classify_pages(texts)
        except Exception:
            classifications = []
    if total_pages == 0:
        try:
            total_pages = page_count(file_path)
        except Exception:
            total_pages = 0

    contents = {
        group.name: _group_page_content(
            file_path, group.name, classifications, total_pages, full_content
        )
        for group in EXTRACTION_GROUPS
    }

    groups: list[list[DetectedItem]] = []
    errors: list[str] = []

    workers = max(1, min(settings.pipeline_max_workers, len(EXTRACTION_GROUPS)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for group in EXTRACTION_GROUPS:
            ctx = contextvars.copy_context()
            content = contents[group.name]
            future = executor.submit(
                lambda g=group, c=content, cx=ctx: cx.run(_run_group, g, c)
            )
            futures[future] = group
        for future in futures:
            group = futures[future]
            try:
                groups.append(future.result())
            except Exception as exc:
                errors.append(f"{group.name}: {exc}")

    if not groups:
        raise ValueError("Every analysis pass failed: " + "; ".join(errors))

    return AIAnalysisResponse(items=merge_items(groups))
