"""Operator-facing runtime + backup posture command for Dwaar."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.operator_health import evaluate_operator_health


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check Dwaar runtime and nominated backup posture."
    )
    parser.add_argument("backup_dir")
    parser.add_argument(
        "--max-backup-age-hours",
        type=float,
        required=True,
        help="Explicit maximum acceptable backup age in hours.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_operator_health(
            backup_dir=args.backup_dir,
            max_backup_age_hours=args.max_backup_age_hours,
            now=datetime.now(timezone.utc),
        )
    except (ValueError, OSError):
        print(
            json.dumps(
                {"healthy": False, "error": "health_check_invalid"},
                sort_keys=True,
            )
        )
        return 2

    payload = {
        "healthy": report.healthy,
        "backup_age_hours": (
            None
            if report.backup_age_hours is None
            else round(report.backup_age_hours, 3)
        ),
        "checks": [
            {
                "code": item.code.value,
                "status": item.status.value,
                "message": item.message,
            }
            for item in report.checks
        ],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
