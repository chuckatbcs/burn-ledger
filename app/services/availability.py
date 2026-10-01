from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.db import connect, query, utcnow


def infer_model_provider(model_key: str | None, display_name: str | None = None, fallback: str | None = None) -> str:
    text = f"{model_key or ''} {display_name or ''}".lower()
    if "claude" in text:
        return "Anthropic"
    if "gemini" in text:
        return "Google"
    if "grok" in text:
        return "xAI"
    if "composer" in text:
        return "Cursor"
    if any(token in text for token in ("gpt-", "gpt_", "openai", "o1-", "o3-", "o4-")):
        return "OpenAI"
    return (fallback or "Unknown").strip() or "Unknown"


def _normalized_key(scope: str, key: str) -> str:
    return key.strip().lower() if scope == "provider" else key.strip()


def get_overrides() -> dict[str, dict[str, bool]]:
    rows = query("SELECT scope,key,enabled FROM availability_overrides")
    result: dict[str, dict[str, bool]] = {"provider": {}, "model": {}}
    for row in rows:
        scope = row["scope"]
        if scope in result:
            result[scope][row["key"]] = bool(row["enabled"])
    return result


def set_override(scope: str, key: str, enabled: bool) -> dict[str, Any]:
    if scope not in {"provider", "model"}:
        raise ValueError("scope must be provider or model")
    normalized = _normalized_key(scope, key)
    now = utcnow()
    with connect() as conn:
        conn.execute(
            """INSERT INTO availability_overrides(scope,key,enabled,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(scope,key) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at""",
            (scope, normalized, 1 if enabled else 0, now),
        )
    return {"scope": scope, "key": normalized, "enabled": enabled, "updated_at": now}


def availability_for(model_key: str, provider: str, overrides: dict[str, dict[str, bool]] | None = None) -> dict[str, Any]:
    overrides = overrides or get_overrides()
    provider_key = provider.strip().lower()
    provider_enabled = overrides["provider"].get(provider_key, True)
    model_enabled = overrides["model"].get(model_key, True)
    available = provider_enabled and model_enabled
    if not provider_enabled:
        reason = f"{provider} provider disabled"
    elif not model_enabled:
        reason = "Model disabled"
    else:
        reason = None
    return {
        "available": available,
        "provider_enabled": provider_enabled,
        "model_enabled": model_enabled,
        "availability_reason": reason,
    }


def provider_states() -> list[dict[str, Any]]:
    rows = query(
        """SELECT hm.model_key,hm.model_display_name,s.provider AS plan_provider
           FROM harness_models hm JOIN subscriptions s ON s.id=hm.subscription_id
           WHERE s.enabled=1"""
    )
    providers = sorted({infer_model_provider(r["model_key"], r["model_display_name"], r["plan_provider"]) for r in rows})
    overrides = get_overrides()
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[infer_model_provider(r["model_key"], r["model_display_name"], r["plan_provider"])] += 1
    return [
        {
            "provider": provider,
            "enabled": overrides["provider"].get(provider.lower(), True),
            "model_count": counts[provider],
        }
        for provider in providers
    ]


def decorate_model_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overrides = get_overrides()
    result = []
    for row in rows:
        item = dict(row)
        provider = infer_model_provider(
            item.get("external_id"), item.get("display_name"), item.get("provider") or item.get("plan_provider")
        )
        item["provider"] = provider
        item.update(availability_for(item.get("external_id") or "", provider, overrides))
        result.append(item)
    return result


