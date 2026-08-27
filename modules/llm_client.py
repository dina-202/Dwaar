"""Gemini client. This module has exactly one job: talk to Gemini.

It loads the API key from .env, configures the SDK once at import time, and
exposes two functions — one to build a prompt from the template file, one to
send it to the model and get the text back.
"""

import os
import time
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

# Configure once at module level. Must run load_dotenv() BEFORE os.getenv()
# or the key comes back None.
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
_model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# The prompt template lives outside the code so Dina can edit it without
# touching Python. Resolve it relative to this file, not the CWD.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "notice_prompt.txt"


def build_notice_prompt(notice_text: str, today: str) -> str:
    """
    Load the notice prompt template and inject the notice text into it.

    Args:
        notice_text: The extracted text of the notice, as returned by
            modules.pdf_reader.extract_text().
        today: Human-readable today's date string (e.g. "26-August-2026"),
            injected into the {today} placeholder in the template.

    Returns:
        The full prompt ready to send to Gemini. On failure (missing or
        unreadable template file) it returns a clean error string instead of
        raising, so the caller can show it directly in the UI.
    """
    try:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return f"Could not load prompt template ({_PROMPT_PATH.name}): {e}"
    return template.replace("{notice_text}", notice_text).replace("{today}", today)


def _generate_once(prompt: str) -> str:
    """One attempt at a Gemini call. Returns the text, or "" on failure."""
    response = client.models.generate_content(
        model=_model_name,
        contents=prompt,
    )
    return response.text or ""


def call_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini and return the model's text response.

    The API call is wrapped so the caller never sees an exception: any error
    is returned as a clean string prefixed with "Error". If the model comes
    back with an empty response (which happens when a response is blocked),
    it retries once after 2 seconds before giving up.

    Args:
        prompt: The full prompt string, as built by build_notice_prompt().

    Returns:
        The model's text response, or an error string starting with "Error".
    """
    try:
        text = _generate_once(prompt)
        if not text.strip():
            time.sleep(2)
            text = _generate_once(prompt)
        if not text.strip():
            return "Error: Gemini returned an empty response."
        return text
    except Exception as e:
        return f"Error: {e}"
