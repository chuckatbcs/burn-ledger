from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from typing import Any

from app.db import connect, get_setting, utcnow


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1","true","yes","y"}


def _num(v: Any, cast=float):
    if v is None or v == "":
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def normalize_row(r: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _num(r.get("input_tokens"), int)
    cache_tokens = _num(r.get("cache_tokens"), int)
    output_tokens = _num(r.get("output_tokens"), int)
    has_quota_observation = any(r.get(key) not in (None, "") for key in (
        "five_hour_before_pct", "five_hour_after_pct", "weekly_before_pct", "weekly_after_pct",
        "five_hour_remaining_before_pct", "five_hour_remaining_after_pct",
        "weekly_remaining_before_pct", "weekly_remaining_after_pct",
    ))
    fidelity = str(r.get("telemetry_fidelity") or "").strip().lower()
    if not fidelity:
        fidelity = "exact_reported" if any(v is not None for v in (input_tokens, cache_tokens, output_tokens)) else "quantized_quota" if has_quota_observation else "unknown"
    return {
        "task_id": r.get("task_id") or r.get("id") or "unknown",
        "matched_pair_id": r.get("matched_pair_id") or None,
        "task_class": r.get("task_class") or "unclassified",
        "model_id": r.get("model_id") or r.get("model") or "unknown",
        "reasoning": r.get("reasoning") or r.get("reasoning_level") or None,
        "quota_pool": r.get("quota_pool") or None,
        "five_hour_before_pct": _num(r.get("five_hour_before_pct") or r.get("five_hour_remaining_before_pct")),
        "five_hour_after_pct": _num(r.get("five_hour_after_pct") or r.get("five_hour_remaining_after_pct")),
        "weekly_before_pct": _num(r.get("weekly_before_pct") or r.get("weekly_remaining_before_pct")),
        "weekly_after_pct": _num(r.get("weekly_after_pct") or r.get("weekly_remaining_after_pct")),
        "completed": _bool(r.get("completed", True)),
        "first_pass_success": _bool(r.get("first_pass_success", r.get("first_pass", True))),
        "attempt_number": _num(r.get("attempt_number"), int) or 1,
        "tool_calls": _num(r.get("tool_calls"), int),
        "agent_steps": _num(r.get("agent_steps"), int),
        "input_tokens": input_tokens,
        "cache_tokens": cache_tokens,
        "output_tokens": output_tokens,
        "wall_clock_seconds": _num(r.get("wall_clock_seconds")),
        "telemetry_fidelity": fidelity,
        "subagent_id": r.get("subagent_id") or r.get("agent_id") or r.get("agent") or None,
        "description": r.get("sanitized_description") or r.get("description") or None,
    }


def parse_bytes(data: bytes, filename: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".jsonl"):
        return [normalize_row(json.loads(line)) for line in text.splitlines() if line.strip()]
    reader = csv.DictReader(io.StringIO(text))
    return [normalize_row(dict(row)) for row in reader]


def _pool_name(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.lower()
    if "gemini" in value:
        return "Gemini Models"
    if "claude" in value or "gpt" in value:
        return "Claude & GPT Models"
    return raw


def import_telemetry(data: bytes, filename: str, source: str = "Antigravity") -> dict[str, Any]:
    rows = parse_bytes(data, filename)
    redact = bool(get_setting("telemetry_redact_descriptions", True))
    now = utcnow()
    with connect() as conn:
        run_id = conn.execute(
            "INSERT INTO telemetry_runs(imported_at,source,file_name,row_count,schema_version,notes) VALUES(?,?,?,?,?,?)",
            (now,source,filename,len(rows),"normalized-v1","Descriptions redacted" if redact else "Descriptions retained"),
        ).lastrowid
        for r in rows:
            description = None if redact else r["description"]
            conn.execute(
                """INSERT INTO telemetry_attempts(run_id,task_id,matched_pair_id,task_class,model_id,reasoning,quota_pool,five_hour_before_pct,five_hour_after_pct,weekly_before_pct,weekly_after_pct,completed,first_pass_success,attempt_number,tool_calls,agent_steps,input_tokens,cache_tokens,output_tokens,wall_clock_seconds,telemetry_fidelity,subagent_id,description,raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id,r["task_id"],r["matched_pair_id"],r["task_class"],r["model_id"],r["reasoning"],r["quota_pool"],r["five_hour_before_pct"],r["five_hour_after_pct"],r["weekly_before_pct"],r["weekly_after_pct"],int(r["completed"]),int(r["first_pass_success"]),r["attempt_number"],r["tool_calls"],r["agent_steps"],r["input_tokens"],r["cache_tokens"],r["output_tokens"],r["wall_clock_seconds"],r["telemetry_fidelity"],r["subagent_id"],description,json.dumps(r,sort_keys=True)),
            )
    computed = compute_metrics(rows, source_label=f"import:{filename}")
    return {"run_id": run_id, "rows": len(rows), "metrics": computed}


def compute_metrics(rows: list[dict[str, Any]], source_label: str) -> list[dict[str, Any]]:
    lanes: dict[tuple[str,str,str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        lanes[(r.get("quota_pool") or "unknown", r["task_class"], r["model_id"])].append(r)

    out: list[dict[str, Any]] = []
    observed = utcnow()
    with connect() as conn:
        subs = conn.execute("SELECT id, plan_name, provider FROM subscriptions").fetchall()
        if not subs:
            return out
        default_sub = next((s for s in subs if "Antigravity" in s["plan_name"]), subs[0])
        all_pools = conn.execute("SELECT id, subscription_id, name FROM quota_pools").fetchall()
        pools_by_sub = defaultdict(dict)
        for p in all_pools:
            pools_by_sub[p["subscription_id"]][p["name"]] = p["id"]

        for (pool_raw, task_class, model_id), attempts in lanes.items():
            task_key = "matched_pair_id" if any(a.get("matched_pair_id") for a in attempts) else "task_id"
            tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for a in attempts:
                tasks[str(a.get(task_key) or a["task_id"])].append(a)
            completed = sum(any(a["completed"] for a in aa) for aa in tasks.values())
            first_pass = sum(any(a["attempt_number"] == 1 and a["completed"] for a in aa) for aa in tasks.values())
            delta5 = sum(max(0.0, (a["five_hour_before_pct"] or 0) - (a["five_hour_after_pct"] or 0)) for a in attempts)
            deltaw = sum(max(0.0, (a["weekly_before_pct"] or 0) - (a["weekly_after_pct"] or 0)) for a in attempts)
            total_inout = sum((a["input_tokens"] or 0) + (a["output_tokens"] or 0) for a in attempts)
            total_steps = sum(a["agent_steps"] or 0 for a in attempts)
            total_seconds = sum(a["wall_clock_seconds"] or 0 for a in attempts)
            n = len(tasks)
            # Use 5h delta if observed, otherwise fall back to weekly delta
            effective_delta = delta5 if delta5 > 0 else (deltaw if deltaw > 0 else None)
            per1 = completed / effective_delta if effective_delta else None
            ext = per1 * 100 if per1 is not None else None

            # Resolve subscription dynamically
            target_sub = default_sub
            pool_canonical = _pool_name(pool_raw)
            raw_text = f"{pool_raw or ''} {model_id} {task_class}".lower()
            if "cursor" in raw_text or "composer" in raw_text:
                target_sub = next((s for s in subs if "Cursor" in s["plan_name"]), default_sub)
            elif "codex" in raw_text or "plus" in raw_text:
                target_sub = next((s for s in subs if "Codex" in s["plan_name"] or "ChatGPT" in s["plan_name"]), default_sub)

            metric = {
                "quota_pool": pool_canonical,
                "task_class": task_class,
                "model_id": model_id,
                "sample_size": n,
                "attempts": len(attempts),
                "completed": completed,
                "first_pass_rate": first_pass / n if n else None,
                "visible_quota_delta_pct": delta5,
                "weekly_quota_delta_pct": deltaw,
                "completed_per_visible_1pct": per1,
                "visible_100point_extrapolation": ext,
                "tokens_per_completed": total_inout / completed if completed else None,
                "steps_per_completed": total_steps / completed if completed else None,
                "seconds_per_completed": total_seconds / completed if completed else None,
            }
            pool_id = pools_by_sub[target_sub["id"]].get(metric["quota_pool"] or "")
            conn.execute(
                """INSERT INTO lane_metrics(subscription_id,quota_pool_id,model_key,task_class,sample_size,attempts,completed,first_pass_rate,visible_quota_delta_pct,weekly_quota_delta_pct,completed_per_visible_1pct,visible_100point_extrapolation,tokens_per_completed,steps_per_completed,seconds_per_completed,evidence_status,observed_at,source_label,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (target_sub["id"],pool_id,model_id,task_class,n,len(attempts),completed,metric["first_pass_rate"],delta5,deltaw,per1,ext,metric["tokens_per_completed"],metric["steps_per_completed"],metric["seconds_per_completed"],"imported_measured_quantized",observed,source_label,"Computed from imported attempts. Visible quota percentages may be quantized."),
            )
            out.append(metric)
    return out
