"""PDF reading. This module has exactly one job: PDF bytes in, text out."""

import fitz  # pip package is "pymupdf", import name is "fitz"


def extract_text(pdf_bytes: bytes) -> str:
    """
    Extract all text from a PDF supplied as raw bytes.

    Streamlit's file_uploader hands us bytes, not a file path, so the PDF is
    opened from an in-memory stream instead of from disk.

    Args:
        pdf_bytes: Raw bytes of the PDF file.

    Returns:
        All text in the document as a single string, pages joined in page order.
        An empty string means the PDF has no text layer (i.e. it is a scan or
        photo of a notice). That is not an error — there is simply nothing to
        extract, and the caller should tell the user to upload a digital PDF.

    Raises:
        RuntimeError: The bytes could not be opened as a PDF — corrupt file,
            password-protected, or not a PDF at all. The message is safe to
            show to the user.
    """
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "".join(page.get_text() for page in doc)
    except Exception as e:
        raise RuntimeError(f"Could not read this PDF: {e}") from e
    finally:
        if doc is not None:
            doc.close()
