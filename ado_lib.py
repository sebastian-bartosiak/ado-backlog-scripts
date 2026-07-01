"""Shared helpers for the ado-*.py scripts: config, auth, formatting, WIQL, comments.

Not a uv-runnable script itself. Each script imports it via:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import ado_lib
"""

import html
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import html2text
from dotenv import load_dotenv
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from azure.devops.connection import Connection
from azure.devops.v7_1.work_item_tracking.models import CommentCreate, Wiql
from msrest.authentication import BasicAuthentication

# ── Field reference names ────────────────────────────────────────────────────
FIELD_TITLE               = "System.Title"
FIELD_DESCRIPTION         = "System.Description"
FIELD_ACCEPTANCE_CRITERIA = "Microsoft.VSTS.Common.AcceptanceCriteria"
FIELD_REPRO_STEPS         = "Microsoft.VSTS.TCM.ReproSteps"
FIELD_AREA_PATH           = "System.AreaPath"
FIELD_ITERATION_PATH      = "System.IterationPath"
FIELD_STATE               = "System.State"
FIELD_ASSIGNED_TO         = "System.AssignedTo"
FIELD_TAGS                = "System.Tags"

HIERARCHY_FORWARD = "System.LinkTypes.Hierarchy-Forward"
HIERARCHY_REVERSE = "System.LinkTypes.Hierarchy-Reverse"

