---
name: lakebase-status
description: Show the state of a Lakebase Autoscaling project — branches, endpoints, hosts, autoscaling bounds, and current state.
argument-hint: <project-id> [--profile PROFILE]
---

# /lakebase-status

Print a compact, human-readable view of a project's branches and endpoints.

## Usage

```
/lakebase-status <project-id> [--profile PROFILE]
```

## Execution

Invoke the `lakebase-autoscaling-guide` skill, then gather data in three calls:

```bash
PROFILE=<profile>
PROJECT=<project-id>

databricks postgres get-project projects/$PROJECT --profile $PROFILE --output json
databricks postgres list-branches projects/$PROJECT --profile $PROFILE --output json
# For each branch:
databricks postgres list-endpoints projects/$PROJECT/branches/<branch-id> --profile $PROFILE --output json
```

Format the output as:

```
Project: <project-id>
  Display name: <display_name>
  Created:      <create_time>

Branches:
  - production  (READY, protected)
      primary       READ_WRITE  ACTIVE   min=0.5 max=2.0   <host>
      replica-1     READ_ONLY   ACTIVE   min=0.5 max=4.0   <host>
  - dev         (READY)
      rw            READ_WRITE  IDLE     min=0.5 max=1.0   <host>
```

Columns:

- `READY` / `READY` (protected) for branches.
- Endpoint type (`READ_WRITE` / `READ_ONLY`).
- Endpoint state (`ACTIVE`, `STARTING`, `IDLE`, `STOPPED`, `FAILED`).
- Autoscaling bounds.
- Host (truncated with `...` if long).

## Highlight surprising things

After the table, surface anything unusual:

- Endpoints in `FAILED` or stuck in `STARTING` for more than 2 minutes — print `status.failure_reason` if present.
- Branches with no endpoints (data-only).
- Endpoints whose `min_cu == max_cu` (autoscaling effectively disabled).
- `min_cu = 0.5` on a branch named `production` (scale-to-zero on prod is usually a smell).

These are observations, not auto-fixes — let the user decide.
