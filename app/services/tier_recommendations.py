from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.db import get_setting, query
from app.services.availability import availability_for, infer_model_provider
from app.services.enrichment import enrich_plan_rows
from app.services.task_cost import calculate_task_cost


TIER_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "tier1",
        "tier": 1,
        "label": "Tier 1 · Light / short",
        "short_label": "Light / short",
        "profile": "micro",
        "description": "Quick answers, extraction, syntax fixes, small edits and low-risk one-file work.",
        "examples": ["small code fix", "lint / syntax", "summarize / extract", "short Q&A"],
    },
    {
        "key": "tier2",
        "tier": 2,
        "label": "Tier 2 · Standard engineering",
        "short_label": "Standard engineering",
        "profile": "standard",
        "description": "Normal coding work: tests, focused implementation, targeted refactors and routine debugging.",
        "examples": ["unit tests", "single-feature implementation", "targeted refactor", "stack-trace debugging"],
    },
    {
        "key": "tier3",
        "tier": 3,
        "label": "Tier 3 · Deep / multi-file",
        "short_label": "Deep / multi-file",
        "profile": "long_horizon",
        "description": "Difficult multi-file engineering where reasoning depth, repair rate and context handling matter.",
        "examples": ["multi-file feature", "difficult bug", "integration work", "large refactor"],
    },
    {
        "key": "tier4",
        "tier": 4,
        "label": "Tier 4 · Heavy agentic / long-horizon",
        "short_label": "Heavy agentic",
        "profile": "massive_context",
        "description": "Architecture, repo-scale changes, prolonged autonomous work and high-consequence agentic tasks.",
        "examples": ["repo-scale repair", "architecture change", "long autonomous run", "large context synthesis"],
    },
]


# Cost sorts candidates only after they pass a workload-suitability gate.
_FIT_RULES: list[tuple[re.Pattern[str], dict[int, int], str]] = [
    (re.compile(r"\bluna\b", re.I), {1: 3}, "high-volume light-work lane"),
    (re.compile(r"\bcomposer\b", re.I), {1: 3, 2: 3}, "fast coding workhorse"),
    (re.compile(r"gemini.*\bflash\b", re.I), {1: 3, 2: 3, 3: 2}, "efficient wide-context model"),
    (re.compile(r"\bterra\b", re.I), {1: 2, 2: 3}, "efficient standard-engineering lane"),
    (re.compile(r"\bgrok\b", re.I), {2: 1, 3: 3}, "deep coding / agentic lane"),
    (re.compile(r"claude.*\bsonnet\b", re.I), {2: 2, 3: 3}, "deep coding model"),
    (re.compile(r"gemini.*\bpro\b", re.I), {3: 3, 4: 2}, "high-reasoning / long-context lane"),
    (re.compile(r"\bsol\b", re.I), {3: 3}, "general high-speed reasoning lane"),
    (re.compile(r"claude.*\bopus\b", re.I), {3: 2, 4: 3}, "premium agentic coding lane"),
    (re.compile(r"claude.*\bfable\b", re.I), {3: 2, 4: 3}, "premium long-horizon lane"),
    (re.compile(r"\bastra\b", re.I), {3: 2, 4: 3}, "flagship deliberative reasoning lane"),
    (re.compile(r"gpt[-\s]?oss\s*120b", re.I), {1: 2, 2: 2}, "general open-weight work lane"),
]

_EFFORT_WORDS = {"low", "medium", "high", "xhigh", "max", "thinking", "fast", "standard", "default", "mode"}
_WEEKS_PER_MONTH = 52.0 / 12.0


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _parse_version(name: str | None) -> tuple[int, ...]:
    if not name:
        return (0, 0, 0, 0)
    matches = re.findall(r"\b\d+(?:[\.-]\d+)*\b", name)
    if matches:
        v_str = matches[-1].replace("-", ".")
        try:
            parts = [int(x) for x in v_str.split(".") if x.isdigit()]
            while len(parts) < 4:
                parts.append(0)
            return tuple(parts[:4])
        except ValueError:
            pass
    return (0, 0, 0, 0)


