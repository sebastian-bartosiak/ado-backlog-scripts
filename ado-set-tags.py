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
ADO Set Tags — Add, remove, or list tags on a work item (System.Tags).

Tags are how you make items easy to find later with ado-search.py.

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Add, remove, or list tags on a work item.")
    sub = p.add_subparsers(dest="action", required=True)

    p_add = sub.add_parser("add", help="Add one or more tags")
    p_add.add_argument("work_item_id", type=int)
    p_add.add_argument("tag", nargs="+", help="Tag(s) to add")

    p_rm = sub.add_parser("remove", help="Remove one or more tags")
    p_rm.add_argument("work_item_id", type=int)
    p_rm.add_argument("tag", nargs="+", help="Tag(s) to remove")

    p_list = sub.add_parser("list", help="List current tags")
    p_list.add_argument("work_item_id", type=int)

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

    item = lib.fetch_item(client, args.work_item_id)
    if not item:
        sys.exit(f"ERROR: Cannot fetch item {args.work_item_id}")

    current = lib.parse_tags((item.fields or {}).get(lib.FIELD_TAGS, ""))

    if args.action == "list":
        if current:
            print(f"\n  Tags on {args.work_item_id}: " + ", ".join(current))
        else:
            print(f"\n  No tags on {args.work_item_id}.")
        return

    if args.action == "add":
        existing_lower = {t.lower() for t in current}
        new_tags = current + [t for t in args.tag if t.lower() not in existing_lower]
    else:  # remove
        remove_lower = {t.lower() for t in args.tag}
        new_tags = [t for t in current if t.lower() not in remove_lower]

    ops = [lib.op("replace" if current else "add", f"/fields/{lib.FIELD_TAGS}", lib.format_tags(new_tags))]
    try:
        client.update_work_item(ops, args.work_item_id)
    except Exception as e:
        sys.exit(f"ERROR: Failed to update tags: {e}")

    print(lib.c(f"  ✓ [{args.work_item_id}] tags: {lib.format_tags(new_tags) or '(none)'}", lib.GREEN))


if __name__ == "__main__":
    main()
