from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(os.getenv("BURN_LEDGER_DB", Path(__file__).resolve().parents[1] / "data" / "burn-ledger.db"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS subscriptions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      provider TEXT NOT NULL,
      plan_name TEXT NOT NULL,
      monthly_price REAL NOT NULL DEFAULT 0,
      currency TEXT NOT NULL DEFAULT 'USD',
      billing_cycle TEXT NOT NULL DEFAULT 'monthly',
      source_url TEXT,
      price_regex TEXT,
      auto_update_price INTEGER NOT NULL DEFAULT 0,
      evidence_status TEXT NOT NULL DEFAULT 'user_configured',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(provider, plan_name)
    );

    CREATE TABLE IF NOT EXISTS subscription_price_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
      captured_at TEXT NOT NULL,
      monthly_price REAL NOT NULL,
      currency TEXT NOT NULL,
      reason TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS quota_pools (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      reset_window TEXT,
      evidence_status TEXT NOT NULL DEFAULT 'official',
      source_url TEXT,
      policy_json TEXT NOT NULL DEFAULT '{}',
      UNIQUE(subscription_id, name)
    );

    CREATE TABLE IF NOT EXISTS model_catalog (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      external_id TEXT NOT NULL,
      provider TEXT,
      display_name TEXT,
      mode TEXT,
      context_window INTEGER,
      input_per_million REAL,
      cache_write_per_million REAL,
      cache_read_per_million REAL,
      output_per_million REAL,
      reasoning_supported INTEGER,
      capabilities_json TEXT NOT NULL DEFAULT '{}',
      source_url TEXT,
      first_seen_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      raw_hash TEXT,
      lifecycle_status TEXT NOT NULL DEFAULT 'active',
      superseded_by TEXT,
      announced_at TEXT,
      deprecation_date TEXT,
      UNIQUE(source, external_id)
    );

    CREATE TABLE IF NOT EXISTS model_price_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      model_catalog_id INTEGER NOT NULL REFERENCES model_catalog(id) ON DELETE CASCADE,
      captured_at TEXT NOT NULL,
      input_per_million REAL,
      cache_write_per_million REAL,
      cache_read_per_million REAL,
      output_per_million REAL,
      reason TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS harness_models (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
      quota_pool_id INTEGER REFERENCES quota_pools(id) ON DELETE SET NULL,
      model_key TEXT NOT NULL,
      model_display_name TEXT NOT NULL,
      reasoning TEXT,
      speed TEXT,
      entitlement_status TEXT NOT NULL DEFAULT 'candidate',
      source_url TEXT,
      source_evidence TEXT,
      last_verified TEXT,
      lifecycle_status TEXT NOT NULL DEFAULT 'active',
      superseded_by TEXT,
      UNIQUE(subscription_id, model_key, reasoning, speed)
    );

    CREATE TABLE IF NOT EXISTS lane_metrics (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
      quota_pool_id INTEGER REFERENCES quota_pools(id) ON DELETE SET NULL,
      model_key TEXT NOT NULL,
      task_class TEXT NOT NULL,
      sample_size INTEGER,
      attempts INTEGER,
      completed INTEGER,
      first_pass_rate REAL,
      visible_quota_delta_pct REAL,
      weekly_quota_delta_pct REAL,
      completed_per_visible_1pct REAL,
      visible_100point_extrapolation REAL,
      tokens_per_completed REAL,
      steps_per_completed REAL,
      seconds_per_completed REAL,
      evidence_status TEXT NOT NULL,
      observed_at TEXT NOT NULL,
      source_label TEXT,
      notes TEXT,
      UNIQUE(subscription_id, model_key, task_class, observed_at)
    );

    CREATE TABLE IF NOT EXISTS telemetry_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      imported_at TEXT NOT NULL,
      source TEXT NOT NULL,
      file_name TEXT,
      row_count INTEGER NOT NULL,
      schema_version TEXT,
      notes TEXT
    );

    CREATE TABLE IF NOT EXISTS telemetry_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id INTEGER NOT NULL REFERENCES telemetry_runs(id) ON DELETE CASCADE,
      task_id TEXT NOT NULL,
      matched_pair_id TEXT,
      task_class TEXT,
      model_id TEXT NOT NULL,
      reasoning TEXT,
      quota_pool TEXT,
      five_hour_before_pct REAL,
      five_hour_after_pct REAL,
      weekly_before_pct REAL,
      weekly_after_pct REAL,
      completed INTEGER NOT NULL,
      first_pass_success INTEGER NOT NULL,
      attempt_number INTEGER,
      tool_calls INTEGER,
      agent_steps INTEGER,
      input_tokens INTEGER,
      cache_tokens INTEGER,
      output_tokens INTEGER,
      wall_clock_seconds REAL,
      telemetry_fidelity TEXT NOT NULL DEFAULT 'unknown',
      subagent_id TEXT,
      description TEXT,
      raw_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS source_watch (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_key TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL,
      url TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'html',
      parser TEXT NOT NULL DEFAULT 'hash',
      enabled INTEGER NOT NULL DEFAULT 1,
      last_checked TEXT,
      last_status INTEGER,
      last_hash TEXT,
      last_change_at TEXT,
      last_excerpt TEXT
    );

    CREATE TABLE IF NOT EXISTS availability_overrides (
      scope TEXT NOT NULL CHECK(scope IN ('provider','model')),
      key TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL,
      reason TEXT,
      PRIMARY KEY(scope,key)
    );

    CREATE TABLE IF NOT EXISTS change_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_watch_id INTEGER REFERENCES source_watch(id) ON DELETE CASCADE,
      detected_at TEXT NOT NULL,
      event_type TEXT NOT NULL,
      title TEXT NOT NULL,
      detail TEXT,
      old_value TEXT,
      new_value TEXT,
      severity TEXT NOT NULL DEFAULT 'info',
      acknowledged INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sync_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL,
      detail TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_catalog_provider ON model_catalog(provider);
    CREATE INDEX IF NOT EXISTS idx_catalog_last_seen ON model_catalog(last_seen_at);
    CREATE INDEX IF NOT EXISTS idx_changes_ack ON change_events(acknowledged, detected_at);
    CREATE INDEX IF NOT EXISTS idx_telemetry_model ON telemetry_attempts(model_id, task_class);
    """
    with connect() as conn:
        conn.executescript(schema)
        # In-place migrations for upgrades from v0.1.x.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_watch)").fetchall()}
        if "last_error" not in columns:
            conn.execute("ALTER TABLE source_watch ADD COLUMN last_error TEXT")
        if "consecutive_failures" not in columns:
            conn.execute("ALTER TABLE source_watch ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0")
        telemetry_columns = {row["name"] for row in conn.execute("PRAGMA table_info(telemetry_attempts)").fetchall()}
        if "telemetry_fidelity" not in telemetry_columns:
            conn.execute("ALTER TABLE telemetry_attempts ADD COLUMN telemetry_fidelity TEXT NOT NULL DEFAULT 'unknown'")
        if "subagent_id" not in telemetry_columns:
            conn.execute("ALTER TABLE telemetry_attempts ADD COLUMN subagent_id TEXT")
        catalog_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_catalog)").fetchall()}
        for name, definition in {
            "lifecycle_status": "TEXT NOT NULL DEFAULT 'active'",
            "superseded_by": "TEXT",
            "announced_at": "TEXT",
            "deprecation_date": "TEXT",
        }.items():
            if name not in catalog_columns:
                conn.execute(f"ALTER TABLE model_catalog ADD COLUMN {name} {definition}")
        harness_columns = {row["name"] for row in conn.execute("PRAGMA table_info(harness_models)").fetchall()}
        for name, definition in {
            "lifecycle_status": "TEXT NOT NULL DEFAULT 'active'",
            "superseded_by": "TEXT",
        }.items():
            if name not in harness_columns:
                conn.execute(f"ALTER TABLE harness_models ADD COLUMN {name} {definition}")
        conn.execute(
            "UPDATE change_events SET acknowledged=1 "
            "WHERE event_type='source_changed' AND acknowledged=0"
        )


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def set_setting(key: str, value: Any) -> None:
    payload = json.dumps(value)
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, payload, now),
        )


def get_setting(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default