def _canonical_family(model_key: str | None, display_name: str | None) -> str:
    text = (display_name or model_key or "").lower()
    if "grok" in text:
        return "xai-grok"
    if "opus" in text:
        return "claude-opus"
    if "sonnet" in text:
        return "claude-sonnet"
    if "fable" in text:
        return "claude-fable"
    if "gemini" in text and "flash" in text:
        return "gemini-flash"
    if "gemini" in text and "pro" in text:
        return "gemini-pro"
    if "composer" in text:
        return "cursor-composer"
    if "astra" in text:
        return "gpt-astra"
    if "sol" in text:
        return "gpt-sol"
    if "terra" in text:
        return "gpt-terra"
    if "luna" in text:
        return "gpt-luna"
    toks = [t for t in _tokens(display_name or model_key) if t not in _EFFORT_WORDS]
    return "-".join(toks)


def _fit_for(row: dict[str, Any], tier: int) -> tuple[int, str, str]:
    text = f"{row.get('display_name') or ''} {row.get('external_id') or ''}"
    for regex, tier_scores, reason in _FIT_RULES:
        if regex.search(text):
            score = int(tier_scores.get(tier, 0))
            return score, reason, "curated"

    context = int(row.get("context_window") or 0)
    reasoning = bool(row.get("reasoning_supported"))
    if tier == 1 and context:
        return 1, "new catalog model; light-work fit inferred from published metadata", "inferred"
    if tier == 2 and (reasoning or context >= 128_000):
        return 1, "new catalog model; standard-work fit inferred from published metadata", "inferred"
    if tier == 3 and reasoning and context >= 200_000:
        return 1, "new catalog model; deep-work fit inferred from reasoning/context metadata", "inferred"
    return 0, "no established fit evidence for this tier", "unrated"


def _plan_rows() -> list[dict[str, Any]]:
    rows = query(
        """
        SELECT
          hm.id AS row_id,
          hm.model_key AS external_id,
          CASE
            WHEN LOWER(hm.model_key) LIKE '%claude%' THEN 'Anthropic'
            WHEN LOWER(hm.model_key) LIKE '%gemini%' THEN 'Google'
            WHEN LOWER(hm.model_key) LIKE '%grok%' THEN 'xAI'
            WHEN LOWER(hm.model_key) LIKE '%composer%' THEN 'Cursor'
            WHEN LOWER(hm.model_key) LIKE '%gpt-%' OR LOWER(hm.model_key) LIKE '%gpt_%' OR LOWER(hm.model_key) LIKE '%openai%' THEN 'OpenAI'
            ELSE s.provider
          END AS provider,
          s.provider AS plan_provider,
          s.id AS subscription_id,
          s.monthly_price AS monthly_price,
          s.currency AS currency,
          hm.model_display_name AS display_name,
          NULL AS context_window,
          NULL AS input_per_million,
          NULL AS cache_write_per_million,
          NULL AS cache_read_per_million,
          NULL AS output_per_million,
          NULL AS reasoning_supported,
          hm.source_url AS source_url,
          hm.last_verified AS last_seen_at,
          hm.entitlement_status AS entitlement_status,
          hm.lifecycle_status AS lifecycle_status,
          hm.superseded_by AS superseded_by,
          s.plan_name AS plan_name,
          qp.name AS pool_name
        FROM harness_models hm
        JOIN subscriptions s ON s.id=hm.subscription_id AND s.enabled=1
        LEFT JOIN quota_pools qp ON qp.id=hm.quota_pool_id
        """
    )
    return enrich_plan_rows(rows)


def _latest_metrics() -> dict[tuple[str, str], dict[str, Any]]:
    rows = query(
        """
        SELECT lm.*, s.plan_name, s.monthly_price, s.currency, qp.name AS pool_name
        FROM lane_metrics lm
        JOIN subscriptions s ON s.id=lm.subscription_id AND s.enabled=1
        LEFT JOIN quota_pools qp ON qp.id=lm.quota_pool_id
        WHERE lm.observed_at=(
          SELECT MAX(x.observed_at) FROM lane_metrics x
          WHERE x.subscription_id=lm.subscription_id AND x.model_key=lm.model_key AND x.task_class=lm.task_class
        )
        """
    )
    return {(r["model_key"], r["task_class"]): r for r in rows}


def _metric_for_tier(metrics: dict[tuple[str, str], dict[str, Any]], model_key: str, tier: int) -> dict[str, Any] | None:
    prefix = f"Tier {tier}:"
    matches = [r for (key, task_class), r in metrics.items() if key == model_key and task_class.startswith(prefix)]
    if not matches:
        return None
    return max(matches, key=lambda r: str(r.get("observed_at") or ""))