def _pick_quota(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [c for c in candidates if c["available"] and c.get("completed_per_visible_1pct") is not None]
    if not usable:
        return None
    return max(
        usable,
        key=lambda c: (
            float(c.get("completed_per_visible_1pct") or 0),
            float(c.get("first_pass_rate") or 0),
            -float(c.get("seconds_per_completed") or 10**12),
        ),
    )


def _pick_time(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [c for c in candidates if c["available"] and c.get("seconds_per_completed") is not None]
    if not usable:
        return None
    return min(
        usable,
        key=lambda c: (
            float(c.get("seconds_per_completed") or 10**12),
            -float(c.get("first_pass_rate") or 0),
            float(c.get("attempts") or 0) / max(1.0, float(c.get("completed") or 1)),
        ),
    )


def _brief_candidate(c: dict[str, Any] | None) -> dict[str, Any] | None:
    if not c:
        return None
    return {
        "model_key": c["model_key"],
        "model_display_name": c.get("model_display_name") or c["model_key"],
        "provider": c["model_provider"],
        "completed_per_visible_1pct": c.get("completed_per_visible_1pct"),
        "first_pass_rate": c.get("first_pass_rate"),
        "seconds_per_completed": c.get("seconds_per_completed"),
        "tokens_per_completed": c.get("tokens_per_completed"),
        "evidence_status": c.get("evidence_status"),
    }


def current_recommendations() -> list[dict[str, Any]]:
    rows = query(
        """SELECT lm.*,s.provider AS plan_provider,s.plan_name,qp.name AS pool_name,
                  COALESCE(hm.model_display_name,lm.model_key) AS model_display_name
           FROM lane_metrics lm
           JOIN subscriptions s ON s.id=lm.subscription_id AND s.enabled=1
           LEFT JOIN quota_pools qp ON qp.id=lm.quota_pool_id
           JOIN harness_models hm ON hm.subscription_id=lm.subscription_id AND hm.model_key=lm.model_key
           WHERE lm.observed_at=(
             SELECT MAX(x.observed_at) FROM lane_metrics x
             WHERE x.subscription_id=lm.subscription_id AND x.model_key=lm.model_key AND x.task_class=lm.task_class
           )
           ORDER BY qp.name,lm.task_class,lm.model_key"""
    )
    overrides = get_overrides()
    decorated = []
    for row in rows:
        item = dict(row)
        provider = infer_model_provider(item["model_key"], item.get("model_display_name"), item.get("plan_provider"))
        item["model_provider"] = provider
        item.update(availability_for(item["model_key"], provider, overrides))
        decorated.append(item)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in decorated:
        grouped[(row.get("pool_name") or "Unpooled", row["task_class"])].append(row)

    result = []
    for (pool_name, task_class), candidates in grouped.items():
        baseline_candidates = [dict(c, available=True) for c in candidates]
        baseline_quota = _pick_quota(baseline_candidates)
        baseline_time = _pick_time(baseline_candidates)
        quota = _pick_quota(candidates)
        time = _pick_time(candidates)
        changed = (
            (baseline_quota or {}).get("model_key") != (quota or {}).get("model_key")
            or (baseline_time or {}).get("model_key") != (time or {}).get("model_key")
        )
        disabled = [
            {
                "model_key": c["model_key"],
                "model_display_name": c.get("model_display_name") or c["model_key"],
                "provider": c["model_provider"],
                "reason": c.get("availability_reason"),
            }
            for c in candidates if not c["available"]
        ]
        result.append({
            "pool_name": pool_name,
            "task_class": task_class,
            "tier": "Tier 2" if task_class.startswith("Tier 2") else "Tier 3" if task_class.startswith("Tier 3") else task_class,
            "quota_first": _brief_candidate(quota),
            "time_first": _brief_candidate(time),
            "baseline_quota_first": _brief_candidate(baseline_quota),
            "baseline_time_first": _brief_candidate(baseline_time),
            "changed_by_availability": changed,
            "disabled_candidates": disabled,
            "candidate_count": len(candidates),
            "available_count": sum(1 for c in candidates if c["available"]),
        })
    return result


def decorate_lanes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overrides = get_overrides()
    result = []
    for row in rows:
        item = dict(row)
        provider = infer_model_provider(item["model_key"], item.get("model_display_name"), item.get("provider"))
        item["model_provider"] = provider
        item.update(availability_for(item["model_key"], provider, overrides))
        result.append(item)
    return result
