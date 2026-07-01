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
ADO Push — Fetch ADO state, compare to a local YAML plan, apply changes interactively.

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ado_lib as lib


def norm(text):
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in str(text).strip().splitlines())


def prompt(choices):
    valid = {ch[0].lower() for ch in choices}
    opts = " / ".join(f"[{ch[0]}]{ch[1:]}" for ch in choices)
    while True:
        resp = input(f"  → {opts}: ").strip().lower()
        if resp and resp[0] in valid:
            return resp[0]


def print_field(label, text, max_lines=5):
    if not text:
        return
    lines = str(text).strip().splitlines()
    print(lib.c(f"      {label}:", lib.CYAN))
    for line in lines[:max_lines]:
        print(f"        {line}")
    if len(lines) > max_lines:
        print(lib.c(f"        ... ({len(lines) - max_lines} more lines)", lib.DIM))


def show_diff(label, old_text, new_text, max_lines=40):
    old_lines = str(old_text or "").strip().splitlines(keepends=True)
    new_lines = str(new_text or "").strip().splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"ADO/{label}", tofile=f"Plan/{label}", lineterm=""
    ))
    if not diff:
        return
    print(lib.c(f"      diff {label}:", lib.CYAN))
    for line in diff[:max_lines]:
        if line.startswith("+++") or line.startswith("---"):
            print(lib.c(f"        {line}", lib.DIM))
        elif line.startswith("+"):
            print(lib.c(f"        {line}", lib.GREEN))
        elif line.startswith("-"):
            print(lib.c(f"        {line}", lib.RED))
        elif line.startswith("@@"):
            print(lib.c(f"        {line}", lib.CYAN))
        else:
            print(lib.c(f"        {line}", lib.DIM))
    if len(diff) > max_lines:
        print(lib.c(f"        ... ({len(diff) - max_lines} more diff lines)", lib.DIM))

# ── ADO write operations ──────────────────────────────────────────────────────
def exec_update(client, item):
    fields = item.get("fields", {})
    ops = []
    if item.get("title"):
        ops.append(lib.op("replace", f"/fields/{lib.FIELD_TITLE}", item["title"]))
    if fields.get("description"):
        ops.extend(lib.markdown_field_ops(lib.FIELD_DESCRIPTION, fields["description"], value_op="replace"))
    if fields.get("acceptance_criteria"):
        ac = str(fields["acceptance_criteria"]).replace("&nbsp;", "")
        ops.extend(lib.markdown_field_ops(lib.FIELD_ACCEPTANCE_CRITERIA, ac, value_op="replace"))
    if fields.get("repro_steps"):
        rs = str(fields["repro_steps"]).replace("&nbsp;", "")
        ops.extend(lib.markdown_field_ops(lib.FIELD_REPRO_STEPS, rs, value_op="replace"))
    if not ops:
        return None, "nothing to update"
    try:
        return client.update_work_item(ops, item["id"]), None
    except Exception as e:
        return None, str(e)


def exec_create(client, cfg, item):
    fields = item.get("fields", {})
    ops = [lib.op("add", f"/fields/{lib.FIELD_TITLE}", item["title"])]
    if item.get("area"):
        ops.append(lib.op("add", f"/fields/{lib.FIELD_AREA_PATH}", item["area"]))
    if item.get("iteration"):
        ops.append(lib.op("add", f"/fields/{lib.FIELD_ITERATION_PATH}", item["iteration"]))
    if item.get("tags"):
        ops.append(lib.op("add", f"/fields/{lib.FIELD_TAGS}", lib.format_tags(item["tags"])))
    if fields.get("description"):
        ops.extend(lib.markdown_field_ops(lib.FIELD_DESCRIPTION, fields["description"]))
    if fields.get("acceptance_criteria"):
        ac = str(fields["acceptance_criteria"]).replace("&nbsp;", "")
        ops.extend(lib.markdown_field_ops(lib.FIELD_ACCEPTANCE_CRITERIA, ac))
    if fields.get("repro_steps"):
        rs = str(fields["repro_steps"]).replace("&nbsp;", "")
        ops.extend(lib.markdown_field_ops(lib.FIELD_REPRO_STEPS, rs))
    if item.get("parent_id"):
        ops.append(lib.op("add", "/relations/-", lib.relation_value(cfg.org_url, item["parent_id"])))
    try:
        return client.create_work_item(ops, cfg.project, item.get("type", cfg.type_story)), None
    except Exception as e:
        return None, str(e)


