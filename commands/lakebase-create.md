---
name: lakebase-create
description: Create a Databricks Lakebase Autoscaling project (auto-creates production branch + primary endpoint) and wait for it to reach ACTIVE.
argument-hint: <project-id> [--profile PROFILE] [--display-name "..."] [--min-cu 0.5] [--max-cu 2]
---

# /lakebase-create

Create a new Lakebase Autoscaling project. The project comes with a `production` branch and a `primary` read-write endpoint by default.

## Usage

```
/lakebase-create <project-id> [--profile PROFILE] [--display-name "Display Name"] [--min-cu 0.5] [--max-cu 2]
```

Arguments:

- `<project-id>` — required. 3-63 chars, lowercase letters/numbers/hyphens, must start with a letter.
- `--profile` — Databricks CLI profile. Defaults to `DEFAULT` if not set.
- `--display-name` — human-readable name. Defaults to the project ID.
- `--min-cu`, `--max-cu` — autoscaling bounds for the primary endpoint. If both omitted, the API defaults (1/1) are used. If supplied, both must be in 0.5-32, `min ≤ max`, and `max - min ≤ 16` (server-enforced).

## Execution

Invoke the `lakebase-autoscaling-guide` skill to load context, then:

1. **Validate prerequisites**
   - `databricks --version` is 0.285.0 or higher.
   - Profile is reachable: `databricks current-user me --profile <PROFILE>`.
   - Project ID matches `^[a-z][a-z0-9-]{2,62}$`.

2. **Create the project** (the CLI default-waits for completion; use `--no-wait` if you want to poll yourself)
   ```bash
   databricks postgres create-project <project-id> --profile <PROFILE>
   ```
   Note: `create-project` silently ignores `display_name` in its payload. Set it in step 4 if `--display-name` was provided.

3. **Wait for ACTIVE** (poll every 5s, time out at 5 minutes; only needed with `--no-wait`)
   ```bash
   databricks postgres list-endpoints projects/<project-id>/branches/production \
     --profile <PROFILE> --output json | jq -r '.[0].status.current_state'
   ```
   Expect: `STARTING` → `ACTIVE`. If `FAILED`, surface `status.failure_reason`.

4. **Apply display name and/or scaling bounds (only if any of `--display-name`, `--min-cu`, `--max-cu` were passed)**
   ```bash
   # Display name
   databricks postgres update-project projects/<project-id> "spec.display_name" \
     --json '{"spec": {"display_name": "<display-name>"}}' \
     --profile <PROFILE>

   # Scaling bounds on the auto-created primary endpoint
   databricks postgres update-endpoint \
     projects/<project-id>/branches/production/endpoints/primary \
     "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
     --json '{"spec": {"autoscaling_limit_min_cu": <min>, "autoscaling_limit_max_cu": <max>}}' \
     --profile <PROFILE>
   ```

5. **Print a summary**
   - Project path, branch path, endpoint path.
   - Endpoint host (from `status.hosts.host`).
   - Suggested next steps:
     - Quick interactive: `databricks psql --project <project-id> -p <PROFILE>`.
     - Programmatic / `--export`: `/lakebase-connect projects/<project-id>/branches/production/endpoints/primary --profile <PROFILE>`.

## Failure modes

- `unknown command "postgres"` → CLI is too old; tell the user to `brew upgrade databricks` and stop.
- Project ID already exists → ask the user to pick a different ID; do not retry.
- Endpoint stuck in `STARTING` past 5 minutes → surface the JSON `status` block; do not poll forever.
