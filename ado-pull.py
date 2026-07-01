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
ADO Pull — Fetch a work item and all its descendants from ADO, save to YAML.

Output:  data/<WorkItemType>_<id>.yaml  (e.g. data/Feature_275453.yaml)

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def fetch_descendants(client, parent_id, items_out, depth, max_depth):
    """Recursively fetch children up to max_depth levels (0 = unlimited)."""
    ado_item = lib.fetch_item(client, parent_id)
    if not ado_item:
        return

    for cid in lib.children_of(ado_item):
        child = lib.fetch_item(client, cid)
        if not child:
            continue
        items_out.append(lib.item_to_dict(child, parent_id=parent_id))
        if max_depth == 0 or depth < max_depth:
            fetch_descendants(client, cid, items_out, depth + 1, max_depth)


def parse_args():
    p = argparse.ArgumentParser(description="Fetch a work item and its descendants from ADO, save to YAML.")
    p.add_argument("work_item_id", type=int, help="Root work item id to fetch")
    p.add_argument("--depth", type=int, default=1, metavar="N",
                    help="Levels of children to fetch (default: 1, use 0 for unlimited)")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)
    depth_label = "unlimited" if args.depth == 0 else str(args.depth)

    lib.banner("ADO PULL")
    print(f"  Item   : {args.work_item_id}")
    print(f"  Depth  : {depth_label}")
    print(f"  Org    : {cfg.org_url}")
    print(f"  Project: {cfg.project}")

    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    print(f"  Fetching item {args.work_item_id}...", end="", flush=True)
    root = lib.fetch_item(client, args.work_item_id)
    if not root:
        sys.exit(f"\nERROR: Cannot fetch item {args.work_item_id}")
    root_fields = root.fields or {}
    item_type = root_fields.get("System.WorkItemType", "WorkItem")
    print(f" ok  ({item_type}: {root_fields.get('System.Title', '')})")

    print(f"  Fetching descendants (depth={depth_label})...", end="", flush=True)
    items = []
    fetch_descendants(client, args.work_item_id, items, depth=1, max_depth=args.depth)
    print(f" done  ({len(items)} item(s))")

    # ── Build output ──────────────────────────────────────────────────────────
    parent_dict = lib.item_to_dict(root)  # no parent_id for root

    output = {
        "meta": {
            "generated": str(date.today()),
            "source":    f"{item_type}_{args.work_item_id}",
        },
        "parent": parent_dict,
        "items":  items,
    }

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    filename = out_dir / f"{item_type}_{args.work_item_id}.yaml"
    with open(filename, "w", encoding="utf-8") as fh:
        lib.get_yaml().dump(output, fh)

    lib.banner(f"Saved → {filename}", lib.GREEN)
    print(f"  Parent : {item_type} {args.work_item_id}  —  {parent_dict.get('title', '')}")
    print(f"  Items  : {len(items)}")
    print()


if __name__ == "__main__":
    main()