# States considered "not actionable" for default query/sprint filters.
# Standard across Agile/Scrum/CMMI process templates.
DONE_STATES = ("Closed", "Done", "Removed")

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"; DIM = "\033[2m"

def c(text, *codes):
    return "".join(codes) + str(text) + R

def banner(title, *extra_codes):
    line = "═" * 62
    print()
    print(c(line, BOLD))
    print(c(f"  {title}", BOLD, *extra_codes))
    print(c(line, BOLD))

# ── Config ──────────────────────────────────────────────────────────────────
@dataclass
class Config:
    pat: str
    org_url: str
    project: str
    me: str
    type_story: str
    type_task: str
    type_bug: str


def load_config(script_file):
    """Load .env (checked at .vscode/.env first, then .env) relative to script_file."""
    root = Path(script_file).resolve().parent
    env_path = root / ".vscode" / ".env"
    if not env_path.exists():
        env_path = root / ".env"
    load_dotenv(env_path)

    pat = os.environ.get("ADO_PAT", "")
    if not pat:
        sys.exit("ADO_PAT not set in .env file")

    return Config(
        pat=pat,
        org_url=os.environ.get("ADO_ORG_URL", "https://dev.azure.com/xxx"),
        project=os.environ.get("ADO_PROJECT", "yyy"),
        me=os.environ.get("ADO_ME", ""),
        type_story=os.environ.get("ADO_TYPE_STORY", "Product Backlog Item"),
        type_task=os.environ.get("ADO_TYPE_TASK", "Task"),
        type_bug=os.environ.get("ADO_TYPE_BUG", "Bug"),
    )


def require_me(cfg):
    """Return cfg.me, or exit if ADO_ME is not configured."""
    if not cfg.me:
        sys.exit("ADO_ME not set in .env file (e.g. 'Name Surname')")
    return cfg.me

# ── ADO client ──────────────────────────────────────────────────────────────
def get_client(cfg):
    creds = BasicAuthentication("", cfg.pat)
    conn = Connection(base_url=cfg.org_url, creds=creds)
    return conn.clients.get_work_item_tracking_client()

# ── HTML → Markdown ─────────────────────────────────────────────────────────
_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.body_width = 0          # no line wrapping
_h2t.protect_links = True
_h2t.wrap_links = False

def html_to_md(raw):
    """Convert an ADO HTML field to clean Markdown. Handles plain text too."""
    if not raw:
        return ""
    stripped = raw.strip()
    if "<" not in stripped:
        # Plain text: unescape entities and normalise line endings
        text = html.unescape(stripped)
    else:
        text = _h2t.handle(stripped)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def literal(s):
    """Wrap a string so ruamel.yaml emits it as a block literal scalar (|)."""
    return LiteralScalarString(s + "\n")

# ── YAML ────────────────────────────────────────────────────────────────────
def get_yaml():
    """A ruamel.yaml instance configured consistently across all scripts."""
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 120
    return y

# ── Work item patch ops ───────────────────────────────────────────────────────
def op(operation, path, value=None):
    d = {"op": operation, "path": path}
    if value is not None:
        d["value"] = value
    return d


def markdown_field_ops(field_ref, value, value_op="add"):
    """Patch ops that set a multiline field's value and mark it as markdown."""
    return [
        op(value_op, f"/fields/{field_ref}", str(value)),
        op("replace", f"/multilineFieldsFormat/{field_ref}", "markdown"),
    ]


def relation_value(org_url, target_id, rel_type=HIERARCHY_REVERSE):
    return {"rel": rel_type, "url": f"{org_url}/_apis/wit/workItems/{target_id}"}

# ── Fetch / relations ─────────────────────────────────────────────────────────
def fetch_item(client, item_id):
    try:
        return client.get_work_item(item_id, expand="Relations")
    except Exception as e:
        print(c(f"  WARNING: fetch {item_id} failed: {e}", YELLOW))
        return None


def _related_id(rel):
    return int(rel.url.rstrip("/").split("/")[-1])


def children_of(item):
    if not item or not item.relations:
        return []
    return [_related_id(rel) for rel in item.relations if rel.rel == HIERARCHY_FORWARD]


def parent_of(item):
    if not item or not item.relations:
        return None
    for rel in item.relations:
        if rel.rel == HIERARCHY_REVERSE:
            return _related_id(rel)
    return None


def find_relation_idx(item, rel_type, target_id):
    if not item or not item.relations:
        return None
    for i, rel in enumerate(item.relations):
        if rel.rel == rel_type and _related_id(rel) == target_id:
            return i
    return None

# ── Tags ────────────────────────────────────────────────────────────────────
def parse_tags(raw):
    """ADO stores tags as a single '; '-separated string."""
    return [t.strip() for t in (raw or "").split(";") if t.strip()]


def format_tags(tags):
    return "; ".join(tags)


def identity_display_name(value):
    """AssignedTo (and similar identity fields) can be a plain string or an
    IdentityRef object depending on API/expand options."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return getattr(value, "display_name", None) or getattr(value, "unique_name", None) or str(value)

# ── Item <-> dict ───────────────────────────────────────────────────────────
def item_to_dict(item, parent_id=None, include_status=False):
    """Convert an ADO work item to the YAML dict structure used by pull/push/search."""
    if not item:
        return None
    f = item.fields or {}

    d = {}
    d["id"] = item.id
    d["type"] = f.get("System.WorkItemType", "")
    d["title"] = f.get(FIELD_TITLE, "")
    if include_status:
        d["status"] = f.get(FIELD_STATE, "")

    if parent_id is not None:
        d["parent_id"] = parent_id

    area = f.get(FIELD_AREA_PATH, "")
    if area:
        d["area"] = area

    iteration = f.get(FIELD_ITERATION_PATH, "")
    if iteration:
        d["iteration"] = iteration

    tags = parse_tags(f.get(FIELD_TAGS, ""))
    if tags:
        d["tags"] = tags

    assigned_to = identity_display_name(f.get(FIELD_ASSIGNED_TO))
    if assigned_to:
        d["assigned_to"] = assigned_to

    release_notes = html_to_md(f.get("Custom.ReleaseNotes", ""))
    if release_notes:
        d["release_notes"] = literal(release_notes)

    item_fields = {}
    description = html_to_md(f.get(FIELD_DESCRIPTION, ""))
    if description:
        item_fields["description"] = literal(description)

    ac = html_to_md(f.get(FIELD_ACCEPTANCE_CRITERIA, ""))
    if ac:
        item_fields["acceptance_criteria"] = literal(ac)

    repro = html_to_md(f.get(FIELD_REPRO_STEPS, ""))
    if repro:
        item_fields["repro_steps"] = literal(repro)

    if item_fields:
        d["fields"] = item_fields

    return d

# ── Iteration / sprint resolution ─────────────────────────────────────────────
def _as_date(val):
    """Coerce datetime / ISO-string / date / None → date, or None."""
    if not val:
        return None
    if hasattr(val, "date"):          # datetime object
        return val.date()
    if isinstance(val, str):          # ISO string e.g. "2026-01-14T00:00:00Z"
        try:
            return datetime.fromisoformat(val.rstrip("Z").split("T")[0]).date()
        except ValueError:
            return None
    return val                        # already a date


def _walk_nodes(node, today, best=None):
    """Recursively walk the project classification tree, returning the deepest
    node whose [start_date, finish_date] bracket contains today."""
    attrs = node.attributes or {}
    start = _as_date(attrs.get("startDate"))
    finish = _as_date(attrs.get("finishDate"))
    if start and finish and start <= today <= finish:
        depth = node.path.count("\\")
        if best is None or depth > best[0].count("\\"):
            best = (node.path, node.name)
    for child in (node.children or []):
        best = _walk_nodes(child, today, best)
    return best


def _normalize_iter_path(raw_path):
    """Convert classification node path to WIQL-compatible iteration path."""
    p = raw_path.lstrip("\\")                          # remove leading backslash
    # Remove the '\Iteration\' segment that classification nodes inject
    p = re.sub(r"^([^\\]+)\\Iteration\\", r"\1\\", p)
    return p


def get_current_iteration(wit_client, project):
    """Return (iteration_path, sprint_name) using the project-level classification
    node tree (depth=10), which includes all sprints regardless of team assignment."""
    today = date.today()
    try:
        root = wit_client.get_classification_node(project, "iterations", depth=10)
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

# ── WIQL ──────────────────────────────────────────────────────────────────────
def wiql_escape(value):
    return str(value).replace("'", "''")


def run_wiql(client, query):
    """Execute a WIQL query, return the list of matching work item ids."""
    result = client.query_by_wiql(Wiql(query=query))
    return [ref.id for ref in (result.work_items or [])]

# ── Comments ────────────────────────────────────────────────────────────────
def add_comment(client, project, item_id, text):
    """Add a comment via the modern Comments API, rendered as markdown."""
    return client.add_work_item_comment(CommentCreate(text=text), project, item_id, format="Markdown")
