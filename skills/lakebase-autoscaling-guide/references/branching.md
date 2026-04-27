# Branching

Lakebase branches are copy-on-write database snapshots — like git branches for Postgres. A branch shares storage with its source until divergence, so creating one is cheap and instant.

## Contents

- Branch lifecycle
- Creating a branch
- Attaching an endpoint
- Read replicas
- Protecting branches
- Deletion (and what cascades)
- Point-in-time semantics
- Common branching patterns

## Branch lifecycle

```
CREATING → READY → (writes + reads) → DELETING → (gone)
                ↘ PROTECTED (delete blocked until unprotected)
```

- A new project always has one branch named `production` with a `primary` endpoint.
- A new branch created via `create-branch` **also receives a `primary` read-write endpoint automatically**, sized from the parent project's `default_endpoint_settings` (autoscaling bounds + `suspend_timeout_duration`).
- To get a "data only" branch, you would have to delete the auto-created `primary` after creation — but read-write endpoints can only be deleted by deleting the branch, so in practice every live branch has at least its `primary`.
- To customize a branch's endpoint sizing, run `update-endpoint` on its `primary` after creation, or set the project's `default_endpoint_settings` before creating the branch.

## Creating a branch

```bash
databricks postgres create-branch projects/<p> <new-branch> \
  --json '{"spec": {
    "source_branch": "projects/<p>/branches/production",
    "no_expiry": true
  }}' \
  -p <PROFILE>
```

Spec fields:

| Field | Purpose |
|---|---|
| `source_branch` | Branch to fork from. Defaults to `production` if omitted. |
| `no_expiry` | If `true`, branch lives until manually deleted. If `false`/omitted, may auto-expire (check current API behavior). |
| `parent_lsn` | Optional: fork from a specific WAL position (point-in-time branch). |
| `parent_timestamp` | Optional: fork from a specific timestamp. |

For a point-in-time branch (e.g. "data as of 2 hours ago"):

```bash
databricks postgres create-branch projects/<p> hotfix-from-yesterday \
  --json '{"spec": {
    "source_branch": "projects/<p>/branches/production",
    "parent_timestamp": "2026-04-26T18:00:00Z",
    "no_expiry": true
  }}' \
  -p <PROFILE>
```

## Customizing the auto-created endpoint

A new branch's `primary` endpoint inherits the project's `default_endpoint_settings`. To change `autoscaling_limit_min_cu` / `autoscaling_limit_max_cu` after creation:

```bash
databricks postgres update-endpoint projects/<p>/branches/<branch>/endpoints/primary \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}' \
  -p <PROFILE>
```

`suspend_timeout_duration` cannot be changed on an existing endpoint — it's only settable at `create-endpoint` time. To get a different suspend behavior on a branch's `primary`, change the project's `default_endpoint_settings` **before** creating the branch:

```bash
databricks postgres update-project projects/<p> "spec.default_endpoint_settings" \
  --json '{"spec": {"default_endpoint_settings": {
    "autoscaling_limit_min_cu": 0.5,
    "autoscaling_limit_max_cu": 2,
    "suspend_timeout_duration": "300s"
  }}}' \
  -p <PROFILE>
# then: create-branch ...
```

- Each branch has **one** read-write endpoint at most (the auto-created `primary`).
- Multiple read-only endpoints (replicas) are allowed — add them with `create-endpoint`.

For dev/preview branches set `min_cu=0.5`. For prod branches set `min_cu>=1` to avoid cold-start latency.

## Read replicas

```bash
databricks postgres create-endpoint projects/<p>/branches/production replica-1 \
  --json '{"spec": {
    "endpoint_type": "ENDPOINT_TYPE_READ_ONLY",
    "autoscaling_limit_min_cu": 0.5,
    "autoscaling_limit_max_cu": 4.0
  }}' \
  -p <PROFILE>
```

Endpoint IDs must be 3-63 chars (`rw`, `ro` are rejected — use `replica-1`, `read-only`, etc.).

Read replicas are eventually-consistent reads of the same branch — useful for analytics, reporting, and offloading read traffic. They have their own endpoint host; clients must explicitly connect to the replica host to use it.

## Protecting branches

Mark `production` (or any critical branch) as protected to block accidental deletion:

```bash
databricks postgres update-branch projects/<p>/branches/production \
  "spec.is_protected" \
  --json '{"spec": {"is_protected": true}}' \
  -p <PROFILE>
```

Unprotect the same way with `false`. You must unprotect before delete will succeed.

## Deletion

```bash
# Delete a non-root branch — cascades to ALL its endpoints
databricks postgres delete-branch projects/<p>/branches/<branch> -p <PROFILE>

# Delete a project — cascades to ALL branches, endpoints, and data
databricks postgres delete-project projects/<p> -p <PROFILE>
```

What cascades:

| Action | Cascades to |
|---|---|
| Delete endpoint (read-only) | Just that endpoint |
| Delete non-root branch | All endpoints on the branch + branch data |
| Delete project | All branches (including root) + all endpoints + all data |

**Hard constraints** (server-enforced, not just convention):

- **Root branches cannot be deleted independently.** The default `production` branch on a project is the root. Attempting `delete-branch` returns: `Cannot delete root branch ... Root branches cannot be deleted independently.` This holds whether the branch is protected or not. To remove `production`, delete the whole project.
- **Read-write endpoints cannot be deleted independently.** `delete-endpoint` on a `ENDPOINT_TYPE_READ_WRITE` endpoint returns: `Cannot delete read-write endpoint ... Read-write endpoints cannot be deleted.` Delete the parent branch instead (cascades).
- **Read-only endpoints (replicas) can be deleted individually** with `delete-endpoint` and stay deleted; the parent branch isn't affected.

`is_protected` provides an additional manual lock for non-root branches — it just blocks `delete-branch` until you unprotect.

## Common branching patterns

### Dev branch off production

```bash
databricks postgres create-branch projects/my-app dev \
  --json '{"spec": {"source_branch": "projects/my-app/branches/production", "no_expiry": true}}' \
  -p $PROFILE

# `primary` was auto-created — resize it for dev (suspend_timeout_duration is not changeable post-create):
databricks postgres update-endpoint projects/my-app/branches/dev/endpoints/primary \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 1.0}}' \
  -p $PROFILE
```

### Per-PR preview branches

In CI, create a branch named after the PR number, run integration tests, delete on PR close:

```bash
PR=$1
databricks postgres create-branch projects/my-app pr-$PR \
  --json '{"spec": {"source_branch": "projects/my-app/branches/production"}}' \
  -p $PROFILE
# ... run tests ...
databricks postgres delete-branch projects/my-app/branches/pr-$PR -p $PROFILE
```

### Pre-migration safety branch

Before a destructive migration, branch off, run the migration on the branch, validate, then either promote or discard.

```bash
databricks postgres create-branch projects/my-app premigration-$(date +%Y%m%d) \
  --json '{"spec": {"source_branch": "projects/my-app/branches/production", "no_expiry": true}}' \
  -p $PROFILE
```

### Restore via point-in-time branch

If `production` got corrupted at `T`, branch from `T - 5min`, copy the missing/correct rows back to production via `INSERT ... SELECT` over a foreign data wrapper or `pg_dump`/`COPY`.
