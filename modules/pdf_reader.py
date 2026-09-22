"""PDF text extraction with an additive page-aware provenance path."""

from typing import List

import fitz  # pip package is "pymupdf", import name is "fitz"


def extract_page_texts(pdf_bytes: bytes) -> List[str]:
    """Extract embedded text for each PDF page in physical page order.

    Page list index 0 corresponds to document page 1. This function does not
    run OCR; a page with no embedded text is represented by an empty string.

    Args:
        pdf_bytes: Raw bytes of the PDF file.

    Returns:
        One text string per physical PDF page, preserving page order.

    Raises:
        RuntimeError: The bytes could not be opened/read as a PDF.
    """
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return [page.get_text() for page in doc]
    except Exception as error:
        raise RuntimeError(f"Could not read this PDF: {error}") from error
    finally:
        if doc is not None:
            doc.close()


def extract_text(pdf_bytes: bytes) -> str:
    """Backward-compatible flattened PDF text extraction.

    The result is exactly the ordered concatenation of extract_page_texts(),
    preserving the previous Phase-2 behavior while allowing newer callers to
    retain page boundaries for deterministic source-page validation.

    An empty string means the PDF contains no embedded text. OCR is a separate
    ingestion step and is intentionally not performed here.
    """
    return "".join(extract_page_texts(pdf_bytes))
