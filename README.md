# ADO Backlog Scripts

`uv run`-able Python scripts for working with an Azure DevOps backlog from the command line —
pull/push work item trees, create tasks and bugs, assign, tag, change status, comment, and
search by tag. All scripts share a common library (`ado_lib.py`) and are configured entirely
through `.env`, so the same scripts work across different organizations/projects/process
templates — just point them at a different `.env`.

| Script | What it does |
|---|---|
| `ado-pull.py` | Fetch a work item and its descendants; save to `data/<Type>_<id>.yaml` |
| `ado-pull-my-sprint.py` | Fetch all Story/PBI & Bug items assigned to you in the current sprint; save to `data/my-sprint-<N>.yaml` |
| `ado-push.py` | Compare a local YAML plan against ADO, then interactively apply updates / creates / reparents / deletes |
| `ado-create-task.py` | Create a Task under a parent work item |
| `ado-create-bug.py` | Create a Bug in the current sprint |
| `ado-set-owner.py` | Assign one or more work items to yourself (or someone else, or clear assignment) |
| `ado-set-tags.py` | Add / remove / list tags on a work item |
| `ado-set-status.py` | Change a work item's state, optionally with a comment |
| `ado-add-comment.py` | Add a comment to a work item |
| `ado-search.py` | Query items by tag/type/state/assignee/iteration; prints a table and saves to `data/query-<timestamp>.yaml` |

All ADO reads/writes go through `ado_lib.py`, which also makes sure multiline fields
(Description, Acceptance Criteria, Repro Steps) are written as **Markdown**, not HTML, and
that comments are posted through the modern Comments API rendered as Markdown.

---

## Prerequisites

