"""Split a blueprint PDF so each analysis pass reads only the pages it needs.

The user always uploads the whole set. Re-sending all 13 pages to all six
passes is what makes analysis slow and token-heavy. These helpers let the
pipeline carve out the relevant pages for one pass and send just those, while
the user's upload is untouched. Everything here is pure file work - no AI.
"""

from __future__ import annotations
import base64
import io
from pathlib import Path
from pypdf import PdfReader, PdfWriter


def page_count(file_path: str | Path) -> int:
    return len(PdfReader(str(file_path)).pages)


def extract_page_texts(file_path: str | Path) -> list[str]:
    """Return the text layer of each page, or "" for a page that has none.

    A scanned set with no text layer yields all-empty strings; the router then
    falls back to sending the whole PDF, so routing never makes things worse.
    """
    texts: list[str] = []
    for page in PdfReader(str(file_path)).pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    return texts


def build_subset_bytes(file_path: str | Path, page_indices: list[int]) -> bytes:
    """A new PDF containing only `page_indices`, in the given order."""
    reader = PdfReader(str(file_path))
    writer = PdfWriter()
    last = len(reader.pages) - 1
    for index in page_indices:
        if 0 <= index <= last:
            writer.add_page(reader.pages[index])

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def encode_subset(
    file_path: str | Path,
    page_indices: list[int],
    filename: str,
) -> dict:
    """Base64 input_file content for just the chosen pages (OpenAI Responses)."""
    data = build_subset_bytes(file_path, page_indices)
    encoded = base64.b64encode(data).decode("utf-8")
    return {
        "type": "input_file",
        "filename": filename,
        "file_data": f"data:application/pdf;base64,{encoded}",
        "detail": "high",
    }
