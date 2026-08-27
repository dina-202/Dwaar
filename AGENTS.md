# AGENTS.md — Rulebook for CA Notice Explainer Tool
> Read this file completely before doing anything.
> Then read PROJECT_MEMORY.md for current state.
> These two files are your complete briefing every time.

---

## ⚡ AUTO-MEMORY RULE — MOST IMPORTANT RULE
After EVERY response you give — no matter how small — you must:

1. Open PROJECT_MEMORY.md
2. Find the CURRENT SESSION block at the top of the SESSION LOG
3. Append what you just did as a new log entry in this exact format:

```
[PROMPT #X — HH:MM]
Task     : what Dina asked
Did      : what you actually did
Files    : which files were touched and what changed
Errors   : any errors hit (or "none")
Attempts : how many tries if there was an error
Fix      : what solved the error (or "n/a")
Status   : DONE / PARTIAL / FAILED
```

4. Update the CURRENT STATE section to reflect right now
5. Save the file

Do this even if the prompt was just a question or explanation.
This is non-negotiable. The file is the only memory across power cuts, crashes, and restarts.

---

## PROJECT OVERVIEW
**Product:** CA Notice Explainer Tool
**What it does:** CA uploads a GST or Income Tax notice PDF → get plain-language explanation + draft reply letter
**Users:** Chartered Accountants and tax consultants in India
**MVP Goal:** Working demo to show in 10 CA offices

---

## TECH STACK — DO NOT CHANGE WITHOUT ASKING DINA
```
Language       : Python 3.11+
UI             : Streamlit
PDF Reading    : PyMuPDF  →  import as: import fitz
LLM            : Google Gemini 2.5 Flash  →  SDK: google-generativeai
API Key Mgmt   : python-dotenv  →  keys in .env only
Hosting        : Streamlit Cloud (free)
Dev OS         : Windows native (no WSL)
```

---

## FOLDER STRUCTURE
```
ca-ai-tool/
├── AGENTS.md                  ← this file
├── PROJECT_MEMORY.md          ← auto-updated after every prompt
├── app.py                     ← Streamlit UI only, zero logic
├── requirements.txt
├── .env                       ← API keys, never commit
├── .gitignore
├── modules/
│   ├── __init__.py
│   ├── pdf_reader.py          ← only job: extract text from PDF
│   ├── llm_client.py          ← only job: talk to Gemini
│   └── notice_explainer.py   ← only job: combine pdf + prompt + llm
└── prompts/
    └── notice_prompt.txt      ← prompt text, editable without touching code
```

---

## CODING RULES

- `app.py` handles UI only. All logic lives in modules/
- Each module does exactly one job. Never mix responsibilities.
- All prompts in prompts/ folder as .txt files. Never hardcode in Python.
- All API keys from .env via load_dotenv(). Never hardcode.
- Every external API call must have try/except.
- Use st.session_state for anything that must survive Streamlit reruns.
- New library = ask Dina first. Then update requirements.txt immediately.

---

## WHAT AGENTS MUST NEVER DO
- ❌ Rewrite working code not related to current task
- ❌ Skip updating PROJECT_MEMORY.md after a response
- ❌ Hardcode API keys or model names
- ❌ Add databases, auth, or user accounts (out of MVP scope)
- ❌ Add libraries not in the approved stack without asking

---

## QUICK REFERENCE — CORRECT CODE PATTERNS

### Gemini
```python
import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
response = model.generate_content(prompt)
result = response.text
```

### PyMuPDF
```python
import fitz  # pip package is "pymupdf", import name is "fitz"

def extract_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text
```

### Streamlit file upload
```python
uploaded = st.file_uploader("Upload Notice PDF", type="pdf")
if uploaded:
    pdf_bytes = uploaded.read()  # returns bytes, not a file path
```

---

## GOTCHAS
1. `import fitz` = PyMuPDF. pip install pymupdf. Not the same name.
2. `load_dotenv()` must run BEFORE os.getenv() or you get None.
3. Streamlit reruns the whole script on every click. Use st.session_state.
4. Gemini free tier = 1,500 req/day, 10 RPM. Don't loop calls fast.
5. st.rerun() not st.experimental_rerun()

---

## .env TEMPLATE
```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.6-flash
```

---

## AGENT ROSTER
| Agent | Where | Role |
|---|---|---|
| Claude Code | Antigravity / Claude.ai | Primary builder |
| DeepSeek V4 | Antigravity | Second opinion, unsticking |
| Codex | Codex tool | Isolated bug fixes |

All agents follow these same rules. All agents update PROJECT_MEMORY.md after every prompt.
