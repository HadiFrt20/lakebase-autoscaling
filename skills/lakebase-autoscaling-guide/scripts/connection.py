"""Reusable helpers for connecting to a Databricks Lakebase Autoscaling endpoint.

Two entry points:

    from connection import lakebase_credentials, lakebase_psycopg, lakebase_sqlalchemy

    creds = lakebase_credentials("my-app", "production", "primary", profile="dev")
    # creds = {"host": "...", "user": "you@org.com", "token": "...", ...}

    conn = lakebase_psycopg("my-app", "production", "primary", profile="dev", dbname="shop")
    engine = lakebase_sqlalchemy("my-app", "production", "primary", profile="dev", dbname="shop")

OAuth tokens expire after 60 minutes; long-running services should re-fetch
periodically (see TokenRefresher) and recycle connections accordingly.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

CLI = "databricks"
TOKEN_TTL_SECONDS = 60 * 60  # OAuth tokens last 1 hour
REFRESH_BEFORE_SECONDS = 5 * 60  # refresh 5 minutes before expiry

# Resource IDs: 3-63 chars, start with a lowercase letter, only [a-z0-9-]. The API rejects shorter/non-conforming IDs.
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,62}$")


def _validate_id(kind: str, value: str) -> None:
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"{kind} {value!r} is invalid: must be 3-63 chars, lowercase letters/digits/hyphens, starting with a letter."
        )


@dataclass(frozen=True)
class LakebaseCredentials:
    host: str
    user: str
    token: str
    issued_at: float

    def expires_at(self) -> float:
        return self.issued_at + TOKEN_TTL_SECONDS

    def is_fresh(self) -> bool:
        return time.time() < self.expires_at() - REFRESH_BEFORE_SECONDS

    def url(self, dbname: str, driver: str = "psycopg") -> str:
        return (
            f"postgresql+{driver}://{self.user}:{quote_plus(self.token)}"
            f"@{self.host}:5432/{dbname}?sslmode=require"
        )


def _cli_json(args: list[str]) -> Any:
    result = subprocess.run([CLI, *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"databricks {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def lakebase_credentials(
    project: str, branch: str, endpoint: str, *, profile: str = "DEFAULT"
) -> LakebaseCredentials:
    """Fetch host + OAuth token + user email for a Lakebase Autoscaling endpoint."""
    _validate_id("project", project)
    _validate_id("branch", branch)
    _validate_id("endpoint", endpoint)
    endpoint_path = f"projects/{project}/branches/{branch}/endpoints/{endpoint}"

    endpoint_info = _cli_json([
        "postgres", "get-endpoint", endpoint_path,
        "--profile", profile, "--output", "json",
    ])
    try:
        host = endpoint_info["status"]["hosts"]["host"]
    except KeyError as e:
        raise ValueError(f"Endpoint {endpoint_path!r} has no host (state={endpoint_info.get('status',{}).get('current_state')!r})") from e

    token = _cli_json([
        "postgres", "generate-database-credential", endpoint_path,
        "--profile", profile, "--output", "json",
    ])["token"]

    user = _cli_json([
        "current-user", "me",
        "--profile", profile, "--output", "json",
    ])["userName"]

    return LakebaseCredentials(host=host, user=user, token=token, issued_at=time.time())


def lakebase_psycopg(
    project: str, branch: str, endpoint: str,
    *, profile: str = "DEFAULT", dbname: str = "postgres",
):
    """Return a live psycopg (v3) connection. Caller is responsible for closing it."""
    import psycopg  # type: ignore

    creds = lakebase_credentials(project, branch, endpoint, profile=profile)
    return psycopg.connect(
        host=creds.host, port=5432, dbname=dbname,
        user=creds.user, password=creds.token, sslmode="require",
    )


def lakebase_psycopg2(
    project: str, branch: str, endpoint: str,
    *, profile: str = "DEFAULT", dbname: str = "postgres",
):
    """Same as `lakebase_psycopg` but using the older psycopg2 driver."""
    import psycopg2  # type: ignore

    creds = lakebase_credentials(project, branch, endpoint, profile=profile)
    return psycopg2.connect(
        host=creds.host, port=5432, database=dbname,
        user=creds.user, password=creds.token, sslmode="require",
    )


def lakebase_sqlalchemy(
    project: str, branch: str, endpoint: str,
    *, profile: str = "DEFAULT", dbname: str = "postgres",
    driver: str = "psycopg", **engine_kwargs: Any,
):
    """Return a SQLAlchemy engine. Use `pool_pre_ping=True` (default below)."""
    from sqlalchemy import create_engine  # type: ignore

    creds = lakebase_credentials(project, branch, endpoint, profile=profile)
    engine_kwargs.setdefault("pool_pre_ping", True)
    return create_engine(creds.url(dbname, driver=driver), **engine_kwargs)


class TokenRefresher:
    """Background refresher for long-running services.

    Holds the latest credentials and refreshes ~5 minutes before token expiry.
    Use `.creds()` to read the latest credentials at runtime.

        refresher = TokenRefresher("my-app", "production", "primary", profile="dev")
        refresher.start()
        # ... in request handlers ...
        creds = refresher.creds()
    """

    def __init__(self, project: str, branch: str, endpoint: str, *, profile: str = "DEFAULT"):
        self._args = (project, branch, endpoint)
        self._profile = profile
        self._lock = threading.Lock()
        self._creds: LakebaseCredentials | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def creds(self) -> LakebaseCredentials:
        with self._lock:
            if self._creds is None or not self._creds.is_fresh():
                self._creds = lakebase_credentials(*self._args, profile=self._profile)
            return self._creds

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.creds()  # refresh if stale
            self._stop.wait(timeout=REFRESH_BEFORE_SECONDS)