- **Python ≥ 3.11**
- [`uv`](https://github.com/astral-sh/uv) (recommended — handles dependencies automatically)
  _or_ install dependencies manually with `pip`

---

## Setup

1. Copy the example env file and fill in your values:

   ```bash
   cp example.env .env
   # or place it at .vscode/.env  (checked first)
   ```

2. Edit `.env`:

   ```
   ADO_PAT=<your Personal Access Token>
   ADO_ORG_URL=https://dev.azure.com/<your-org>
   ADO_PROJECT=<your-project>
   ADO_ME=Firstname Lastname

   ADO_TYPE_STORY=Product Backlog Item
   ADO_TYPE_TASK=Task
   ADO_TYPE_BUG=Bug
   ```

   Working across multiple organizations? Keep a separate `.env` per org (they're git-ignored)
   and swap the active one in before running scripts against that org.

### `.env` keys

| Key | Required by | Description |
|---|---|---|
| `ADO_PAT` | all scripts | Personal Access Token with **Work Items (Read & Write)** scope |
| `ADO_ORG_URL` | all scripts | e.g. `https://dev.azure.com/myorg` |
| `ADO_PROJECT` | all scripts | Project name, e.g. `xxx` |
| `ADO_ME` | `ado-pull-my-sprint.py`, `ado-set-owner.py`, `ado-create-task.py`, `ado-create-bug.py`, `ado-search.py --assigned-to me` | Your display name as it appears in ADO `AssignedTo` |
| `ADO_TYPE_STORY` | `ado-search.py`, `ado-push.py` (default create type) | Name of your "top-level backlog item" type, e.g. `Product Backlog Item` or `User Story` |
| `ADO_TYPE_TASK` | `ado-create-task.py`, `ado-search.py` | Task type name |
| `ADO_TYPE_BUG` | `ado-create-bug.py`, `ado-search.py` | Bug type name |

Different orgs name types differently (Scrum: *Product Backlog Item*, Agile/CMMI: *User Story*
or *Requirement*) — set `ADO_TYPE_STORY`/`ADO_TYPE_TASK`/`ADO_TYPE_BUG` to match yours.
State names (`Active`, `Resolved`, `Closed`, `Done`, ...) also vary by process template;
scripts that take a state (`ado-set-status.py`, `ado-search.py --state`) accept whatever raw
string your org uses.

---

## Usage

### Pull a work item tree

```bash
uv run ado-pull.py <work_item_id>
uv run ado-pull.py <work_item_id> --depth 0   # unlimited depth
uv run ado-pull.py <work_item_id> --depth 2   # two levels of children
```

Output: `data/<WorkItemType>_<id>.yaml`
Example: `data/Feature_275453.yaml`

---

### Pull your current sprint

```bash
uv run ado-pull-my-sprint.py
```

Automatically resolves the active sprint from the project's iteration tree and queries all
`ADO_TYPE_STORY` and `ADO_TYPE_BUG` items assigned to `ADO_ME` that are not Closed / Done / Removed.

Output: `data/my-sprint-<SprintNumber>.yaml`
Example: `data/my-sprint-104.yaml`

---

### Push changes back to ADO

```bash
uv run ado-push.py data/Feature_275453.yaml
```

Fetches the current ADO state, diffs it against the YAML, and walks you through each change
interactively before writing anything:

- **Updates** — title, description, acceptance criteria, repro steps
- **Creates** — new child items (leave `id:` blank in the YAML)
- **Reparents** — items whose `parent_id` changed
- **Orphans** — items present in ADO but missing from the YAML (keep / unlink / delete)

After a create succeeds, the new ADO id is written back into the source YAML file (its `id:`
becomes the real id instead of blank) — safe to re-run `ado-push.py` against the same file
without creating duplicates.

---

### Create a task under a parent item

```bash
uv run ado-create-task.py <parent_id> "Wire up the retry logic"
uv run ado-create-task.py <parent_id> "Wire up the retry logic" --description "Handles the 429 case, see AC 3."
uv run ado-create-task.py <parent_id> "Investigate flaky test" --no-assign
```

Area Path is inherited from the parent unless `--area` is given. Iteration defaults to the
current sprint unless `--iteration` is given. Assigned to `ADO_ME` unless `--no-assign`.

---

### Create a bug in the current sprint

```bash
uv run ado-create-bug.py "Login button is unresponsive on Safari"
uv run ado-create-bug.py "Crash on save" --repro-steps "1. Open item\n2. Edit title\n3. Save" --parent-id 12345
```

Iteration defaults to the current sprint. If `--parent-id` is given and `--area` is not, Area
Path is inherited from the parent. Assigned to `ADO_ME` unless `--no-assign`.

---

### Assign work items

```bash
uv run ado-set-owner.py 12345                 # assign to ADO_ME
uv run ado-set-owner.py 12345 67890            # assign multiple items to ADO_ME
uv run ado-set-owner.py 12345 --to "Someone Else"
uv run ado-set-owner.py 12345 --unassign
```

---

### Tag work items

```bash
uv run ado-set-tags.py add 12345 needs-design tech-debt
uv run ado-set-tags.py remove 12345 tech-debt
uv run ado-set-tags.py list 12345
```

---

### Change status / add comments

```bash
uv run ado-set-status.py 12345 Active
uv run ado-set-status.py 12345 Closed --comment "Verified in staging, closing."
uv run ado-add-comment.py 12345 "Blocked on the API team — see thread in #backend."
```

---

### Search by tag / type / state / assignee / iteration

```bash
uv run ado-search.py --tag needs-design
uv run ado-search.py --tag tech-debt --type Bug
uv run ado-search.py --assigned-to me --iteration current
uv run ado-search.py --tag urgent --all-states
```

`--tag` is repeatable and ANDed (an item must have all given tags). `--type` defaults to
`ADO_TYPE_STORY` + `ADO_TYPE_TASK` + `ADO_TYPE_BUG`. `--state` defaults to excluding
Closed/Done/Removed (pass `--all-states` to see everything). `--assigned-to me` resolves to
`ADO_ME`; `--iteration current` resolves the active sprint.

Prints a table and saves full results to `data/query-<timestamp>.yaml`.

---

## Workflow

```
1. ado-pull.py 275453              # fetch Feature + children → data/Feature_275453.yaml
2. edit data/Feature_275453.yaml   # refine titles, descriptions, AC; add new items
3. ado-push.py data/Feature_275453.yaml  # review diff, approve changes, write to ADO
4. ado-create-task.py 275460 "Set up CI job"   # add a task under one of the new items
5. ado-set-tags.py add 275460 sprint-goal
6. ado-set-status.py 275460 Active
```

---

## Output files

All YAML output lands in `data/` (git-ignored). Never commit files from this folder — they may
contain sensitive project details.

---

## Development

`ado_lib.py` holds everything shared across scripts: `.env` loading, the ADO client, HTML→Markdown
conversion, YAML I/O, work item patch-op helpers, tag parsing, iteration/sprint resolution, WIQL
helpers, and the comment API wrapper. Each script imports it via a sibling `sys.path` insert —
there's no packaging step.

Run the unit tests for `ado_lib.py`'s pure helpers:

```bash
uv run pytest
```
