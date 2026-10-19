import base64
import re
import time
from pathlib import Path
from typing import Any
from app.core.config import settings
from app.core.tracing import OpenAI, observe
from app.schemas.ai import AIAnalysisResponse


client = OpenAI(api_key=settings.OPENAI_API_KEY)

# A momentary TPM burst (e.g. parallel pipeline passes overlapping) returns 429
# and is transient, so we wait and retry rather than failing the pass.
_RATE_LIMIT_MAX_RETRIES = 5


def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return "rate_limit" in text or "429" in text


def _retry_wait_seconds(exc: Exception, attempt: int) -> float:
    # Honor the "try again in 1.519s" hint when present, else back off.
    match = re.search(r"try again in ([\d.]+)s", str(exc))
    if match:
        return min(float(match.group(1)) + 0.25, 30.0)
    return min(2.0 * (2 ** attempt), 30.0)


_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_ANALYSIS_INSTRUCTIONS = """
You are a senior construction estimator performing a complete quantity
takeoff for the whole project, covering every trade the drawings show.

Work through the blueprint sheet by sheet:
1. Identify each sheet's type from its title and title block: floor plan,
   roof plan, elevations, sections, site plan, foundation plan, framing plan,
   details, schedules, or notes.
2. Take each quantity from the sheet made for it, exactly once:
   - Doors, windows, fixtures, devices, and equipment: count them on the
     floor plans only.
   - Wall heights, exterior finishes, and trim: read them from elevations and
     sections.
   - Roofing, gutters, and roof penetrations: from the roof plan.
   - Slab, footings, and foundation items: from the foundation plan.
   - Framing members: from the framing plans.
   - Site work: from the site plan.
3. Elevations, sections, and details show the same doors, windows, and
   fixtures again from another view. Never add their occurrences to the
   floor plan count; that double-counts the item.
4. When several floor plans show different floors, add their counts together
   into one item.
5. Include only new work. Skip anything marked existing, (E), or "to remain".
   Include demolition only when the drawings show demolition work.
   On an addition or remodel this is critical: the existing house is NOT new
   work. Do not measure the existing slab, walls, roof, footings or fixtures.
   Measure only the added area and the elements the drawings explicitly mark as
   new, altered or (N). When a dimension covers existing plus new, take only the
   new portion.

Cover every trade the drawings support, including:
- Site work, concrete slab, footings, and foundation
- Framing, sheathing, and structural hardware shown on plans
- Roofing, underlayment, gutters, and downspouts
- Exterior finishes such as stucco, siding, and trim
- Insulation, drywall, and ceilings
- Doors, windows, and skylights
- Flooring, baseboard, cabinets, and countertops
- Painting
- Plumbing fixtures such as toilets, sinks, showers, tubs, and water heaters
- Electrical devices such as smoke detectors, carbon monoxide detectors,
  exhaust fans, lights, and outlets
- HVAC equipment such as mini-splits, furnaces, and ducts
Items required by the notes (for example "provide rain gutters") are part of
the takeoff too.

Schedules and legends:
- Treat schedules and legends as reference information. They define symbols,
  types, dimensions, and descriptions, but a schedule row is not an installed
  occurrence by itself.
- Count actual symbols or tagged occurrences placed on the floor plans. Do not
  count symbols shown only in legends, schedules, notes, or examples.
- Use schedule information to enrich an item only after its corresponding tag
  or symbol is found on the drawing.
- For each door, window, or other scheduled component, count its symbol on the
  floor plans first. If its count is zero, do not return an item for that
  schedule row.
- After finding a scheduled symbol on the plan, join it to the matching schedule
  row and extract its type and size. For a two-part door or window size, the
  first value is width and the second value is height. Store those values in
  width and height even though the item's measurement_type is "count". Leave
  length null for doors and windows.

How to measure:
- Report what you measure, never a total you computed. The backend multiplies,
  sums wall runs, applies the roof slope, and deducts openings. Your job is to
  read raw numbers off the drawing and put them in the right fields. Do not do
  arithmetic.
- Use the dimensions written on the drawings. Only when a needed dimension is
  not written, estimate it from the drawing scale and set confidence to low.
- Normalize every length, width, and height to decimal feet. For example,
  2'-8" is 2.6667 feet, 6'-8" is 6.6667 feet, and 1'-6" is 1.5 feet.
- A material thickness or specification is never a length, width, or height.
  "7/8 inch stucco", "1/2 inch gypsum", "#4 bar", "R-15" describe the material;
  they go in item_name, never in a dimension field. A house wall is tens of
  feet long, not fractions of an inch.
- When count is set, length, width, and height describe one occurrence, not
  the total. Six 5'-0" headers are count 6 and length 5.0, never length 30.0.
- Horizontal surfaces (slab, flooring, ceilings): length by width of the area
  they cover. Measure the house, the garage, and the porch as separate items;
  never one rectangle around the whole building.
- Walls and wall finishes (stucco, siding, sheathing, drywall, insulation,
  paint, weep screed): these are AREA items, never linear. Use measurement_type
  "area". Put the length of each wall run in wall_segments, one number per run,
  and put the wall height in height. The backend adds the runs up and multiplies
  by height. Never report a wall finish as a single perimeter length, and never
  use the building's overall length by width - that is a floor area, not a wall
  area. Exterior finishes cover the exterior wall runs; drywall
  covers both faces of interior walls and the inside face of exterior walls.
- To deduct door and window openings from a wall finish, put their combined
  area in openings_sqft. The backend subtracts it.
- Roofs: give the plan (footprint) length and width and the pitch as rise:run,
  for example "4:12", in pitch. The backend converts to the sloped surface.
  Measure every roof separately - house, garage, and porch each get their own
  item. Without a written pitch, give the plan area and set confidence to low.
- Concrete slabs are areas in sqft; footings and grade beams are linear in ft.

Output rules:
- Never invent a dimension, count, quantity, unit, or construction item. Use
  null when a numeric value is not visibly supported.
- When an item is clearly required but its quantity cannot be determined,
  still return it with the unknown fields null and confidence low, so a
  reviewer can complete it.
- The unit field describes the final estimating quantity, not the dimensional
  fields. A counted door or window therefore uses unit "ea" while its width and
  height are still decimal feet.
- Use measurement_type "count" for discrete objects such as doors, windows,
  fixtures, and equipment. Put the number of occurrences in count and leave
  quantity null; the backend calculates the final quantity.
- Use measurement_type "linear" for linear measurements. Put the measured
  length in length and leave quantity null.
- Use measurement_type "area" for surfaces, and leave quantity null so the
  backend can calculate it. For a horizontal surface give length and width. For
  a wall finish give wall_segments and height. For a roof give length, width,
  and pitch. Only when the drawing explicitly states a finished total area, and
  no dimensions are available, place that value in quantity and leave the
  dimensions null.
- Use consistent estimating units: "ea" for counts, "ft" for linear feet,
  and "sqft" for square feet unless the drawing explicitly uses another unit.
- Return one item per distinct material or scope. Do not split one item into
  duplicates, and do not merge different materials into one item.
- Be complete and consistent. Before finishing, check that every trade listed
  above that the drawings support is represented: foundation and footings,
  framing, roofing, exterior finish, insulation, drywall, doors and windows,
  flooring, and every plumbing fixture, electrical device, and HVAC unit shown.
  Do not drop a trade that is present on the drawings.
- Set confidence to high only when the item and its measurement are clear,
  medium when supported but somewhat ambiguous, and low when review is needed.
- Keep item names concise, construction-specific, and faithful to the drawing.
  Include a schedule symbol such as W2 or D1 when available, but do not put
  dimensions in item_name because they belong in width and height.

Example 1: if the floor plan contains three W7 symbols and the W7 schedule row
says NEW WINDOW with size 3'-0" x 5'-0", return one item named "New Window W7"
with measurement_type "count", count 3, quantity null, unit "ea", length null,
width 3.0, and height 5.0. If the elevations also show W7 windows, the count is
still 3. Do not return W8 merely because W8 has a schedule row; return it only
if a W8 symbol is actually found on the floor plan.

Example 2 (method only): to measure exterior stucco, read the written length of
every exterior wall run on the floor plan, including wings such as an attached
garage, and list each run as its own number in wall_segments. Put the wall
height from the elevations or sections in height. Do not add the runs up
yourself and do not use the footprint's overall length by width, which is a
floor area and the wrong quantity for any wall.

Example 3 (method only): for a 4:12 roof over a house and an attached garage,
return two items. Each gives its own plan length and width and pitch "4:12".
Do not merge them into one rectangle and do not pre-multiply by the slope.

The examples illustrate methods only. Every number you return must be measured
from this project's drawings; never copy a number from these instructions in
place of measuring it.
""".strip()


