"""Operator-friendly Dwaar product tour-readiness rehearsal."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.product_rehearsal import run_product_rehearsal


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="dwaar-tour-") as temp:
            report = run_product_rehearsal(temp)
    except Exception:
        print(
            json.dumps(
                {
                    "tour_ready": False,
                    "error": "product_rehearsal_failed",
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "tour_ready": report.tour_ready,
                "checks": [
                    {
                        "code": item.code,
                        "status": "pass" if item.passed else "blocked",
                        "detail": item.detail,
                    }
                    for item in report.checks
                ],
            },
            sort_keys=True,
        )
    )
    return 0 if report.tour_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
