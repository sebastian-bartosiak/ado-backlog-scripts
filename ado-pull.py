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

Usage:   uv run ado-pull.py <work_item_id> [--depth N]
         --depth N   how many levels of children to fetch (default: 1, use 0 for unlimited)

Output:  <WorkItemType>_<id>.yaml  (e.g. Feature_275453.yaml)

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT
"""

import sys, os, re, html
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
import html2text
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
YELLOW = "\033[33m"; CYAN = "\033[36m"; DIM = "\033[2m"
def c(text, *codes): return "".join(codes) + str(text) + R

# ── ADO client ────────────────────────────────────────────────────────────────
def get_client():
    creds = BasicAuthentication("", PAT)
    conn  = Connection(base_url=ORG_URL, creds=creds)
    return conn.clients.get_work_item_tracking_client()

# ── HTML → Markdown ───────────────────────────────────────────────────────────
_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.body_width = 0          # no line wrapping
_h2t.protect_links = True
_h2t.wrap_links = False

def html_to_md(raw: str) -> str:
    """Convert an ADO HTML field to clean Markdown. Handles plain text too."""
    if not raw:
        return ""
    stripped = raw.strip()
    if "<" not in stripped:
        # Plain text: unescape entities and normalise line endings
        text = html.unescape(stripped)
    else:
        text = _h2t.handle(stripped)
    # Normalise line endings, collapse excess blank lines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def literal(s: str) -> LiteralScalarString:
    """Wrap a string so ruamel.yaml emits it as a block literal scalar (|)."""
    return LiteralScalarString(s + "\n")

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

def item_to_dict(item, parent_id=None):
    """Convert an ADO work item to the YAML dict structure."""
    if not item:
        return None
    f = item.fields or {}

    d = {}
    d["id"]   = item.id
    d["type"] = f.get("System.WorkItemType", "Product Backlog Item")
    d["title"] = f.get("System.Title", "")

    if parent_id is not None:
        d["parent_id"] = parent_id

    area = f.get("System.AreaPath", "")
    if area:
        d["area"] = area

    iteration = f.get("System.IterationPath", "")
    if iteration:
        d["iteration"] = iteration

    release_notes = html_to_md(f.get("Custom.ReleaseNotes", ""))
    if release_notes:
        d["release_notes"] = literal(release_notes)

    item_fields = {}
    description = html_to_md(f.get("System.Description", ""))
    if description:
        item_fields["description"] = literal(description)

    ac = html_to_md(f.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""))
    if ac:
        item_fields["acceptance_criteria"] = literal(ac)

    if item_fields:
        d["fields"] = item_fields

    return d

# ── Recursive fetch ───────────────────────────────────────────────────────────
def fetch_descendants(client, parent_id, items_out, depth, max_depth):
    """Recursively fetch children up to max_depth levels (0 = unlimited)."""
    ado_item = fetch_item(client, parent_id)
    if not ado_item:
        return

    child_ids = children_of(ado_item)
    for cid in child_ids:
        child = fetch_item(client, cid)
        if not child:
            continue
        items_out.append(item_to_dict(child, parent_id=parent_id))
        if max_depth == 0 or depth < max_depth:
            fetch_descendants(client, cid, items_out, depth + 1, max_depth)

# ── YAML setup ────────────────────────────────────────────────────────────────
_yaml = YAML()
_yaml.default_flow_style = False
_yaml.allow_unicode = True
_yaml.width = 120

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("Usage: python3 ado-pull.py <work_item_id> [--depth N]")

    item_id   = None
    max_depth = 1  # default: direct children only

    i = 0
    while i < len(args):
        if args[i] == "--depth" and i + 1 < len(args):
            max_depth = int(args[i + 1])
            i += 2
        else:
            item_id = int(args[i])
            i += 1

    if item_id is None:
        sys.exit("Usage: python3 ado-pull.py <work_item_id> [--depth N]")

    depth_label = "unlimited" if max_depth == 0 else str(max_depth)

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c("  ADO PULL", BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  Item   : {item_id}")
    print(f"  Depth  : {depth_label}")
    print(f"  Org    : {ORG_URL}")
    print(f"  Project: {PROJECT}")

    print(f"\n  Connecting...", end="", flush=True)
    try:
        client = get_client()
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    print(f"  Fetching item {item_id}...", end="", flush=True)
    root = fetch_item(client, item_id)
    if not root:
        sys.exit(f"\nERROR: Cannot fetch item {item_id}")
    root_fields = root.fields or {}
    item_type   = root_fields.get("System.WorkItemType", "WorkItem")
    print(f" ok  ({item_type}: {root_fields.get('System.Title', '')})")

    print(f"  Fetching descendants (depth={depth_label})...", end="", flush=True)
    items = []
    fetch_descendants(client, item_id, items, depth=1, max_depth=max_depth)
    print(f" done  ({len(items)} item(s))")

    # ── Build output ──────────────────────────────────────────────────────────
    parent_dict = item_to_dict(root)  # no parent_id for root

    output = {
        "meta": {
            "generated": str(date.today()),
            "source":    f"{item_type}_{item_id}",
        },
        "parent": parent_dict,
        "items":  items,
    }

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    filename = out_dir / f"{item_type}_{item_id}.yaml"
    with open(filename, "w", encoding="utf-8") as fh:
        _yaml.dump(output, fh)

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c(f"  Saved → {filename}", GREEN + BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  Parent : {item_type} {item_id}  —  {parent_dict.get('title', '')}")
    print(f"  Items  : {len(items)}")
    print()


if __name__ == "__main__":
    main()