def _encode_file(file_path: Path) -> str:
    return base64.b64encode(file_path.read_bytes()).decode("utf-8")


def _build_input_content(file_path: Path) -> dict[str, Any]:
    extension = file_path.suffix.lower()

    if extension != ".pdf" and extension not in _IMAGE_MIME_TYPES:
        raise ValueError(
            "Unsupported blueprint format. Expected PDF, PNG, JPG, or JPEG."
        )

    encoded_file = _encode_file(file_path)

    if extension == ".pdf":
        return {
            "type": "input_file",
            "filename": file_path.name,
            "file_data": f"data:application/pdf;base64,{encoded_file}",
            "detail": "high",
        }

    mime_type = _IMAGE_MIME_TYPES[extension]
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded_file}",
        "detail": "high",
    }


def build_input_content(file_path: Path) -> dict[str, Any]:
    """Public encoder for callers such as the per-sheet pipeline."""
    return _build_input_content(file_path)


def request_items(
    file_content: dict[str, Any],
    instructions: str,
    prompt: str,
) -> AIAnalysisResponse:
    """One structured extraction call against an already-encoded blueprint.

    Shared by the single-call analysis and the per-sheet pipeline so both go
    through exactly the same model, schema and settings. Transient 429 rate
    limits are retried with backoff so a brief TPM burst does not fail a pass.
    """
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            response = client.responses.parse(
                model=settings.llm_model,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [
                            file_content,
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
                text_format=AIAnalysisResponse,
                # temperature=0,
                store=False,
            )
            break
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < _RATE_LIMIT_MAX_RETRIES:
                time.sleep(_retry_wait_seconds(exc, attempt))
                continue
            raise

    if response.output_parsed is None:
        raise ValueError("The AI response did not contain a parsed takeoff result")

    return response.output_parsed


@observe(name="analyze-blueprint")
def analyze_blueprint(file_path: str) -> AIAnalysisResponse:
    # The pipeline runs focused passes for better coverage; the single call is
    # the cheaper default. The import is deferred to avoid a circular import.
    if settings.analysis_mode == "pipeline":
        from app.services.analysis_pipeline import analyze_blueprint_pipeline

        return analyze_blueprint_pipeline(file_path)

    file_content = _build_input_content(Path(file_path))
    return request_items(
        file_content,
        _ANALYSIS_INSTRUCTIONS,
        "Analyze this blueprint and extract its measurable construction "
        "takeoff items.",
    )
