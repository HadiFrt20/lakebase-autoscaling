---
name: lakebase-destroy
description: Delete a Lakebase Autoscaling project or branch. Always confirms with the user first; deletion is permanent and cascades.
argument-hint: <path> [--profile PROFILE] [--yes]
---

# /lakebase-destroy

Delete a Lakebase project or branch. Cascades aggressively — see the cascade rules below.

## Usage

```
/lakebase-destroy <path> [--profile PROFILE] [--yes]
```

Where `<path>` is **either**:

- `projects/<project-id>` — delete the project (cascades to all branches, endpoints, and data).
- `projects/<project-id>/branches/<branch-id>` — delete one branch (cascades to its endpoints).

`--yes` skips the explicit confirmation prompt. Required when running non-interactively (e.g. from a CI command file). For interactive use, omit it and confirm at the prompt.

## Execution

Invoke the `lakebase-autoscaling-guide` skill, then:

1. **Inspect what will be deleted**
   - Project case: list all branches and endpoints. Show row count of each branch's logical databases if cheap (skip if it requires opening connections).
   - Branch case: list its endpoints. Note that read-write endpoints can only be deleted via the branch.

2. **Show a summary and ask for confirmation** (unless `--yes`)
   ```
   You are about to delete: projects/my-app/branches/dev

   Branch: dev (READY)
     Endpoints: rw (ACTIVE)

   This is PERMANENT. All data on this branch will be lost. Type "delete" to proceed.
   ```
   Accept only literal `delete` (case-sensitive) as confirmation. Anything else → abort.

3. **Unprotect if needed** (branch case only)
   ```bash
   databricks postgres update-branch <branch-path> "spec.is_protected" \
     --json '{"spec": {"is_protected": false}}' \
     --profile <PROFILE>
   ```
   Skip if not protected.

4. **Delete**
   ```bash
   # Branch
   databricks postgres delete-branch <branch-path> --profile <PROFILE>

   # Project
   databricks postgres delete-project <project-path> --profile <PROFILE>
   ```

5. **Verify it's gone**
   - Branch: `databricks postgres get-branch <branch-path>` should return 404.
   - Project: `databricks postgres get-project <project-path>` should return 404.

## Cascade rules

| Target | Cascades to |
|---|---|
| Read-only endpoint | The endpoint only (use `delete-endpoint`, **not** this command — but this command is project/branch only) |
| Branch | All endpoints on the branch + branch data |
| Project | All branches + all endpoints + all data |

> **Cascade caveat for UC**: whether deleting a project automatically removes UC catalogs registered against it (or synced tables that reference it) is **not documented**. Treat any UC integration as separately managed: list and clean up UC catalogs before destroying the project to avoid dangling references.

## Refusal cases

Refuse to proceed (with a clear message) when:

- The user passes an endpoint path — only project and branch paths are supported here.
- The path is `projects/<p>/branches/production` (or any root branch). The API itself blocks `delete-branch` on root branches with `Cannot delete root branch ... Root branches cannot be deleted independently.` Tell the user to delete the whole project instead, or pick a non-root branch.
- The CLI returns auth errors mid-flight — stop, do not retry blindly.
