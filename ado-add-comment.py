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
ADO Add Comment — Add a comment to a work item (no state change).

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Add a comment to a work item.")
    p.add_argument("work_item_id", type=int)
    p.add_argument("text", help="Comment text (rendered as markdown)")
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

    try:
        lib.add_comment(client, cfg.project, args.work_item_id, args.text)
    except Exception as e:
        sys.exit(f"ERROR: Failed to add comment: {e}")

    print(lib.c(f"  ✓ [{args.work_item_id}] comment added", lib.GREEN))


if __name__ == "__main__":
    main()
