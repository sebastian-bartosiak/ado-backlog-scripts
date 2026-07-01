#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "ruamel.yaml",
#   "azure-devops",
#   "python-dotenv",
#   "html2text",
# ]
# ///
"""
ADO Set Owner — Assign one or more work items to yourself (or someone else).

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT, ADO_ME
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Assign work items to yourself, someone else, or clear assignment.")
    p.add_argument("work_item_id", type=int, nargs="+", help="One or more work item ids")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--to", metavar="PERSON", help="Assign to this person instead of ADO_ME")
    g.add_argument("--unassign", action="store_true", help="Clear the assignment")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)

    if args.unassign:
        assignee = None
    elif args.to:
        assignee = args.to
    else:
        assignee = lib.require_me(cfg)

    lib.banner("ADO SET OWNER")
    print(f"  Items    : {', '.join(str(i) for i in args.work_item_id)}")
    print(f"  Assign to: {assignee or '(cleared)'}")
    print(f"  Org      : {cfg.org_url}")
    print(f"  Project  : {cfg.project}")

    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok\n")

    if assignee is None:
        ops = [lib.op("remove", f"/fields/{lib.FIELD_ASSIGNED_TO}")]
    else:
        ops = [lib.op("add", f"/fields/{lib.FIELD_ASSIGNED_TO}", assignee)]

    failures = 0
    for item_id in args.work_item_id:
        try:
            client.update_work_item(ops, item_id)
            print(lib.c(f"  ✓ [{item_id}] assigned to {assignee or '(cleared)'}", lib.GREEN))
        except Exception as e:
            failures += 1
            print(lib.c(f"  ✗ [{item_id}] FAILED: {e}", lib.RED))

    print()
    if failures:
        sys.exit(f"{failures} of {len(args.work_item_id)} item(s) failed.")


if __name__ == "__main__":
    main()
