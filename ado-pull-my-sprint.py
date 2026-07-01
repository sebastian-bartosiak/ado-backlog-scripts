# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml",
#   "azure-devops",
#   "python-dotenv",
#   "html2text",
# ]
# ///
"""
ADO Pull My Sprint — Fetch all PBIs and Bugs assigned to me in the current sprint.

Usage:   uv run ado-pull-my-sprint.py
         python ado-pull-my-sprint.py

Output:  data/my-sprint-<SprintNumber>.yaml

.env keys: ADO_PAT, ADO_ORG_URL, ADO_PROJECT, ADO_ME
"""

import re
import sys
import os
import html
from pathlib import Path
from datetime import date
import html2text

# ── Load .env ─────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".vscode" / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).parent / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(_env_path)
except ImportError:
    sys.exit("python-dotenv required: pip install python-dotenv")

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

try:
    from azure.devops.connection import Connection
    from msrest.authentication import BasicAuthentication
except ImportError:
    sys.exit("azure-devops required: pip install azure-devops")

# ── Config ────────────────────────────────────────────────────────────────────
PAT     = os.environ.get("ADO_PAT", "")
ORG_URL = os.environ.get("ADO_ORG_URL", "https://dev.azure.com/xxx")
PROJECT = os.environ.get("ADO_PROJECT", "yyy")
ADO_ME  = os.environ.get("ADO_ME", "")

if not PAT:
    sys.exit("ADO_PAT not set in .env file")
if not ADO_ME:
    sys.exit("ADO_ME not set in .env file (e.g. 'Name Surname')")

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

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; CYAN = "\033[36m"; DIM = "\033[2m"
def c(text, *codes): return "".join(codes) + str(text) + R

# ── ADO clients ───────────────────────────────────────────────────────────────
def get_clients():
    creds = BasicAuthentication("", PAT)
    conn  = Connection(base_url=ORG_URL, creds=creds)
    wit   = conn.clients.get_work_item_tracking_client()
    return wit

# ── Current sprint ────────────────────────────────────────────────────────────
def _as_date(val):
    """Coerce datetime / ISO-string / date / None → date, or None."""
    if not val:
        return None
    if hasattr(val, "date"):          # datetime object
        return val.date()
    if isinstance(val, str):          # ISO string e.g. "2026-01-14T00:00:00Z"
        from datetime import datetime
        try:
            return datetime.fromisoformat(val.rstrip("Z").split("T")[0]).date()
        except ValueError:
            return None
    return val                        # already a date

def _walk_nodes(node, today, best=None):
    """Recursively walk the project classification tree, returning the deepest
    node whose [start_date, finish_date] bracket contains today."""
    attrs = node.attributes or {}
    start  = _as_date(attrs.get("startDate"))
    finish = _as_date(attrs.get("finishDate"))
    if start and finish and start <= today <= finish:
        depth = node.path.count("\\")
        if best is None or depth > best[0].count("\\"):
            best = (node.path, node.name)
    for child in (node.children or []):
        best = _walk_nodes(child, today, best)
    return best

def _normalize_iter_path(raw_path):
    """Convert classification node path to WIQL-compatible iteration path.

    """
    p = raw_path.lstrip("\\")                          # remove leading backslash
    # Remove the '\Iteration\' segment that classification nodes inject
    p = re.sub(r"^([^\\]+)\\Iteration\\", r"\1\\", p)
    return p

def get_current_iteration(wit_client):
    """Return (iteration_path, sprint_name) using the project-level classification
    node tree (depth=10), which includes all sprints regardless of team assignment."""
    today = date.today()
    try:
        root = wit_client.get_classification_node(PROJECT, "iterations", depth=10)
        result = _walk_nodes(root, today)
        if result:
            path, name = result
            return _normalize_iter_path(path), name
    except Exception as e:
        print(c(f"  WARNING: Could not determine current iteration: {e}", YELLOW))
    return None, None

def sprint_number(iteration_path):
    """Extract a file-safe label from the last segment of the iteration path.

    Falls back to the full last segment with spaces replaced by dashes.
    """
    if not iteration_path:
        return "unknown"
    last_segment = iteration_path.rstrip("\\").split("\\")[-1]  # e.g. "Sprint 104"
    m = re.search(r"(\d+)$", last_segment.strip())
    if m:
        return m.group(1)
    return re.sub(r"\s+", "-", last_segment)

