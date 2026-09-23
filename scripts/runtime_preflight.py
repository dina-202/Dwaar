"""Operator-facing Dwaar runtime readiness preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.runtime_readiness import evaluate_runtime_readiness


def main() -> int:
    report = evaluate_runtime_readiness()
    print(
        json.dumps(
            {
                "ready": report.ready,
                "checks": [
                    {
                        "code": item.code.value,
                        "status": item.status.value,
                        "message": item.message,
                    }
                    for item in report.checks
                ],
            },
            sort_keys=True,
        )
    )
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
