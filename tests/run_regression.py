"""Regression runner for the CA Notice Explainer (Architecture Phase 1).

Standard library only — no pytest, no new dependencies. Runs the EXISTING
runtime pipeline (modules.notice_explainer.explain_notice) against the four
sample notices in data/sample_notices/, saves each generated analysis under
tests/outputs/ (the controlled regression directory), and compares against
baselines stored in tests/baselines/.

Reported statuses:
    PASS               pipeline succeeded, structural checks passed, and a
                       baseline exists whose coverage checks also passed
    FAIL               pipeline succeeded but structural checks failed
    BASELINE_MISSING   pipeline succeeded and checks passed; no baseline file
                       exists yet for this notice
    EXECUTION_ERROR    pipeline raised an exception or returned success=False

Exit code: 0 if every notice is PASS or BASELINE_MISSING, 1 otherwise.

Comparison semantics: LLM output is non-deterministic, so raw text equality
is never asserted. A generated analysis passes when (a) all eight required
section titles are present, (b) the output is non-trivial in size, and (c)
when a baseline exists, the baseline itself contains all eight sections and
every status label present in the baseline is also present in the fresh
output. This catches real regressions (missing sections, allegations that
stop being labelled) without failing on normal LLM variation.

Usage:
    python tests/run_regression.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.notice_explainer import explain_notice  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data" / "sample_notices"
TESTS_DIR = Path(__file__).resolve().parent
BASELINES_DIR = TESTS_DIR / "baselines"
OUTPUTS_DIR = TESTS_DIR / "outputs"

# Unique title fragments from the eight sections of prompts/notice_prompt.txt.
REQUIRED_SECTION_TITLES = (
    "NOTICE FACTS",
    "ALLEGATIONS",
    "COMPUTATION REVIEW",
    "URGENCY",
    "EVIDENCE GAPS",
    "LEGAL DEFENCES",
    "DRAFT REPLY",
    "CLIENT MESSAGE",
)

# The five Fact status labels (prompts/notice_prompt.txt CORE EVIDENCE
# DISCIPLINE; matches modules/domain_models.FactStatus).
STATUS_LABELS = (
    "[CONFIRMED]",
    "[ALLEGED BY DEPARTMENT]",
    "[NOT AVAILABLE]",
    "[REQUIRES VERIFICATION]",
    "[INFERRED]",
)

# Previous real runs produced 14,648–19,875 chars. This floor catches
# degenerate/truncated outputs without coupling to exact lengths.
MIN_EXPLANATION_CHARS = 5000


def discover_notices() -> list[Path]:
    """Return the four sample notice PDFs, sorted by name."""
    return sorted(DATA_DIR.glob("NOTICE_*.pdf"))


def section_titles_found(text: str) -> set[str]:
    lowered = text.lower()
    return {title for title in REQUIRED_SECTION_TITLES if title.lower() in lowered}


def status_labels_found(text: str) -> set[str]:
    return {label for label in STATUS_LABELS if label in text}


def structural_problems(explanation: str) -> list[str]:
    problems: list[str] = []
    if len(explanation) < MIN_EXPLANATION_CHARS:
        problems.append(
            f"explanation too short ({len(explanation)} chars < {MIN_EXPLANATION_CHARS})"
        )
    missing = set(REQUIRED_SECTION_TITLES) - section_titles_found(explanation)
    if missing:
        problems.append("missing sections: " + ", ".join(sorted(missing)))
    return problems


def run_one(notice_pdf: Path) -> tuple[str, str]:
    """Run the existing pipeline on one notice and return (status, detail)."""
    try:
        result = explain_notice(notice_pdf.read_bytes())
    except Exception as exc:  # noqa: BLE001 — the runner must report, not die
        return "EXECUTION_ERROR", f"{type(exc).__name__}: {exc}"

    if not result.get("success"):
        return (
            "EXECUTION_ERROR",
            f"pipeline returned success=False: {result.get('error', '')[:300]}",
        )

    explanation = result["explanation"]

    # Controlled regression directory for generated outputs.
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUTS_DIR / (notice_pdf.stem + ".analysis.md")
    output_path.write_text(explanation, encoding="utf-8")

    problems = structural_problems(explanation)

    baseline_md = BASELINES_DIR / (notice_pdf.stem + ".baseline.md")
    if baseline_md.exists():
        baseline_text = baseline_md.read_text(encoding="utf-8")
        baseline_problems = structural_problems(baseline_text)
        if baseline_problems:
            problems.append(
                "baseline itself fails structural checks: " + "; ".join(baseline_problems)
            )
        missing_labels = status_labels_found(baseline_text) - status_labels_found(explanation)
        if missing_labels:
            problems.append(
                "status labels in baseline but missing from fresh output: "
                + ", ".join(sorted(missing_labels))
            )

    if problems:
        return "FAIL", "; ".join(problems)
    if not baseline_md.exists():
        return "BASELINE_MISSING", f"output saved to {output_path.name} (no baseline found)"
    return "PASS", f"output saved to {output_path.name}; baseline comparison passed"


def main() -> int:
    notices = discover_notices()
    if not notices:
        print(f"No NOTICE_*.pdf files found in {DATA_DIR}")
        return 1

    print(f"Regression runner — {len(notices)} notices; existing pipeline (Gemini)")
    print(f"Baselines dir : {BASELINES_DIR}")
    print(f"Outputs dir   : {OUTPUTS_DIR}")
    results: list[tuple[str, str]] = []
    for notice_pdf in notices:
        print(f"\n=== {notice_pdf.name} ===")
        status, detail = run_one(notice_pdf)
        print(f"  {status}: {detail}")
        results.append((notice_pdf.name, status))

    print("\n--- SUMMARY ---")
    for name, status in results:
        print(f"{status:18} {name}")

    failures = [s for _, s in results if s in ("FAIL", "EXECUTION_ERROR")]
    ok = len(results) - len(failures)
    print(f"\n{ok} PASS/BASELINE_MISSING, {len(failures)} FAIL/EXECUTION_ERROR")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
