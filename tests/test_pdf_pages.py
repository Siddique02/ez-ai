import base64
import io
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.services.pdf_pages import (
    build_subset_bytes,
    encode_subset,
    extract_page_texts,
    page_count,
)


def _make_pdf(num_pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    directory = tempfile.mkdtemp()
    path = Path(directory) / "plan.pdf"
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


class PdfPagesTests(unittest.TestCase):
    def test_page_count(self):
        self.assertEqual(page_count(_make_pdf(5)), 5)

    def test_extract_page_texts_returns_one_entry_per_page(self):
        texts = extract_page_texts(_make_pdf(3))
        self.assertEqual(len(texts), 3)  # blank pages, so each is empty-ish

    def test_build_subset_keeps_only_requested_pages(self):
        path = _make_pdf(6)
        data = build_subset_bytes(path, [0, 2, 4])
        self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 3)

    def test_build_subset_ignores_out_of_range_indices(self):
        path = _make_pdf(3)
        data = build_subset_bytes(path, [0, 99, -1])
        self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 1)

    def test_encode_subset_is_a_base64_pdf_input_file(self):
        path = _make_pdf(4)
        content = encode_subset(path, [1, 3], "plan.pdf")
        self.assertEqual(content["type"], "input_file")
        self.assertEqual(content["filename"], "plan.pdf")
        self.assertTrue(content["file_data"].startswith("data:application/pdf;base64,"))
        raw = base64.b64decode(content["file_data"].split(",", 1)[1])
        self.assertEqual(len(PdfReader(io.BytesIO(raw)).pages), 2)


if __name__ == "__main__":
    unittest.main()
