"""Notice explainer. Glue between pdf_reader and llm_client.

This module has exactly one job: turn raw PDF bytes into a structured
explanation by chaining the other modules together. It owns no PDF logic and
no Gemini logic itself — it just calls them in the right order and shapes the
result into a dict the UI can consume.
"""

from datetime import date
from modules.pdf_reader import extract_text
from modules.llm_client import build_notice_prompt, call_gemini


def explain_notice(pdf_bytes: bytes) -> dict:
    """
    Explain a government notice PDF: extract its text, run it through Gemini,
    and return a structured result dict.

    Args:
        pdf_bytes: Raw bytes of the notice PDF, as read from Streamlit's
            file_uploader (i.e. uploaded.read()).

    Returns:
        A dict with four keys, present in every outcome:

        success     : bool — True only when a Gemini explanation was produced.
        explanation : str  — the Gemini analysis (5 sections + draft reply) on
                      success, or "" on failure.
        raw_text    : str  — the text extracted from the PDF. Empty on failure
                      (including the scanned-PDF case).
        error       : str  — a clean, user-safe message on failure, or "" on
                      success.

        Failure modes covered:
        - PDF has no text layer (scanned/photo notice) -> success False with a
          "Scanned PDF detected" error and empty raw_text.
        - PDF can't be read (corrupt/not a PDF) -> success False, raw_text "".
        - Gemini call failed or returned empty -> success False, raw_text still
          carries the extracted text so the UI could offer a fallback.
    """
    try:
        text = extract_text(pdf_bytes)
    except RuntimeError as e:
        return {"success": False, "error": str(e), "raw_text": "", "explanation": ""}

    if not text.strip():
        return {
            "success": False,
            "error": (
                "Scanned PDF detected — no text layer found. "
                "Please upload a digital PDF downloaded from a government portal."
            ),
            "raw_text": "",
            "explanation": "",
        }

    today = date.today().strftime("%d-%B-%Y")
    prompt = build_notice_prompt(text, today)
    explanation = call_gemini(prompt)

    if explanation.startswith("Error"):
        return {
            "success": False,
            "error": explanation,
            "raw_text": text,
            "explanation": "",
        }

    return {"success": True, "explanation": explanation, "raw_text": text, "error": ""}
