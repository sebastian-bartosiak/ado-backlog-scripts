# ADO CLI Tools

Three lightweight Python scripts for syncing Azure DevOps work items with local YAML files.

| Script | What it does |
|---|---|
| `ado-pull.py` | Fetch a work item and its descendants; save to `data/<Type>_<id>.yaml` |
| `ado-pull-my-sprint.py` | Fetch all PBIs & Bugs assigned to you in the current sprint; save to `data/my-sprint-<N>.yaml` |
| `ado-push.py` | Compare a local YAML plan against ADO, then interactively apply updates / creates / reparents / deletes |

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
   ```

### `.env` keys

| Key | Required by | Description |
|---|---|---|
| `ADO_PAT` | all scripts | Personal Access Token with **Work Items (Read & Write)** scope |
| `ADO_ORG_URL` | all scripts | e.g. `https://dev.azure.com/myorg` |
| `ADO_PROJECT` | all scripts | Project name, e.g. `xxx` |
| `ADO_ME` | `ado-pull-my-sprint.py` | Your display name as it appears in ADO `AssignedTo` |

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
`Product Backlog Item` and `Bug` items assigned to `ADO_ME` that are not Closed / Done / Removed.

Output: `data/my-sprint-<SprintNumber>.yaml`
Example: `data/my-sprint-104.yaml`

---

### Push changes back to ADO

```bash
uv run ado-push.py data/Feature_275453.yaml
```

Fetches the current ADO state, diffs it against the YAML, and walks you through each change
interactively before writing anything:

- **Updates** — title, description, acceptance criteria
- **Creates** — new child items (leave `id:` blank in the YAML)
- **Reparents** — items whose `parent_id` changed
- **Orphans** — items present in ADO but missing from the YAML (keep / unlink / delete)

---

## Workflow

```
1. ado-pull.py 275453          # fetch Feature + children → data/Feature_275453.yaml
2. edit data/Feature_275453.yaml  # refine titles, descriptions, AC; add new items
3. ado-push.py data/Feature_275453.yaml  # review diff, approve changes, write to ADO
4. ado-pull.py 275453          # re-pull to pick up any ADO-side changes / new IDs
```

---

## Output files

All YAML output lands in `data/` (git-ignored). Never commit files from this folder — they may
contain sensitive project details.