def _subscription_economics(metric: dict[str, Any] | None, monthly_price: float | int | None) -> dict[str, Any]:
    if not metric or not metric.get("completed"):
        return {
            "subscription_cost_per_completed_task": None,
            "weekly_burn_pct_per_completed": None,
            "five_hour_burn_pct_per_completed": None,
            "monthly_completed_capacity_estimate": None,
            "subscription_cost_status": "unmeasured",
        }

    completed = max(1.0, float(metric.get("completed") or 0))
    q5 = float(metric.get("visible_quota_delta_pct") or 0)
    qw = float(metric.get("weekly_quota_delta_pct") or 0)
    burn_5h = q5 / completed if q5 > 0 else None
    burn_weekly = qw / completed if qw > 0 else None
    monthly_capacity = None
    effective_cost = None
    if burn_weekly and burn_weekly > 0:
        weekly_capacity = 100.0 / burn_weekly
        monthly_capacity = weekly_capacity * _WEEKS_PER_MONTH
        if monthly_price is not None:
            effective_cost = float(monthly_price) / monthly_capacity

    return {
        "subscription_cost_per_completed_task": effective_cost,
        "weekly_burn_pct_per_completed": burn_weekly,
        "five_hour_burn_pct_per_completed": burn_5h,
        "tasks_per_weekly_quota": (100.0 / burn_weekly) if burn_weekly and burn_weekly > 0 else None,
        "monthly_completed_capacity_estimate": monthly_capacity,
        "subscription_cost_status": "measured_weekly" if effective_cost is not None else "burn_only" if burn_5h is not None else "unmeasured",
    }


def _route_candidate(
    row: dict[str, Any],
    tier_def: dict[str, Any],
    metrics: dict[tuple[str, str], dict[str, Any]],
    mix: dict[str, float],
    basis: str,
) -> dict[str, Any] | None:
    if row.get("lifecycle_status") in {"superseded", "deprecated"}:
        return None
    metric = _metric_for_tier(metrics, row.get("external_id") or "", tier_def["tier"])
    fit_score, fit_reason, fit_basis = _fit_for(row, tier_def["tier"])

    # Direct matched completion evidence is stronger than a curated prior. If a model
    # actually completed this tier in the user's telemetry, it is recommendation-grade
    # for that tier even when the static family map was conservative.
    if metric and metric.get("completed"):
        if fit_score < 2:
            fit_score = 2
            fit_reason = "measured successful completion on this workload tier"
            fit_basis = "measured"
    elif fit_score < 2:
        return None

    provider = infer_model_provider(row.get("external_id"), row.get("display_name"), row.get("provider") or row.get("plan_provider"))
    availability = availability_for(row.get("external_id") or "", provider)

    # API-equivalent completed-task economics.
    cost = calculate_task_cost(row, tier_def["profile"], mix)
    api_completed_cost = None
    api_evidence = "estimated"
    if cost.get("task_cost_per_task") is not None:
        api_completed_cost = float(cost["task_cost_per_task"])
        if metric:
            tokens_per_completed = metric.get("tokens_per_completed")
            profile_tokens = float(cost.get("task_cost_tokens") or 0)
            if tokens_per_completed is not None and profile_tokens > 0:
                api_completed_cost *= float(tokens_per_completed) / profile_tokens
                api_evidence = "measured"
            elif metric.get("attempts") is not None and metric.get("completed"):
                api_completed_cost *= float(metric["attempts"]) / max(1.0, float(metric["completed"]))
                api_evidence = "retry-adjusted"

    sub = _subscription_economics(metric, row.get("monthly_price"))
    sample_size = int(metric.get("sample_size") or 0) if metric else 0
    completed = int(metric.get("completed") or 0) if metric else 0
    success_rate = (completed / sample_size) if sample_size else None
    if metric and sample_size:
        confidence = "high" if sample_size >= 30 else "medium" if sample_size >= 10 else "low"
        quality_evidence = "measured"
    elif metric:
        confidence = "unresolved"
        quality_evidence = "partial"
    else:
        confidence = "estimated"
        quality_evidence = "estimated"
    if basis == "quota":
        rank_value = sub["weekly_burn_pct_per_completed"]
        if rank_value is not None:
            selected_evidence = "measured_subscription"
            ranking_bucket = 0
        elif api_completed_cost is not None:
            # Quota burn is not derivable from API prices. Keep the lane visible,
            # but put it after measured quota lanes and label it as a proxy.
            rank_value = api_completed_cost
            selected_evidence = "api_proxy"
            ranking_bucket = 1
        else:
            return None
    else:
        rank_value = api_completed_cost
        if rank_value is None:
            return None
        selected_evidence = api_evidence
        ranking_bucket = 0

    return {
        "family_key": _canonical_family(row.get("external_id"), row.get("display_name")),
        "model_key": row.get("external_id"),
        "model_display_name": row.get("display_name") or row.get("external_id"),
        "provider": provider,
        "plan_name": row.get("plan_name"),
        "pool_name": row.get("pool_name"),
        "monthly_price": row.get("monthly_price"),
        "currency": row.get("currency") or "USD",
        "context_window": row.get("context_window"),
        "fit_score": fit_score,
        "fit_reason": fit_reason,
        "fit_basis": fit_basis,
        "available": availability["available"],
        "availability_reason": availability.get("availability_reason"),
        "model_enabled": availability["model_enabled"],
        "provider_enabled": availability["provider_enabled"],
        # The legacy field remains the selected ranking value for UI/backward compatibility.
        "cost_per_completed_task": float(rank_value),
        "cost_evidence": selected_evidence,
        "ranking_bucket": ranking_bucket,
        "quality_evidence": quality_evidence,
        "confidence": confidence,
        "sample_size": sample_size or None,
        "completed": completed or None,
        "success_rate": success_rate,
        "api_cost_per_completed_task": api_completed_cost,
        "expected_cost_per_success": api_completed_cost,
        "api_cost_evidence": api_evidence if api_completed_cost is not None else None,
        **sub,
        "reference_task_cost": cost.get("task_cost_per_task"),
        "task_profile": tier_def["profile"],
        "task_tokens": cost.get("task_cost_tokens"),
        "task_cost_status": cost.get("task_cost_status"),
        "first_pass_rate": metric.get("first_pass_rate") if metric else None,
        "seconds_per_completed": metric.get("seconds_per_completed") if metric else None,
        "tokens_per_completed": metric.get("tokens_per_completed") if metric else None,
        "completed_per_visible_1pct": metric.get("completed_per_visible_1pct") if metric else None,
        "evidence_status": metric.get("evidence_status") if metric else row.get("entitlement_status"),
        "entitlement_status": row.get("entitlement_status"),
        "lifecycle_status": row.get("lifecycle_status") or "active",
        "superseded_by": row.get("superseded_by"),
    }


