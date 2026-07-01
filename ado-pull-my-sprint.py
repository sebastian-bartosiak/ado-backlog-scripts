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
ADO Pull My Sprint — Fetch all Story/PBI and Bug items assigned to me in the current sprint.

Output:  data/my-sprint-<SprintNumber>.yaml

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT, ADO_ME, ADO_TYPE_STORY, ADO_TYPE_BUG
"""

import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def query_sprint_items(client, cfg, iteration_path):
    """Return list of work item IDs for Story/PBI and Bug items assigned to ADO_ME."""
    me_escaped = lib.wiql_escape(cfg.me)
    types = f"'{cfg.type_story}', '{cfg.type_bug}'"
    states = ", ".join(f"'{s}'" for s in lib.DONE_STATES)

    if iteration_path:
        iter_escaped = lib.wiql_escape(iteration_path)
        wiql = f"""
SELECT [System.Id]
FROM WorkItems
WHERE [System.AssignedTo] = '{me_escaped}'
  AND [System.WorkItemType] IN ({types})
  AND [System.IterationPath] = '{iter_escaped}'
  AND [System.State] NOT IN ({states})
ORDER BY [System.WorkItemType], [System.Id]
"""
    else:
        print(lib.c("  WARNING: No iteration filter applied — returning all active items.", lib.YELLOW))
        wiql = f"""
SELECT [System.Id]
FROM WorkItems
WHERE [System.AssignedTo] = '{me_escaped}'
  AND [System.WorkItemType] IN ({types})
  AND [System.State] NOT IN ({states})
ORDER BY [System.WorkItemType], [System.Id]
"""

    return lib.run_wiql(client, wiql)


def parse_args():
    p = argparse.ArgumentParser(description="Fetch Story/PBI and Bug items assigned to me in the current sprint.")
    return p.parse_args()


def main():
    parse_args()
    cfg = lib.load_config(__file__)
    lib.require_me(cfg)

    lib.banner("ADO PULL MY SPRINT")
    print(f"  User   : {cfg.me}")
    print(f"  Org    : {cfg.org_url}")
    print(f"  Project: {cfg.project}")

    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    print("  Resolving current sprint...", end="", flush=True)
    iter_path, _ = lib.get_current_iteration(client, cfg.project)
    if iter_path:
        print(f" ok  ({iter_path})")
    else:
        print(" not found (no iteration filter)")

    print("  Querying sprint items...", end="", flush=True)
    try:
        item_ids = query_sprint_items(client, cfg, iter_path)
    except Exception as e:
        sys.exit(f"\nERROR: WIQL query failed: {e}")
    print(f" done  ({len(item_ids)} item(s))")

    if not item_ids:
        print(lib.c("\n  No items found. Nothing to write.", lib.YELLOW))
        return

    print("  Fetching item details...")
    items = []
    for item_id in item_ids:
        ado_item = lib.fetch_item(client, item_id)
        if not ado_item:
            continue
        pid = lib.parent_of(ado_item)
        d = lib.item_to_dict(ado_item, parent_id=pid, include_status=True)
        if d:
            items.append(d)
            itype = d.get("type", "?")
            print(f"    {lib.c(str(item_id), lib.CYAN)}  {lib.c(itype, lib.DIM)}  "
                  f"[{d.get('status', '')}]  {d.get('title', '')}")

    # ── Build output ───────────────────────────────────────────────────────────
    sprint_num = lib.sprint_number(iter_path)
    output = {
        "meta": {
            "generated":   str(date.today()),
            "assigned_to": cfg.me,
            "sprint":      iter_path or "unknown",
        },
        "items": items,
    }

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    filename = out_dir / f"my-sprint-{sprint_num}.yaml"
    with open(filename, "w", encoding="utf-8") as fh:
        lib.get_yaml().dump(output, fh)

    lib.banner(f"Saved → {filename}", lib.GREEN)
    print(f"  Sprint : {iter_path or 'unknown'}")
    print(f"  Items  : {len(items)}")
    print()


if __name__ == "__main__":
    main()
