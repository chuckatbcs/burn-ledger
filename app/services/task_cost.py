from __future__ import annotations

from typing import Any

TASK_PROFILES: dict[str, dict[str, Any]] = {
    "micro": {
        "label": "Micro",
        "billable_tokens": 1_000,
        "description": "~1k billable tokens",
    },
    "standard": {
        "label": "Standard engineering",
        "billable_tokens": 10_000,
        "description": "~10k billable tokens",
    },
    "long_horizon": {
        "label": "Long-horizon",
        "billable_tokens": 50_000,
        "description": "~50k billable tokens",
    },
    "massive_context": {
        "label": "Massive context",
        "billable_tokens": 300_000,
        "description": "~300k billable tokens · long-context band",
    },
}

DEFAULT_PROFILE = "standard"
DEFAULT_MIX = {"input": 0.70, "cache_read": 0.20, "output": 0.10}
LONG_CONTEXT_THRESHOLD = 272_000
DEFAULT_LONG_CONTEXT_MULTIPLIERS = {"input": 1.0, "cache_read": 1.0, "output": 1.0}


def normalize_mix(mix: dict[str, float] | None) -> dict[str, float]:
    raw = mix or DEFAULT_MIX
    out = {k: float(raw.get(k, DEFAULT_MIX[k])) for k in DEFAULT_MIX}
    total = sum(out.values())
    if total <= 0:
        return dict(DEFAULT_MIX)
    return {k: v / total for k, v in out.items()}


def profile_meta(profile: str, mix: dict[str, float] | None = None) -> dict[str, Any]:
    key = profile if profile in TASK_PROFILES else DEFAULT_PROFILE
    meta = dict(TASK_PROFILES[key])
    meta["key"] = key
    meta["mix"] = normalize_mix(mix)
    return meta


def calculate_task_cost(row: dict[str, Any], profile: str, mix: dict[str, float] | None = None) -> dict[str, Any]:
    """Return a comparable API-equivalent reference cost for one task profile.

    The profile fixes total billable token volume and the configured input/cache-read/output
    mix. If a cache-read rate is not published, cache-read tokens conservatively fall back
    to the normal input rate; that fact is exposed in task_cost_status.
    """
    meta = profile_meta(profile, mix)
    input_rate = row.get("input_per_million")
    output_rate = row.get("output_per_million")
    cache_rate = row.get("cache_read_per_million")

    if input_rate is None or output_rate is None:
        return {
            "task_cost_per_task": None,
            "task_cost_status": "unavailable",
            "task_cost_profile": meta["key"],
            "task_cost_tokens": meta["billable_tokens"],
            "task_cost_mix": meta["mix"],
        }

    cache_fallback = cache_rate is None
    if cache_fallback:
        cache_rate = input_rate

    tokens = float(meta["billable_tokens"])
    parts = {
        "input": tokens * meta["mix"]["input"],
        "cache_read": tokens * meta["mix"]["cache_read"],
        "output": tokens * meta["mix"]["output"],
    }
    long_context_threshold = float(row.get("long_context_threshold") or LONG_CONTEXT_THRESHOLD)
    long_context = tokens > long_context_threshold
    explicit_band = row.get("long_context_pricing") if isinstance(row.get("long_context_pricing"), dict) else None
    explicit_multipliers = row.get("long_context_multipliers") if isinstance(row.get("long_context_multipliers"), dict) else None
    applied_multipliers = dict(DEFAULT_LONG_CONTEXT_MULTIPLIERS)
    pricing_basis = "standard_rates"
    if long_context and explicit_band:
        input_rate = explicit_band.get("input_per_million", input_rate)
        cache_rate = explicit_band.get("cache_read_per_million", cache_rate)
        output_rate = explicit_band.get("output_per_million", output_rate)
        pricing_basis = "provider_long_context_band"
    elif long_context and explicit_multipliers:
        applied_multipliers = {
            key: float(explicit_multipliers.get(key, 1.0))
            for key in ("input", "cache_read", "output")
        }
        parts = {key: value * applied_multipliers[key] for key, value in parts.items()}
        pricing_basis = "provider_long_context_multiplier"
    cost = (
        parts["input"] * float(input_rate)
        + parts["cache_read"] * float(cache_rate)
        + parts["output"] * float(output_rate)
    ) / 1_000_000.0

    return {
        "task_cost_per_task": cost,
        "task_cost_status": "cache_at_input_rate" if cache_fallback else "priced",
        "task_cost_pricing_basis": pricing_basis,
        "task_cost_profile": meta["key"],
        "task_cost_tokens": int(tokens),
        "task_cost_mix": meta["mix"],
        "task_cost_band": "long_context" if long_context else "short_context",
        "task_cost_band_threshold": long_context_threshold,
        "task_cost_band_multipliers": applied_multipliers,
    }


def decorate_task_cost(rows: list[dict[str, Any]], profile: str, mix: dict[str, float] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        row.update(calculate_task_cost(row, profile, mix))
        result.append(row)
    return result
