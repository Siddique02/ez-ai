import unittest

from app.core.tracing import mask_file_data


class MaskFileDataTests(unittest.TestCase):
    def test_uploaded_pdf_is_replaced_with_its_size(self):
        pdf = "data:application/pdf;base64," + "A" * 5000
        request = {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": "plan.pdf",
                            "file_data": pdf,
                        },
                        {"type": "input_text", "text": "Analyze this blueprint"},
                    ],
                }
            ]
        }

        masked = mask_file_data(data=request)

        content = masked["input"][0]["content"]
        self.assertEqual(
            content[0]["file_data"],
            f"<data:application/pdf;base64 omitted, {len(pdf):,} characters>",
        )
        # Everything that is not a file is kept as it was.
        self.assertEqual(content[0]["filename"], "plan.pdf")
        self.assertEqual(content[1]["text"], "Analyze this blueprint")

    def test_uploaded_image_is_replaced(self):
        image = "data:image/jpeg;base64,/9j/4AAQ"

        masked = mask_file_data(data=[image])

        self.assertEqual(
            masked,
            [f"<data:image/jpeg;base64 omitted, {len(image)} characters>"],
        )

    def test_other_values_are_unchanged(self):
        for value in ("New Door D1", 7, 6.6667, None, {"count": 7}):
            with self.subTest(value=value):
                self.assertEqual(mask_file_data(data=value), value)


if __name__ == "__main__":
    unittest.main()
