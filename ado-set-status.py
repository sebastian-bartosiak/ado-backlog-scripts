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
ADO Set Status — Change a work item's state, optionally with a comment.

State names are process-template-specific (e.g. Agile: New/Active/Resolved/Closed,
Scrum: New/Approved/Committed/Done). Pass whatever state string your org uses.

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Change a work item's state, optionally with a comment.")
    p.add_argument("work_item_id", type=int)
    p.add_argument("state", help="Target state, e.g. Active, Resolved, Closed, Done")
    p.add_argument("--comment", metavar="TEXT", help="Comment to attach (rendered as markdown)")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)

    print(f"  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    ops = [lib.op("replace", f"/fields/{lib.FIELD_STATE}", args.state)]
    try:
        client.update_work_item(ops, args.work_item_id)
    except Exception as e:
        sys.exit(f"ERROR: Failed to set state: {e}")
    print(lib.c(f"  ✓ [{args.work_item_id}] state → {args.state}", lib.GREEN))

    if args.comment:
        try:
            lib.add_comment(client, cfg.project, args.work_item_id, args.comment)
        except Exception as e:
            sys.exit(f"ERROR: State changed but comment failed: {e}")
        print(lib.c(f"  ✓ [{args.work_item_id}] comment added", lib.GREEN))


if __name__ == "__main__":
    main()