# ── WIQL query ────────────────────────────────────────────────────────────────
def query_sprint_items(wit_client, iteration_path):
    """Return list of work item IDs for PBIs and Bugs assigned to ADO_ME."""
    me_escaped = ADO_ME.replace("'", "''")

    if iteration_path:
        iter_escaped = iteration_path.replace("'", "''")
        wiql = f"""
SELECT [System.Id]
FROM WorkItems
WHERE [System.AssignedTo] = '{me_escaped}'
  AND [System.WorkItemType] IN ('Product Backlog Item', 'Bug')
  AND [System.IterationPath] = '{iter_escaped}'
  AND [System.State] NOT IN ('Closed', 'Done', 'Removed')
ORDER BY [System.WorkItemType], [System.Id]
"""
    else:
        # Fallback: no iteration filter — return all active items assigned to me
        print(c("  WARNING: No iteration filter applied — returning all active items.", YELLOW))
        wiql = f"""
SELECT [System.Id]
FROM WorkItems
WHERE [System.AssignedTo] = '{me_escaped}'
  AND [System.WorkItemType] IN ('Product Backlog Item', 'Bug')
  AND [System.State] NOT IN ('Closed', 'Done', 'Removed')
ORDER BY [System.WorkItemType], [System.Id]
"""

    from azure.devops.v7_1.work_item_tracking.models import Wiql
    result = wit_client.query_by_wiql(Wiql(query=wiql))
    return [ref.id for ref in (result.work_items or [])]

# ── Item helpers (copied from ado-pull.py) ────────────────────────────────────
def fetch_item(client, item_id):
    try:
        return client.get_work_item(item_id, expand="Relations")
    except Exception as e:
        print(c(f"  WARNING: fetch {item_id} failed: {e}", YELLOW))
        return None

def item_to_dict(item, parent_id=None):
    """Convert an ADO work item to the YAML dict structure."""
    if not item:
        return None
    f = item.fields or {}

    d = {}
    d["id"]     = item.id
    d["type"]   = f.get("System.WorkItemType", "Product Backlog Item")
    d["title"]  = f.get("System.Title", "")
    d["status"] = f.get("System.State", "")

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
        d["release_notes"] = release_notes + "\n"

    item_fields = {}
    description = html_to_md(f.get("System.Description", ""))
    if description:
        item_fields["description"] = description + "\n"

    ac = html_to_md(f.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""))
    if ac:
        item_fields["acceptance_criteria"] = ac + "\n"

    if item_fields:
        d["fields"] = item_fields

    return d

def parent_id_of(item):
    """Return the parent work item ID via Hierarchy-Reverse relation, or None."""
    if not item or not item.relations:
        return None
    for rel in item.relations:
        if rel.rel == "System.LinkTypes.Hierarchy-Reverse":
            try:
                return int(rel.url.rstrip("/").split("/")[-1])
            except (ValueError, IndexError):
                pass
    return None

# ── YAML multiline representer ────────────────────────────────────────────────
class _Dumper(yaml.Dumper):
    pass

def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)

_Dumper.add_representer(str, _str_representer)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c("  ADO PULL MY SPRINT", BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  User   : {ADO_ME}")
    print(f"  Org    : {ORG_URL}")
    print(f"  Project: {PROJECT}")

    print(f"\n  Connecting...", end="", flush=True)
    try:
        wit_client = get_clients()
    except Exception as e:
        sys.exit(f"\nERROR: Cannot connect: {e}")
    print(" ok")

    print("  Resolving current sprint...", end="", flush=True)
    iter_path, _ = get_current_iteration(wit_client)
    if iter_path:
        print(f" ok  ({iter_path})")
    else:
        print(" not found (no iteration filter)")

    print("  Querying sprint items...", end="", flush=True)
    try:
        item_ids = query_sprint_items(wit_client, iter_path)
    except Exception as e:
        sys.exit(f"\nERROR: WIQL query failed: {e}")
    print(f" done  ({len(item_ids)} item(s))")

    if not item_ids:
        print(c("\n  No items found. Nothing to write.", YELLOW))
        return

    print("  Fetching item details...")
    items = []
    for item_id in item_ids:
        ado_item = fetch_item(wit_client, item_id)
        if not ado_item:
            continue
        pid = parent_id_of(ado_item)
        d = item_to_dict(ado_item, parent_id=pid)
        if d:
            items.append(d)
            itype = d.get("type", "?")
            print(f"    {c(str(item_id), CYAN)}  {c(itype, DIM)}  [{d.get('status', '')}]  {d.get('title', '')}")

    # ── Build output ───────────────────────────────────────────────────────────
    sprint_num = sprint_number(iter_path)
    output = {
        "meta": {
            "generated":   str(date.today()),
            "assigned_to": ADO_ME,
            "sprint":      iter_path or "unknown",
        },
        "items": items,
    }

    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)
    filename = out_dir / f"my-sprint-{sprint_num}.yaml"
    with open(filename, "w", encoding="utf-8") as fh:
        yaml.dump(output, fh, Dumper=_Dumper, allow_unicode=True,
                  sort_keys=False, default_flow_style=False, width=120)

    print()
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(c(f"  Saved → {filename}", GREEN + BOLD))
    print(c("══════════════════════════════════════════════════════════", BOLD))
    print(f"  Sprint : {iter_path or 'unknown'}")
    print(f"  Items  : {len(items)}")
    print()


if __name__ == "__main__":
    main()
