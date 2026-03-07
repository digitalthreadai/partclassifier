"""Extract text and table data from specification PDF documents."""

import pdfplumber


class PDFExtractor:
    def extract(self, pdf_path: str) -> str | None:
        """Return all text + table content from a PDF as a single string."""
        try:
            parts: list[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    # Plain text
                    text = page.extract_text()
                    if text:
                        parts.append(f"[Page {page_num}]\n{text}")

                    # Tables (convert to pipe-delimited rows)
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if row and any(cell for cell in row):
                                parts.append(
                                    " | ".join(str(cell).strip() if cell else "" for cell in row)
                                )

            return "\n".join(parts) if parts else None

        except Exception as e:
            print(f"    PDF extraction error ({pdf_path}): {e}")
            return None