def exec_reparent(client, cfg, item_id, old_parent, new_parent):
    ado_item = lib.fetch_item(client, item_id)
    idx = lib.find_relation_idx(ado_item, lib.HIERARCHY_REVERSE, old_parent)
    if idx is None:
        return None, f"parent relation to {old_parent} not found"
    ops = [
        lib.op("remove", f"/relations/{idx}"),
        lib.op("add", "/relations/-", lib.relation_value(cfg.org_url, new_parent)),
    ]
    try:
        return client.update_work_item(ops, item_id), None
    except Exception as e:
        return None, str(e)


def exec_unlink(client, item_id, parent_id):
    ado_item = lib.fetch_item(client, item_id)
    idx = lib.find_relation_idx(ado_item, lib.HIERARCHY_REVERSE, parent_id)
    if idx is None:
        return None, f"parent relation to {parent_id} not found"
    try:
        return client.update_work_item([lib.op("remove", f"/relations/{idx}")], item_id), None
    except Exception as e:
        return None, str(e)


def exec_delete(client, cfg, item_id):
    try:
        client.delete_work_item(item_id, cfg.project)
        return True, None
    except Exception as e:
        return None, str(e)


def parse_args():
    p = argparse.ArgumentParser(description="Compare a local YAML plan against ADO, apply changes interactively.")
    p.add_argument("plan_file", type=Path, help="Path to the plan YAML (as produced by ado-pull.py)")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = lib.load_config(__file__)
    yaml_rt = lib.get_yaml()

    with open(args.plan_file) as f:
        plan = yaml_rt.load(f)

    meta = plan.get("meta", {})
    parent = plan["parent"]
    items = plan.get("items", [])

    lib.banner("ADO PUSH")
    print(f"  Parent : {parent['type']} {parent['id']}  —  {parent.get('title','')}")
    print(f"  Source : {meta.get('source', '?')}  (generated {meta.get('generated','?')})")
    print(f"  Org    : {cfg.org_url}")
    print(f"  Project: {cfg.project}")

    # ── Connect ──────────────────────────────────────────────────────────────
    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = lib.get_client(cfg)
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    # ── Fetch ADO state ──────────────────────────────────────────────────────
    print(f"  Fetching ADO state...", end="", flush=True)

    parent_ado = lib.fetch_item(client, parent["id"])
    if not parent_ado:
        sys.exit(f"\nERROR: Cannot fetch parent {parent['id']}")
    ado_children_ids = set(lib.children_of(parent_ado))

    doc_by_id = {item["id"]: item for item in items if item.get("id")}
    doc_new = [item for item in items if not item.get("id")]
    doc_ids = set(doc_by_id.keys())
    orphan_ids = ado_children_ids - doc_ids

    # Fetch orphan candidates first so we can match them against doc_new by title
    orphan_ado = {}
    for iid in orphan_ids:
        d = lib.fetch_item(client, iid)
        if d:
            orphan_ado[iid] = d

    # Match orphans to unID'd doc items by (title, parent_id) — handles re-runs
    # after creates where the YAML still has id: ~
    doc_new_lookup = {(it.get("title", ""), it.get("parent_id")): it for it in doc_new}
    title_matched = {}  # orphan_id -> doc_item

    for oid, ado_item in orphan_ado.items():
        ado_f = ado_item.fields or {}
        key = (ado_f.get("System.Title", ""), lib.parent_of(ado_item))
        if key in doc_new_lookup:
            doc_item = doc_new_lookup[key]
            doc_item["id"] = oid          # inject the real ADO id
            title_matched[oid] = doc_item

    # Promote matched items: known IDs now, no longer new or orphan
    matched_obj_ids = {id(it) for it in title_matched.values()}
    for oid, doc_item in title_matched.items():
        doc_by_id[oid] = doc_item
        doc_ids.add(oid)
    doc_new = [it for it in doc_new if id(it) not in matched_obj_ids]
    orphan_ids = orphan_ids - set(title_matched)

    # Fetch remaining doc items (original explicit IDs)
    ado_state = {parent["id"]: parent_ado}
    ado_state.update(orphan_ado)
    for iid in doc_ids - set(orphan_ado):
        d = lib.fetch_item(client, iid)
        if d:
            ado_state[iid] = d

    print(f" done  ({len(ado_state)} items fetched)")

    ids_changed = bool(title_matched)

    # ── Detect changes ───────────────────────────────────────────────────────
    updates = []
    creates = doc_new[:]
    reparents = []
    orphans = []

    def check_update(doc_item, ado_item):
        fields = doc_item.get("fields", {})
        ado_fields = (ado_item.fields if ado_item else None) or {}
        changed = []
        if fields.get("description") and norm(fields["description"]) != norm(ado_fields.get(lib.FIELD_DESCRIPTION, "")):
            changed.append("description")
        if fields.get("acceptance_criteria") and norm(fields["acceptance_criteria"]) != norm(ado_fields.get(lib.FIELD_ACCEPTANCE_CRITERIA, "")):
            changed.append("acceptance_criteria")
        if fields.get("repro_steps") and norm(fields["repro_steps"]) != norm(ado_fields.get(lib.FIELD_REPRO_STEPS, "")):
            changed.append("repro_steps")
        if doc_item.get("title") and doc_item["title"] != ado_fields.get(lib.FIELD_TITLE, ""):
            changed.append("title")
        return changed

    changed = check_update(parent, parent_ado)
    if changed:
        updates.append({"item": parent, "changed": changed, "ado": parent_ado})

    for iid, doc_item in doc_by_id.items():
        ado_item = ado_state.get(iid)
        changed = check_update(doc_item, ado_item)
        if changed:
            updates.append({"item": doc_item, "changed": changed, "ado": ado_item})

        doc_parent_id = doc_item.get("parent_id")
        ado_parent_id = lib.parent_of(ado_item)
        if doc_parent_id and ado_parent_id and doc_parent_id != ado_parent_id:
            reparents.append({"item": doc_item, "old": ado_parent_id, "new": doc_parent_id})

    for oid in orphan_ids:
        ado_item = ado_state.get(oid)
        title = (ado_item.fields or {}).get(lib.FIELD_TITLE, f"Item {oid}") if ado_item else f"Item {oid}"
        orphans.append({"id": oid, "title": title})

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(lib.c("  DETECTED CHANGES", lib.BOLD))
    if title_matched:
        ids_str = ", ".join(str(i) for i in sorted(title_matched))
        print(lib.c(f"  ~  Title-matched: {len(title_matched)} previously created item(s) recognised by title ({ids_str})", lib.CYAN))
    print(f"  ✏  Updates:   {len(updates)}")
    print(f"  ✚  Creates:   {len(creates)}")
    print(f"  ↩  Reparents: {len(reparents)}")
    print(f"  ⚠  Orphans:   {len(orphans)}")

    if not any([updates, creates, reparents, orphans]):
        print(lib.c("\n  Nothing to do — ADO already matches the plan.", lib.GREEN))
        if ids_changed:
            with open(args.plan_file, "w", encoding="utf-8") as fh:
                yaml_rt.dump(plan, fh)
            print(lib.c(f"  Updated {args.plan_file} with title-matched id(s).", lib.CYAN))
        return

    approved_updates = []
    approved_creates = []
    approved_reparents = []
    orphan_actions = []

    # ── Review updates ───────────────────────────────────────────────────────
    if updates:
        print()
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        print(lib.c("  UPDATES", lib.BOLD))
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        for i, u in enumerate(updates, 1):
            item = u["item"]
            changed = u["changed"]
            fields = item.get("fields", {})
            ado_item = u.get("ado")
            ado_fields = (ado_item.fields if ado_item else None) or {}
            field_map = {
                "title":               ("title",               lib.FIELD_TITLE),
                "description":         ("description",         lib.FIELD_DESCRIPTION),
                "acceptance_criteria": ("acceptance_criteria", lib.FIELD_ACCEPTANCE_CRITERIA),
                "repro_steps":         ("repro_steps",         lib.FIELD_REPRO_STEPS),
            }
            matched_tag = lib.c("  [title-matched]", lib.CYAN) if item["id"] in title_matched else ""
            print()
            print(lib.c(f"  [{i}/{len(updates)}] {item.get('type','Item')} {item['id']}", lib.BOLD) + matched_tag)
            print(f"        {item.get('title', '')}")

            for fname in changed:
                if fname == "title":
                    old_val = ado_fields.get(lib.FIELD_TITLE, "")
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
                print(lib.c("  ✓ Approved", lib.GREEN))
            else:
                print(lib.c("  - Skipped", lib.YELLOW))

    # ── Review creates ───────────────────────────────────────────────────────
    if creates:
        print()
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        print(lib.c("  CREATES", lib.BOLD))
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        for i, item in enumerate(creates, 1):
            fields = item.get("fields", {})
            print()
            print(lib.c(f"  [{i}/{len(creates)}] NEW {item.get('type', cfg.type_story)}", lib.BOLD))
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
                print(lib.c("  ✓ Approved", lib.GREEN))
            else:
                print(lib.c("  - Skipped", lib.YELLOW))

    # ── Review reparents ─────────────────────────────────────────────────────
    if reparents:
        print()
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        print(lib.c("  REPARENTS", lib.BOLD))
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        for i, rp in enumerate(reparents, 1):
            item = rp["item"]
            print()
            print(lib.c(f"  [{i}/{len(reparents)}] REPARENT {item['id']}", lib.BOLD))
            print(f"        {item.get('title', '')}")
            print(f"        {rp['old']}  →  {rp['new']}")

            choice = prompt(["Approve", "Skip", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            if choice == "a":
                approved_reparents.append(rp)
                print(lib.c("  ✓ Approved", lib.GREEN))
            else:
                print(lib.c("  - Skipped", lib.YELLOW))

    # ── Review orphans ───────────────────────────────────────────────────────
    if orphans:
        print()
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        print(lib.c("  ORPHANS  (in ADO but not in document)", lib.BOLD))
        print(lib.c("──────────────────────────────────────────────────────────", lib.DIM))
        for i, orphan in enumerate(orphans, 1):
            print()
            print(lib.c(f"  [{i}/{len(orphans)}] ORPHAN {orphan['id']}", lib.BOLD))
            print(f"        {orphan['title']}")

            choice = prompt(["Keep", "Unlink from parent", "Delete to recycle bin", "Quit"])
            if choice == "q":
                sys.exit("Quitting.")
            orphan_actions.append({"orphan": orphan, "action": choice})
            label = {"k": "Keep", "u": "Unlink", "d": "Delete (recycle bin)"}[choice]
            print(lib.c(f"  → {label}", lib.YELLOW))

    # ── Final confirm ────────────────────────────────────────────────────────
    active_orphan = [a for a in orphan_actions if a["action"] != "k"]
    total = len(approved_updates) + len(approved_creates) + len(approved_reparents) + len(active_orphan)

    if total == 0:
        print(lib.c("\n  Nothing approved — exiting.", lib.YELLOW))
        if ids_changed:
            with open(args.plan_file, "w", encoding="utf-8") as fh:
                yaml_rt.dump(plan, fh)
            print(lib.c(f"  Updated {args.plan_file} with title-matched id(s).", lib.CYAN))
        return

    print()
    print(lib.c("══════════════════════════════════════════════════════════", lib.BOLD))
    print(f"  Will execute: {len(approved_updates)} updates, {len(approved_creates)} creates, "
          f"{len(approved_reparents)} reparents, {len(active_orphan)} orphan actions")
    resp = input("\n  Proceed? [y/N]: ").strip().lower()
    if resp != "y":
        sys.exit("  Aborted.")

    print()

    # ── Execute updates ──────────────────────────────────────────────────────
    if approved_updates:
        print(lib.c("  ─── Updates ───", lib.BOLD))
        for u in approved_updates:
            item = u["item"]
            _, err = exec_update(client, item)
            if err is None:
                print(lib.c(f"  ✓ [{item['id']}] {item.get('title','')}", lib.GREEN))
            else:
                print(lib.c(f"  ✗ [{item['id']}] FAILED: {err}", lib.RED))

    # ── Execute creates ──────────────────────────────────────────────────────
    if approved_creates:
        print(lib.c("  ─── Creates ───", lib.BOLD))
        for item in approved_creates:
            result, err = exec_create(client, cfg, item)
            if err is None:
                item["id"] = result.id       # write the new ADO id back into the loaded plan
                ids_changed = True
                print(lib.c(f"  ✓ Created '{item['title']}' → ID: {result.id}", lib.GREEN))
            else:
                print(lib.c(f"  ✗ FAILED '{item['title']}': {err}", lib.RED))

    # ── Execute reparents ────────────────────────────────────────────────────
    if approved_reparents:
        print(lib.c("  ─── Reparents ───", lib.BOLD))
        for rp in approved_reparents:
            item = rp["item"]
            _, err = exec_reparent(client, cfg, item["id"], rp["old"], rp["new"])
            if err is None:
                print(lib.c(f"  ✓ [{item['id']}] → {rp['new']}", lib.GREEN))
            else:
                print(lib.c(f"  ✗ [{item['id']}] FAILED: {err}", lib.RED))

    # ── Execute orphan actions ───────────────────────────────────────────────
    if active_orphan:
        print(lib.c("  ─── Orphans ───", lib.BOLD))
        for entry in active_orphan:
            orphan = entry["orphan"]
            action = entry["action"]
            if action == "u":
                _, err = exec_unlink(client, orphan["id"], parent["id"])
                if err is None:
                    print(lib.c(f"  ✓ [{orphan['id']}] Unlinked from parent", lib.GREEN))
                else:
                    print(lib.c(f"  ✗ [{orphan['id']}] Unlink FAILED: {err}", lib.RED))
            elif action == "d":
                _, err = exec_delete(client, cfg, orphan["id"])
                if err is None:
                    print(lib.c(f"  ✓ [{orphan['id']}] Deleted (recoverable from recycle bin)", lib.GREEN))
                else:
                    print(lib.c(f"  ✗ [{orphan['id']}] Delete FAILED: {err}", lib.RED))

    # ── Persist newly-known ids back into the plan file ───────────────────────
    if ids_changed:
        with open(args.plan_file, "w", encoding="utf-8") as fh:
            yaml_rt.dump(plan, fh)
        print()
        print(lib.c(f"  Updated {args.plan_file} with new id(s) — safe to re-run without duplicating creates.", lib.CYAN))

    print()
    print(lib.c("══════════════════════════════════════════════════════════", lib.BOLD))
    print(lib.c("  Done!", lib.GREEN + lib.BOLD))
    print(lib.c("══════════════════════════════════════════════════════════", lib.BOLD))
    print()


if __name__ == "__main__":
    main()
