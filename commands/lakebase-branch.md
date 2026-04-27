---
name: lakebase-branch
description: Create a Lakebase Autoscaling branch from a source (default `production`) and attach a read-write endpoint so it's reachable.
argument-hint: <project-id> <branch-id> [--from SOURCE_BRANCH] [--profile PROFILE] [--min-cu 0.5] [--max-cu 2] [--no-endpoint]
---

# /lakebase-branch

Create a new branch off an existing branch and (by default) attach a read-write endpoint so the branch is connectable.

## Usage

```
/lakebase-branch <project-id> <branch-id> [--from <source-branch>] [--profile PROFILE] \
                                          [--min-cu 0.5] [--max-cu 2] [--no-endpoint]
```

Arguments:

- `<project-id>` — required.
- `<branch-id>` — required. 3-63 chars, lowercase letters/numbers/hyphens, starts with a letter.
- `--from` — source branch ID. Defaults to `production`.
- `--profile` — Databricks CLI profile.
- `--min-cu`, `--max-cu` — autoscaling bounds for the auto-created `primary` endpoint (applied via `update-endpoint` after `create-branch`). Default: `0.5` / `2`. Must satisfy `0.5 ≤ min ≤ max ≤ 32` and `max - min ≤ 16` (server-enforced).
- `--no-endpoint` — kept for forward-compat; on the current API `create-branch` always provisions `primary` (read-write endpoints can't be deleted individually). With this flag, just skip the resize step.

## Execution

Invoke the `lakebase-autoscaling-guide` skill, then:

1. **Validate**
   - Project exists: `databricks postgres get-project projects/<project-id>`.
   - Source branch exists.
   - `--min-cu` / `--max-cu` in `[0.5, 32]`, `min ≤ max`, and `max - min ≤ 16`.
   - All resource IDs are 3-63 chars, lowercase letters/digits/hyphens, start with a letter.

2. **Create the branch** (auto-creates a `primary` read-write endpoint sized from the project's `default_endpoint_settings`)
   ```bash
   databricks postgres create-branch projects/<project-id> <branch-id> \
     --json '{"spec": {
       "source_branch": "projects/<project-id>/branches/<source>",
       "no_expiry": true
     }}' \
     --profile <PROFILE>
   ```

3. **Resize the auto-created `primary` endpoint** if `--min-cu` / `--max-cu` differ from the project defaults
   ```bash
   databricks postgres update-endpoint projects/<project-id>/branches/<branch-id>/endpoints/primary \
     "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
     --json '{"spec": {
       "autoscaling_limit_min_cu": <min>,
       "autoscaling_limit_max_cu": <max>
     }}' \
     --profile <PROFILE>
   ```

   **Note**: `--no-endpoint` is a no-op on the current API — `create-branch` always provisions `primary`. To get rid of it, you'd have to delete the branch (read-write endpoints can't be deleted individually). The flag is kept for forward-compatibility; document that and skip the resize step.

4. **Wait for ACTIVE**, then print the endpoint host and a suggested `/lakebase-connect` invocation.

## Recommended patterns

- **Dev branch**: `--min-cu 0.5 --max-cu 1` for scale-to-zero.
- **Per-PR preview**: name the branch `pr-<num>`; delete on PR close with `/lakebase-destroy`.
- **Pre-migration safety branch**: branch off `production`, run the migration on the branch, validate, then either promote or discard.

## Failure modes

- Branch ID already exists → ask the user to pick a different name.
- Source branch missing → list available branches and stop.
- Endpoint creation fails after branch creation succeeded → tell the user the branch exists but is "data only"; suggest `/lakebase-branch` again with a different endpoint config or manual `create-endpoint`.