def _route_priority(candidate: dict[str, Any], basis: str) -> tuple[int, float, float, float, int, list[int], str]:
    bucket = int(candidate.get("ranking_bucket") or 0)
    rank = float(candidate.get("cost_per_completed_task") or 1e30)
    api_cost = float(candidate.get("api_cost_per_completed_task") or 1e30)
    weekly_burn = float(candidate.get("weekly_burn_pct_per_completed") or 1e30)
    seconds = float(candidate.get("seconds_per_completed") or 1e30)
    entitlement_rank = {"official": 2, "baseline": 1}.get(candidate.get("entitlement_status"), 0)
    # Primary basis always wins. The opposite economic measure is the first tie-breaker,
    # then measured completion time, so equal-quota models prefer the cheaper API route.
    secondary = api_cost if basis == "quota" else weekly_burn
    v = _parse_version(candidate.get("model_display_name"))
    neg_version = [-x for x in v]
    return (bucket, rank, secondary, seconds, -entitlement_rank, neg_version, str(candidate.get("model_display_name") or ""))


def _dedupe_family(candidates: list[dict[str, Any]], basis: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        grouped[c["family_key"]].append(c)

    out: list[dict[str, Any]] = []
    for _, group in grouped.items():
        available = [c for c in group if c["available"]]
        choice_pool = available or group
        choice = sorted(choice_pool, key=lambda c: _route_priority(c, basis))[0]
        item = dict(choice)
        item["plans"] = sorted({c["plan_name"] for c in group if c.get("plan_name")})
        item["enabled_plans"] = sorted({c["plan_name"] for c in group if c.get("plan_name") and c["available"]})
        item["alternate_routes"] = len(group) - 1
        item["available"] = bool(available)
        if not available:
            item["availability_reason"] = "All entitled routes for this model are disabled"
        out.append(item)
    return out


def tier_recommendations(basis: str = "api") -> dict[str, Any]:
    # v0.8: "subscription" is retained as a legacy alias for quota-first ranking.
    if basis == "subscription":
        basis = "quota"
    if basis not in {"api", "quota"}:
        basis = "api"
    mix = get_setting("catalog_token_mix", {"input": 0.70, "cache_read": 0.20, "output": 0.10})
    rows = _plan_rows()
    metrics = _latest_metrics()
    tiers: list[dict[str, Any]] = []

    all_disabled_models: set[str] = set()
    measured_top_count = 0
    measured_quota_top_count = 0
    quota_fallback_top_count = 0
    total_top_count = 0
    unresolved_fit = 0

    for tier_def in TIER_DEFINITIONS:
        candidates = []
        for row in rows:
            fit_score, _, fit_basis = _fit_for(row, tier_def["tier"])
            if fit_score == 1 and fit_basis == "inferred":
                unresolved_fit += 1
            c = _route_candidate(row, tier_def, metrics, mix, basis)
            if c:
                candidates.append(c)

        deduped = _dedupe_family(candidates, basis)
        baseline = sorted(deduped, key=lambda c: _route_priority(c, basis))[:3]
        enabled = [c for c in deduped if c["available"]]
        ranked = sorted(enabled, key=lambda c: _route_priority(c, basis))[:3]

        baseline_keys = [c["family_key"] for c in baseline]
        ranked_keys = [c["family_key"] for c in ranked]
        changed = baseline_keys != ranked_keys
        for c in deduped:
            if not c["available"]:
                all_disabled_models.add(c["family_key"])
        measured_top_count += sum(1 for c in ranked if c["cost_evidence"] in {"measured", "retry-adjusted", "measured_subscription"})
        measured_quota_top_count += sum(1 for c in ranked if c["cost_evidence"] == "measured_subscription")
        quota_fallback_top_count += sum(1 for c in ranked if c["cost_evidence"] == "api_proxy")
        total_top_count += len(ranked)

        tiers.append({
            **tier_def,
            "top_models": ranked,
            "baseline_top_models": baseline,
            "changed_by_availability": changed,
            "eligible_model_count": len(deduped),
            "available_model_count": len(enabled),
            "missing_rank_slots": max(0, 3 - len(ranked)),
            "missing_measured_slots": sum(1 for c in ranked if c.get("cost_evidence") == "api_proxy") if basis == "quota" else 0,
        })

    providers = query("SELECT COUNT(DISTINCT provider) AS n FROM subscriptions WHERE enabled=1")[0]["n"]
    source_rows = query("SELECT * FROM source_watch")
    source_failures = sum(1 for s in source_rows if int(s.get("enabled") or 0) and int(s.get("last_status") or 0) == 0 and s.get("last_checked"))
    changes = query("SELECT COUNT(*) AS n FROM change_events WHERE acknowledged=0 AND event_type!='source_changed'")[0]["n"]
    total_slots = len(TIER_DEFINITIONS) * 3

    if basis == "quota":
        cost_basis = {
            "key": "quota",
            "label": "Lowest weekly quota burn per completed task",
            "note": "Measured weekly quota burn ranks first. API-equivalent cost fills lanes without quota telemetry as an explicitly labeled proxy, so every workload tier remains actionable without fabricating subscription burn.",
            "weeks_per_month": _WEEKS_PER_MONTH,
        }
    else:
        cost_basis = {
            "key": "api",
            "label": "API-equivalent completed-task cost",
            "mix": mix,
            "note": "Measured lanes incorporate observed success-adjusted token/retry burden. Unmeasured lanes use the tier reference workload and are labeled estimated.",
        }

    return {
        "tiers": tiers,
        "summary": {
            "top_pick_count": total_top_count,
            "measured_top_pick_count": measured_top_count,
            "measured_top_pick_pct": (measured_top_count / total_top_count) if total_top_count else 0,
            "ranked_slot_count": measured_quota_top_count if basis == "quota" else total_top_count,
            "ranked_slot_total": total_slots,
            "ranked_slot_coverage_pct": (measured_quota_top_count if basis == "quota" else total_top_count) / total_slots if total_slots else 0,
            "quota_fallback_slot_count": quota_fallback_top_count,
            "quota_fallback_slot_total": total_slots if basis == "quota" else 0,
            "missing_rank_slot_count": total_slots - total_top_count,
            "disabled_model_family_count": len(all_disabled_models),
            "enabled_subscription_provider_count": providers,
            "source_failure_count": source_failures,
            "unacknowledged_change_count": changes,
            "inferred_models_waiting_for_fit": unresolved_fit,
        },
        "cost_basis": cost_basis,
    }
