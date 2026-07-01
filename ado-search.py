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
ADO Search — Query Story/PBI/Task/Bug items by tag, type, state, assignee, iteration.

Prints a table and saves the full results to data/query-<timestamp>.yaml.

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT, ADO_ME, ADO_TYPE_STORY, ADO_TYPE_TASK, ADO_TYPE_BUG
"""

import argparse
import sys
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def parse_args():
    p = argparse.ArgumentParser(description="Query work items by tag/type/state/assignee/iteration.")
    p.add_argument("--tag", action="append", default=[], metavar="TAG",
                    help="Required tag (repeatable; all given tags must be present)")
    p.add_argument("--type", action="append", default=[], metavar="TYPE",
                    help="Work item type (repeatable; default: Story+Task+Bug from .env)")
    p.add_argument("--state", metavar="STATE", help="Restrict to this state")
    p.add_argument("--all-states", action="store_true",
                    help="Don't exclude Closed/Done/Removed by default")
    p.add_argument("--assigned-to", metavar="PERSON", help="'me' resolves to ADO_ME, or pass a display name")
    p.add_argument("--iteration", metavar="PATH", help="'current' resolves the active sprint, or pass a path")
    return p.parse_args()


def build_wiql(cfg, args, resolved_iteration):
    conditions = [f"[System.TeamProject] = '{lib.wiql_escape(cfg.project)}'"]

    types = args.type or [cfg.type_story, cfg.type_task, cfg.type_bug]
    type_list = ", ".join(f"'{lib.wiql_escape(t)}'" for t in types)
    conditions.append(f"[System.WorkItemType] IN ({type_list})")

    for tag in args.tag:
        conditions.append(f"[System.Tags] CONTAINS '{lib.wiql_escape(tag)}'")

    if args.state:
        conditions.append(f"[System.State] = '{lib.wiql_escape(args.state)}'")
    elif not args.all_states:
        states = ", ".join(f"'{s}'" for s in lib.DONE_STATES)
        conditions.append(f"[System.State] NOT IN ({states})")

    assigned_to = args.assigned_to
    if assigned_to:
        if assigned_to.lower() == "me":
            assigned_to = lib.require_me(cfg)
        conditions.append(f"[System.AssignedTo] = '{lib.wiql_escape(assigned_to)}'")

    if resolved_iteration:
        conditions.append(f"[System.IterationPath] = '{lib.wiql_escape(resolved_iteration)}'")

    where = "\n  AND ".join(conditions)
    return f"""
SELECT [System.Id]
FROM WorkItems
WHERE {where}
ORDER BY [System.WorkItemType], [System.Id]
"""


def truncate(text, width):
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)

    print(f"  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    resolved_iteration = args.iteration
    if resolved_iteration and resolved_iteration.lower() == "current":
        print("  Resolving current sprint...", end="", flush=True)
        resolved_iteration, _ = lib.get_current_iteration(client, cfg.project)
        print(f" ok  ({resolved_iteration})" if resolved_iteration else " not found")

    wiql = build_wiql(cfg, args, resolved_iteration)
    try:
        item_ids = lib.run_wiql(client, wiql)
    except Exception as e:
        sys.exit(f"ERROR: WIQL query failed: {e}")

    if not item_ids:
        print(lib.c("\n  No items found.", lib.YELLOW))
        return

    items = []
    for item_id in item_ids:
        ado_item = lib.fetch_item(client, item_id)
        if not ado_item:
            continue
        pid = lib.parent_of(ado_item)
        d = lib.item_to_dict(ado_item, parent_id=pid, include_status=True)
        if d:
            items.append(d)

    # ── Table ─────────────────────────────────────────────────────────────────
    print()
    header = f"  {'ID':>7}  {'TYPE':<22}  {'STATE':<12}  {'ASSIGNED TO':<20}  {'TAGS':<20}  TITLE"
    print(lib.c(header, lib.BOLD))
    print(lib.c("  " + "─" * (len(header) - 2), lib.DIM))
    for d in items:
        assigned = d.get("assigned_to", "")
        tags = ", ".join(d.get("tags", []))
        print(f"  {d['id']:>7}  {truncate(d.get('type',''), 22):<22}  {truncate(d.get('status',''), 12):<12}  "
              f"{truncate(assigned, 20):<20}  {truncate(tags, 20):<20}  {truncate(d.get('title',''), 60)}")

    print(f"\n  {len(items)} item(s)")

    # ── Save ──────────────────────────────────────────────────────────────────
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = out_dir / f"query-{stamp}.yaml"
    output = {
        "meta": {
            "generated": str(date.today()),
            "filters": {
                "tag": args.tag or None,
                "type": args.type or None,
                "state": args.state or ("all" if args.all_states else "not-done"),
                "assigned_to": args.assigned_to or None,
                "iteration": resolved_iteration or None,
            },
        },
        "items": items,
    }
    with open(filename, "w", encoding="utf-8") as fh:
        lib.get_yaml().dump(output, fh)

    print(lib.c(f"  Saved → {filename}", lib.GREEN))


if __name__ == "__main__":
    main()
