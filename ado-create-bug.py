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
ADO Create Bug — Create a Bug in the current sprint.

Iteration defaults to the current sprint unless --iteration is given. If --parent-id
is given and --area is not, Area Path is inherited from the parent. Assigned to
ADO_ME unless --no-assign.

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT, ADO_ME, ADO_TYPE_BUG
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Create a Bug in the current sprint.")
    p.add_argument("title", help="Bug title")
    p.add_argument("--description", metavar="TEXT", help="Description (markdown)")
    p.add_argument("--repro-steps", metavar="TEXT", help="Repro steps (markdown)")
    p.add_argument("--area", metavar="PATH", help="Area Path (default: inherited from --parent-id, if given)")
    p.add_argument("--iteration", metavar="PATH", help="Iteration Path (default: current sprint)")
    p.add_argument("--parent-id", type=int, metavar="ID", help="Parent work item id to link under")
    p.add_argument("--no-assign", action="store_true", help="Don't assign the bug to ADO_ME")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)
    if not args.no_assign:
        lib.require_me(cfg)

    print(f"  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    area = args.area
    if not area and args.parent_id:
        parent = lib.fetch_item(client, args.parent_id)
        if parent:
            area = (parent.fields or {}).get(lib.FIELD_AREA_PATH, "")

    iteration = args.iteration
    if not iteration:
        print("  Resolving current sprint...", end="", flush=True)
        iteration, _ = lib.get_current_iteration(client, cfg.project)
        print(f" ok  ({iteration})" if iteration else " not found")

    ops = [lib.op("add", f"/fields/{lib.FIELD_TITLE}", args.title)]
    if area:
        ops.append(lib.op("add", f"/fields/{lib.FIELD_AREA_PATH}", area))
    if iteration:
        ops.append(lib.op("add", f"/fields/{lib.FIELD_ITERATION_PATH}", iteration))
    if not args.no_assign:
        ops.append(lib.op("add", f"/fields/{lib.FIELD_ASSIGNED_TO}", cfg.me))
    if args.description:
        ops.extend(lib.markdown_field_ops(lib.FIELD_DESCRIPTION, args.description))
    if args.repro_steps:
        ops.extend(lib.markdown_field_ops(lib.FIELD_REPRO_STEPS, args.repro_steps))
    if args.parent_id:
        ops.append(lib.op("add", "/relations/-", lib.relation_value(cfg.org_url, args.parent_id)))

    try:
        result = client.create_work_item(ops, cfg.project, cfg.type_bug)
    except Exception as e:
        sys.exit(f"ERROR: Failed to create bug: {e}")

    print(lib.c(f"  ✓ Created {cfg.type_bug} '{args.title}' → ID: {result.id}  (iteration: {iteration or 'unset'})", lib.GREEN))


if __name__ == "__main__":
    main()
