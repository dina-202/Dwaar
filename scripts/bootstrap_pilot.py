"""Command-line bootstrap for the first local Dwaar pilot firm."""

import argparse
import os
import sys

from modules.pilot_bootstrap import bootstrap_initial_firm


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create the first Dwaar pilot firm and grant the supplied "
            "OIDC account all current permissions. Refuses to run once "
            "a firm already exists."
        )
    )
    parser.add_argument(
        "--firm-name",
        required=True,
        help="Professional firm display name.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help=(
            "Opaque Dwaar OIDC account ID shown by the signed-in "
            "unprovisioned screen."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help=(
            "Pilot SQLite path. Defaults to DWAAR_DB_PATH environment "
            "variable."
        ),
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db_path or os.environ.get("DWAAR_DB_PATH")
    if not db_path:
        print(
            "DWAAR_DB_PATH is required (or pass --db-path).",
            file=sys.stderr,
        )
        return 2

    try:
        firm, grant = bootstrap_initial_firm(
            db_path,
            firm_name=args.firm_name,
            user_id=args.user_id,
        )
    except Exception as error:
        print(f"Bootstrap failed: {error}", file=sys.stderr)
        return 1

    print("Dwaar pilot bootstrap complete.")
    print(f"Firm ID: {firm.firm_id}")
    print(f"Firm: {firm.display_name}")
    print(f"User ID: {grant.user_id}")
    print(
        "Permissions: "
        + ", ".join(
            sorted(permission.value for permission in grant.permissions)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
