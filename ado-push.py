#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml",
#   "azure-devops",
#   "python-dotenv",
# ]
# ///
"""
ADO Sync Runner — Fetch ADO state, compare to plan, apply changes interactively.

Usage:   uv run ado-push.py <plan.yaml>
.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import sys, difflib, os
from pathlib import Path
from dotenv import load_dotenv
import yaml
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

# ── Load .env ─────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".vscode" / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

# ── Config ────────────────────────────────────────────────────────────────────
PAT     = os.environ.get("ADO_PAT", "")
ORG_URL = os.environ.get("ADO_ORG_URL", "https://dev.azure.com/xxx")
PROJECT = os.environ.get("ADO_PROJECT", "yyy")

if not PAT:
    sys.exit("ADO_PAT not set in .env file")

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"; DIM = "\033[2m"
def c(text, *codes): return "".join(codes) + str(text) + R

# ── ADO client ────────────────────────────────────────────────────────────────
def get_client():
    creds = BasicAuthentication("", PAT)
    conn  = Connection(base_url=ORG_URL, creds=creds)
    return conn.clients.get_work_item_tracking_client()

# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_item(client, item_id):
    try:
        return client.get_work_item(item_id, expand="Relations")
    except Exception as e:
        print(c(f"  WARNING: fetch {item_id} failed: {e}", YELLOW))
        return None

def children_of(item):
    if not item or not item.relations:
        return []
    return [
        int(rel.url.rstrip("/").split("/")[-1])
        for rel in item.relations
        if rel.rel == "System.LinkTypes.Hierarchy-Forward"
    ]

def parent_of(item):
    if not item or not item.relations:
        return None
    for rel in item.relations:
        if rel.rel == "System.LinkTypes.Hierarchy-Reverse":
            return int(rel.url.rstrip("/").split("/")[-1])
    return None

def find_relation_idx(item, rel_type, target_id):
    if not item or not item.relations:
        return None
    for i, rel in enumerate(item.relations):
        if rel.rel == rel_type:
            if int(rel.url.rstrip("/").split("/")[-1]) == target_id:
                return i
    return None

def norm(text):
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in str(text).strip().splitlines())

def prompt(choices):
    valid = {ch[0].lower() for ch in choices}
    opts  = " / ".join(f"[{ch[0]}]{ch[1:]}" for ch in choices)
    while True:
        resp = input(f"  → {opts}: ").strip().lower()
        if resp and resp[0] in valid:
            return resp[0]

def print_field(label, text, max_lines=5):
    if not text:
        return
    lines = str(text).strip().splitlines()
    print(c(f"      {label}:", CYAN))
    for line in lines[:max_lines]:
        print(f"        {line}")
    if len(lines) > max_lines:
        print(c(f"        ... ({len(lines) - max_lines} more lines)", DIM))

def show_diff(label, old_text, new_text, max_lines=40):
    old_lines = str(old_text or "").strip().splitlines(keepends=True)
    new_lines = str(new_text or "").strip().splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"ADO/{label}", tofile=f"Plan/{label}", lineterm=""
    ))
    if not diff:
        return
    print(c(f"      diff {label}:", CYAN))
    for line in diff[:max_lines]:
        if line.startswith("+++") or line.startswith("---"):
            print(c(f"        {line}", DIM))
        elif line.startswith("+"):
            print(c(f"        {line}", GREEN))
        elif line.startswith("-"):
            print(c(f"        {line}", RED))
        elif line.startswith("@@"):
            print(c(f"        {line}", CYAN))
        else:
            print(c(f"        {line}", DIM))
    if len(diff) > max_lines:
        print(c(f"        ... ({len(diff) - max_lines} more diff lines)", DIM))

def op(operation, path, value=None):
    d = {"op": operation, "path": path}
    if value is not None:
        d["value"] = value
    return d

def relation_value(target_id):
    return {
        "rel": "System.LinkTypes.Hierarchy-Reverse",
        "url": f"{ORG_URL}/_apis/wit/workItems/{target_id}"
    }

# ── ADO write operations ──────────────────────────────────────────────────────
def exec_update(client, item):
    fields = item.get("fields", {})
    ops = []
    if item.get("title"):
        ops.append(op("replace", "/fields/System.Title", item["title"]))
    if fields.get("description"):
        ops.append(op("replace", "/fields/System.Description", str(fields["description"])))
    if fields.get("acceptance_criteria"):
        ac = str(fields["acceptance_criteria"]).replace("&nbsp;", "")
        ops.append(op("replace", "/fields/Microsoft.VSTS.Common.AcceptanceCriteria", ac))
        ops.append(op("replace", "/multilineFieldsFormat/Microsoft.VSTS.Common.AcceptanceCriteria", "markdown"))
    if not ops:
        return None, "nothing to update"
    try:
        return client.update_work_item(ops, item["id"]), None
    except Exception as e:
        return None, str(e)

def exec_create(client, item):
    fields = item.get("fields", {})
    ops = [op("add", "/fields/System.Title", item["title"])]
    if item.get("area"):
        ops.append(op("add", "/fields/System.AreaPath", item["area"]))
    if item.get("iteration"):
        ops.append(op("add", "/fields/System.IterationPath", item["iteration"]))
    if fields.get("description"):
        ops.append(op("add", "/fields/System.Description", str(fields["description"])))
    if fields.get("acceptance_criteria"):
        ac = str(fields["acceptance_criteria"]).replace("&nbsp;", "")
        ops.append(op("add", "/fields/Microsoft.VSTS.Common.AcceptanceCriteria", ac))
        ops.append(op("replace", "/multilineFieldsFormat/Microsoft.VSTS.Common.AcceptanceCriteria", "markdown"))
    if item.get("parent_id"):
        ops.append(op("add", "/relations/-", relation_value(item["parent_id"])))
    try:
        return client.create_work_item(ops, PROJECT, item.get("type", "Product Backlog Item")), None
    except Exception as e:
        return None, str(e)

def exec_reparent(client, item_id, old_parent, new_parent):
    ado_item = fetch_item(client, item_id)
    idx = find_relation_idx(ado_item, "System.LinkTypes.Hierarchy-Reverse", old_parent)
    if idx is None:
        return None, f"parent relation to {old_parent} not found"
    ops = [
        op("remove", f"/relations/{idx}"),
        op("add", "/relations/-", relation_value(new_parent)),
    ]
    try:
        return client.update_work_item(ops, item_id), None
    except Exception as e:
        return None, str(e)

def exec_unlink(client, item_id, parent_id):
    ado_item = fetch_item(client, item_id)
    idx = find_relation_idx(ado_item, "System.LinkTypes.Hierarchy-Reverse", parent_id)
    if idx is None:
        return None, f"parent relation to {parent_id} not found"
    try:
        return client.update_work_item([op("remove", f"/relations/{idx}")], item_id), None
    except Exception as e:
        return None, str(e)

def exec_delete(client, item_id):
    try:
        client.delete_work_item(item_id, PROJECT)
        return True, None
    except Exception as e:
        return None, str(e)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 sync-runner.py <plan.yaml>")

    with open(sys.argv[1]) as f:
        plan = yaml.safe_load(f)

    meta   = plan.get("meta", {})
    parent = plan["parent"]
    items  = plan.get("items", [])

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c("  ADO SYNC RUNNER", BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  Parent : {parent['type']} {parent['id']}  —  {parent.get('title','')}")
    print(f"  Source : {meta.get('source', '?')}  (generated {meta.get('generated','?')})")
    print(f"  Org    : {ORG_URL}")
    print(f"  Project: {PROJECT}")

    # ── Connect ──────────────────────────────────────────────────────────────
    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = get_client()
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    # ── Fetch ADO state ──────────────────────────────────────────────────────
    print(f"  Fetching ADO state...", end="", flush=True)

    parent_ado = fetch_item(client, parent["id"])
    if not parent_ado:
        sys.exit(f"\nERROR: Cannot fetch parent {parent['id']}")
    ado_children_ids = set(children_of(parent_ado))

    doc_by_id  = {item["id"]: item for item in items if item.get("id")}
    doc_new    = [item for item in items if not item.get("id")]
    doc_ids    = set(doc_by_id.keys())
    orphan_ids = ado_children_ids - doc_ids

    # Fetch orphan candidates first so we can match them against doc_new by title
    orphan_ado = {}
    for iid in orphan_ids:
        d = fetch_item(client, iid)
        if d:
            orphan_ado[iid] = d

    # Match orphans to unID'd doc items by (title, parent_id) — handles re-runs
    # after creates where the YAML still has id: ~
    doc_new_lookup = {(it.get("title", ""), it.get("parent_id")): it for it in doc_new}
    title_matched  = {}  # orphan_id -> doc_item

    for oid, ado_item in orphan_ado.items():
        ado_f = ado_item.fields or {}
        key   = (ado_f.get("System.Title", ""), parent_of(ado_item))
        if key in doc_new_lookup:
            doc_item       = doc_new_lookup[key]
            doc_item["id"] = oid          # inject the real ADO id
            title_matched[oid] = doc_item

    # Promote matched items: known IDs now, no longer new or orphan
    matched_obj_ids = {id(it) for it in title_matched.values()}
    for oid, doc_item in title_matched.items():
        doc_by_id[oid] = doc_item
        doc_ids.add(oid)
    doc_new    = [it for it in doc_new    if id(it) not in matched_obj_ids]
    orphan_ids = orphan_ids - set(title_matched)

    # Fetch remaining doc items (original explicit IDs)
    ado_state = {parent["id"]: parent_ado}
    ado_state.update(orphan_ado)
    for iid in doc_ids - set(orphan_ado):
        d = fetch_item(client, iid)
        if d:
            ado_state[iid] = d

    print(f" done  ({len(ado_state)} items fetched)")

    # ── Detect changes ───────────────────────────────────────────────────────
    updates   = []
    creates   = doc_new[:]
    reparents = []
    orphans   = []

    def check_update(doc_item, ado_item):
        fields     = doc_item.get("fields", {})
        ado_fields = (ado_item.fields if ado_item else None) or {}
        changed    = []
        if fields.get("description") and norm(fields["description"]) != norm(ado_fields.get("System.Description", "")):
            changed.append("description")
        if fields.get("acceptance_criteria") and norm(fields["acceptance_criteria"]) != norm(ado_fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", "")):
            changed.append("acceptance_criteria")
        if doc_item.get("title") and doc_item["title"] != ado_fields.get("System.Title", ""):
            changed.append("title")
        return changed

    changed = check_update(parent, parent_ado)
    if changed:
        updates.append({"item": parent, "changed": changed, "ado": parent_ado})

    for iid, doc_item in doc_by_id.items():
        ado_item = ado_state.get(iid)
        changed  = check_update(doc_item, ado_item)
        if changed:
            updates.append({"item": doc_item, "changed": changed, "ado": ado_item})

        doc_parent_id = doc_item.get("parent_id")
        ado_parent_id = parent_of(ado_item)
        if doc_parent_id and ado_parent_id and doc_parent_id != ado_parent_id:
            reparents.append({"item": doc_item, "old": ado_parent_id, "new": doc_parent_id})

    for oid in orphan_ids:
        ado_item = ado_state.get(oid)
        title    = (ado_item.fields or {}).get("System.Title", f"Item {oid}") if ado_item else f"Item {oid}"
        orphans.append({"id": oid, "title": title})

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(c("  DETECTED CHANGES", BOLD))
    if title_matched:
        ids_str = ", ".join(str(i) for i in sorted(title_matched))
        print(c(f"  ~  Title-matched: {len(title_matched)} previously created item(s) recognised by title ({ids_str})", CYAN))
    print(f"  ✏  Updates:   {len(updates)}")
    print(f"  ✚  Creates:   {len(creates)}")
    print(f"  ↩  Reparents: {len(reparents)}")
    print(f"  ⚠  Orphans:   {len(orphans)}")

    if not any([updates, creates, reparents, orphans]):
        print(c("\n  Nothing to do — ADO already matches the plan.", GREEN))
        return

    approved_updates   = []
    approved_creates   = []
    approved_reparents = []
    orphan_actions     = []

    # ── Review updates ───────────────────────────────────────────────────────
    if updates:
        print()
        print(c("──────────────────────────────────────────────────────────", DIM))
        print(c("  UPDATES", BOLD))
        print(c("──────────────────────────────────────────────────────────", DIM))
        for i, u in enumerate(updates, 1):
            item       = u["item"]
            changed    = u["changed"]
            fields     = item.get("fields", {})
            ado_item   = u.get("ado")
            ado_fields = (ado_item.fields if ado_item else None) or {}
            field_map  = {
                "title":               ("title",               "System.Title"),
                "description":         ("description",         "System.Description"),
                "acceptance_criteria": ("acceptance_criteria", "Microsoft.VSTS.Common.AcceptanceCriteria"),
            }
            matched_tag = c("  [title-matched]", CYAN) if item["id"] in title_matched else ""
            print()
            print(c(f"  [{i}/{len(updates)}] {item.get('type','Item')} {item['id']}", BOLD) + matched_tag)
            print(f"        {item.get('title', '')}")

            for fname in changed:
                if fname == "title":
                    old_val = ado_fields.get("System.Title", "")
                    new_val = item.get("title", "")
                else:
                    _, ado_key = field_map.get(fname, (fname, fname))
                    old_val = ado_fields.get(ado_key, "")
                    new_val = fields.get(fname, "")
                show_diff(fname, old_val, new_val)

            choice = prompt(["Approve", "Skip", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            if choice == "a":
                approved_updates.append(u)
                print(c("  ✓ Approved", GREEN))
            else:
                print(c("  - Skipped", YELLOW))

    # ── Review creates ───────────────────────────────────────────────────────
    if creates:
        print()
        print(c("──────────────────────────────────────────────────────────", DIM))
        print(c("  CREATES", BOLD))
        print(c("──────────────────────────────────────────────────────────", DIM))
        for i, item in enumerate(creates, 1):
            fields = item.get("fields", {})
            print()
            print(c(f"  [{i}/{len(creates)}] NEW {item.get('type','Product Backlog Item')}", BOLD))
            print(f"        Title:  {item['title']}")
            print(f"        Parent: {item.get('parent_id', '?')}")

            choice = prompt(["Approve", "Skip", "View content", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            if choice == "v":
                for fname, fval in fields.items():
                    if fval:
                        print_field(fname, fval, max_lines=20)
                choice = prompt(["Approve", "Skip", "Quit"])
                if choice == "q":
                    sys.exit("Quitting.")

            if choice == "a":
                approved_creates.append(item)
                print(c("  ✓ Approved", GREEN))
            else:
                print(c("  - Skipped", YELLOW))

    # ── Review reparents ─────────────────────────────────────────────────────
    if reparents:
        print()
        print(c("──────────────────────────────────────────────────────────", DIM))
        print(c("  REPARENTS", BOLD))
        print(c("──────────────────────────────────────────────────────────", DIM))
        for i, rp in enumerate(reparents, 1):
            item = rp["item"]
            print()
            print(c(f"  [{i}/{len(reparents)}] REPARENT {item['id']}", BOLD))
            print(f"        {item.get('title', '')}")
            print(f"        {rp['old']}  →  {rp['new']}")

            choice = prompt(["Approve", "Skip", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            if choice == "a":
                approved_reparents.append(rp)
                print(c("  ✓ Approved", GREEN))
            else:
                print(c("  - Skipped", YELLOW))

    # ── Review orphans ───────────────────────────────────────────────────────
    if orphans:
        print()
        print(c("──────────────────────────────────────────────────────────", DIM))
        print(c("  ORPHANS  (in ADO but not in document)", BOLD))
        print(c("──────────────────────────────────────────────────────────", DIM))
        for i, orphan in enumerate(orphans, 1):
            print()
            print(c(f"  [{i}/{len(orphans)}] ORPHAN {orphan['id']}", BOLD))
            print(f"        {orphan['title']}")

            choice = prompt(["Keep", "Unlink from parent", "Delete to recycle bin", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            orphan_actions.append({"orphan": orphan, "action": choice})
            label = {"k": "Keep", "u": "Unlink", "d": "Delete (recycle bin)"}[choice]
            print(c(f"  → {label}", YELLOW))

    # ── Final confirm ────────────────────────────────────────────────────────
    active_orphan = [a for a in orphan_actions if a["action"] != "k"]
    total = len(approved_updates) + len(approved_creates) + len(approved_reparents) + len(active_orphan)

    if total == 0:
        print(c("\n  Nothing approved — exiting.", YELLOW))
        return

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  Will execute: {len(approved_updates)} updates, {len(approved_creates)} creates, "
          f"{len(approved_reparents)} reparents, {len(active_orphan)} orphan actions")
    resp = input("\n  Proceed? [y/N]: ").strip().lower()
    if resp != "y":
        sys.exit("  Aborted.")

    print()

    # ── Execute updates ──────────────────────────────────────────────────────
    if approved_updates:
        print(c("  ─── Updates ───", BOLD))
        for u in approved_updates:
            item = u["item"]
            _, err = exec_update(client, item)
            if err is None:
                print(c(f"  ✓ [{item['id']}] {item.get('title','')}", GREEN))
            else:
                print(c(f"  ✗ [{item['id']}] FAILED: {err}", RED))

    # ── Execute creates ──────────────────────────────────────────────────────
    if approved_creates:
        print(c("  ─── Creates ───", BOLD))
        for item in approved_creates:
            result, err = exec_create(client, item)
            if err is None:
                print(c(f"  ✓ Created '{item['title']}' → ID: {result.id}", GREEN))
            else:
                print(c(f"  ✗ FAILED '{item['title']}': {err}", RED))

    # ── Execute reparents ────────────────────────────────────────────────────
    if approved_reparents:
        print(c("  ─── Reparents ───", BOLD))
        for rp in approved_reparents:
            item = rp["item"]
            _, err = exec_reparent(client, item["id"], rp["old"], rp["new"])
            if err is None:
                print(c(f"  ✓ [{item['id']}] → {rp['new']}", GREEN))
            else:
                print(c(f"  ✗ [{item['id']}] FAILED: {err}", RED))

    # ── Execute orphan actions ───────────────────────────────────────────────
    if active_orphan:
        print(c("  ─── Orphans ───", BOLD))
        for entry in active_orphan:
            orphan = entry["orphan"]
            action = entry["action"]
            if action == "u":
                _, err = exec_unlink(client, orphan["id"], parent["id"])
                if err is None:
                    print(c(f"  ✓ [{orphan['id']}] Unlinked from parent", GREEN))
                else:
                    print(c(f"  ✗ [{orphan['id']}] Unlink FAILED: {err}", RED))
            elif action == "d":
                _, err = exec_delete(client, orphan["id"])
                if err is None:
                    print(c(f"  ✓ [{orphan['id']}] Deleted (recoverable from recycle bin)", GREEN))
                else:
                    print(c(f"  ✗ [{orphan['id']}] Delete FAILED: {err}", RED))

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c("  Done!", GREEN + BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print()


if __name__ == "__main__":
    main()
