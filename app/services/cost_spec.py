"""
Shared cost specification for OmniBurn and Burn Ledger.

THIS FILE IS VENDORED BYTE-IDENTICAL INTO BOTH REPOSITORIES.
  - OmniBurn:    engine/cost_spec.py
  - Burn Ledger: app/services/cost_spec.py
Both test suites run tests/cost_spec_vectors.json against it, so any change
must be copied to both repos and the vectors regenerated.

Definitions (per model, per workload tier):
  pool_allocation_monthly  Subscription price x pool weight (weights in a subscription sum to 1).
  pool_cycles_per_month    Number of full resets of the *binding* window per month.
  cost_per_pool            pool_allocation_monthly / pool_cycles_per_month  ($ per full 100%->0% pool).
  tasks_per_pool           Completed tasks one full pool yields (measured or estimated, with a range).
  sub_cost_per_task        cost_per_pool / tasks_per_pool.
  api_cost_per_task        API-equivalent $ for one completed task (shared token profiles + mix).
  api_value_per_pool       tasks_per_pool x api_cost_per_task (API spend one pool replaces).
  leverage                 api_value_per_pool / cost_per_pool.
Pure standard library; no database access.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable

SPEC_VERSION = "1.0"

WEEKS_PER_MONTH = 52.0 / 12.0
DAYS_PER_MONTH = 365.0 / 12.0
DEFAULT_ACTIVE_5H_WINDOWS_PER_MONTH = 40.0  # 2 windows/day x 20 workdays

# Workload tier -> billable tokens per task (input + cache-read + output).
TIER_PROFILE_TOKENS = {1: 1_000, 2: 10_000, 3: 50_000, 4: 300_000}
TIER_PROFILE_KEYS = {1: "micro", 2: "standard", 3: "long_horizon", 4: "massive_context"}
DEFAULT_MIX = {"input": 0.70, "cache_read": 0.20, "output": 0.10}
LONG_CONTEXT_THRESHOLD = 272_000

# Monthly request-allowance pools (Cursor). Published Pro allowance per pool.
DEFAULT_REQUEST_ALLOWANCE = 500.0
REQUESTS_PER_TASK = {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0}
FAST_REQUEST_MULTIPLIER = 2.0

# Estimation for rolling pools without any measured lane in the same pool:
# assume one pool cycle replaces DEFAULT_PRIOR_LEVERAGE x its own cost in API spend.
DEFAULT_PRIOR_LEVERAGE = 5.0
ESTIMATE_BAND = 0.30  # +/-30% range shown on estimates

WINDOW_MONTHLY = "monthly"
WINDOW_5H_WEEKLY = "rolling_5h_weekly"
WINDOW_5H = "rolling_5h"
WINDOW_DAILY = "daily"
WINDOW_UNMETERED = "unmetered"


def normalize_window_type(raw: str | None) -> str:
    """Map each app's pool reset vocabulary onto the shared window types."""
    text = (raw or "").strip().lower()
    if not text:
        return WINDOW_5H_WEEKLY
    if "unmetered" in text or "local" in text:
        return WINDOW_UNMETERED
    if "month" in text:
        return WINDOW_MONTHLY
    if "daily" in text or "day" in text:
        return WINDOW_DAILY
    if "5h" in text or "rolling" in text:
        # Rolling 5h pools in both apps carry a weekly ceiling ("5h + weekly",
        # "5h + possible weekly", OmniBurn rolling_5h with weekly_pct_remaining).
        if "no weekly" in text or text.endswith("5h only"):
            return WINDOW_5H
        return WINDOW_5H_WEEKLY
    if "week" in text:
        return WINDOW_5H_WEEKLY
    return WINDOW_5H_WEEKLY


def pool_weights(pool_ids: Iterable[Any], explicit: dict[Any, float | None] | None = None) -> dict[Any, float]:
    """Weights for the pools of one subscription. Explicit weights win; the rest split equally."""
    ids = list(dict.fromkeys(pool_ids))
    if not ids:
        return {}
    explicit = {k: float(v) for k, v in (explicit or {}).items() if v is not None and float(v) > 0 and k in ids}
    fixed = sum(explicit.values())
    if fixed >= 1.0 or len(explicit) == len(ids):
        total = fixed or 1.0
        return {i: explicit.get(i, 0.0) / total for i in ids}
    remaining = [i for i in ids if i not in explicit]
    share = (1.0 - fixed) / len(remaining)
    return {i: explicit.get(i, share) for i in ids}


def pool_allocation(monthly_price: float | None, weight: float | None) -> float:
    return max(0.0, float(monthly_price or 0.0)) * (1.0 if weight is None else float(weight))


def cycles_per_month(window_type: str | None, active_5h_windows: float = DEFAULT_ACTIVE_5H_WINDOWS_PER_MONTH) -> float | None:
    wt = normalize_window_type(window_type)
    if wt == WINDOW_MONTHLY:
        return 1.0
    if wt == WINDOW_5H_WEEKLY:
        return WEEKS_PER_MONTH
    if wt == WINDOW_5H:
        return float(active_5h_windows)
    if wt == WINDOW_DAILY:
        return DAYS_PER_MONTH
    return None  # unmetered


def cost_per_pool(allocation: float, window_type: str | None, active_5h_windows: float = DEFAULT_ACTIVE_5H_WINDOWS_PER_MONTH) -> float:
    cycles = cycles_per_month(window_type, active_5h_windows)
    if not cycles or allocation <= 0:
        return 0.0
    return allocation / cycles


def api_cost_per_task(
    input_rate: float | None,
    output_rate: float | None,
    tier: int,
    cache_rate: float | None = None,
    mix: dict[str, float] | None = None,
    tokens_per_completed: float | None = None,
    attempts: float | None = None,
    completed: float | None = None,
    long_context_multipliers: dict[str, float] | None = None,
    long_context_threshold: float | None = None,
) -> dict[str, Any]:
    """API-equivalent cost of one completed task on the shared tier profile."""
    profile_tokens = float(TIER_PROFILE_TOKENS.get(int(tier), TIER_PROFILE_TOKENS[2]))
    if input_rate is None or output_rate is None:
        return {"api_cost_per_task": None, "api_cost_evidence": None, "api_profile_tokens": int(profile_tokens)}
    raw_mix = mix or DEFAULT_MIX
    m = {k: float(raw_mix.get(k, DEFAULT_MIX[k])) for k in DEFAULT_MIX}
    total = sum(m.values()) or 1.0
    m = {k: v / total for k, v in m.items()}
    cache = input_rate if cache_rate is None else cache_rate
    parts = {k: profile_tokens * m[k] for k in m}
    threshold = float(long_context_threshold or LONG_CONTEXT_THRESHOLD)
    if profile_tokens > threshold and long_context_multipliers:
        parts = {k: v * float(long_context_multipliers.get(k, 1.0)) for k, v in parts.items()}
    base = (parts["input"] * float(input_rate) + parts["cache_read"] * float(cache) + parts["output"] * float(output_rate)) / 1_000_000.0

    cost, evidence = base, "estimated"
    if tokens_per_completed:
        cost = base * float(tokens_per_completed) / profile_tokens
        evidence = "measured"
    elif attempts and completed:
        cost = base * float(attempts) / max(1.0, float(completed))
        evidence = "retry-adjusted"
    return {"api_cost_per_task": cost, "api_cost_evidence": evidence, "api_profile_tokens": int(profile_tokens)}


def measured_tasks_per_pool(
    completed: float | None,
    window_type: str | None,
    weekly_delta_pct: float | None = None,
    five_hour_delta_pct: float | None = None,
    granularity_pct: float = 1.0,
) -> dict[str, Any] | None:
    """Tasks per pool from observed burn on the binding window, with a quantization range.

    Visible quota meters move in whole `granularity_pct` steps, so an observed delta d
    means the true burn lies in [d - g/2, d + g/2]. That range is reported as low/high.
    """
    if not completed or completed <= 0:
        return None
    wt = normalize_window_type(window_type)
    if wt == WINDOW_UNMETERED:
        return None
    if wt == WINDOW_5H_WEEKLY:
        delta = weekly_delta_pct  # weekly ceiling is binding; a 5h-only delta cannot be converted
    elif wt in (WINDOW_5H, WINDOW_DAILY):
        delta = five_hour_delta_pct
    else:
        delta = weekly_delta_pct if weekly_delta_pct else five_hour_delta_pct
    if not delta or delta <= 0:
        return None
    g = max(0.0, float(granularity_pct or 0.0))
    point = float(completed) * 100.0 / float(delta)
    hi_delta = float(delta) + g / 2.0
    lo_delta = max(float(delta) - g / 2.0, g / 2.0 if g > 0 else float(delta))
    return {
        "tasks_per_pool": point,
        "tasks_per_pool_low": float(completed) * 100.0 / hi_delta,
        "tasks_per_pool_high": float(completed) * 100.0 / lo_delta,
        "tasks_per_pool_evidence": "measured",
    }


def calibrate_pool_budget(pairs: Iterable[tuple[float | None, float | None]]) -> float | None:
    """API-$ one pool cycle delivers, calibrated from measured (tasks_per_pool, api_cost) lanes."""
    values = [float(t) * float(c) for t, c in pairs if t and c and t > 0 and c > 0]
    return median(values) if values else None


def estimate_tasks_per_pool(
    window_type: str | None,
    tier: int,
    api_cost: float | None,
    pool_budget: float | None = None,
    pool_cost: float | None = None,
    speed: str | None = None,
    request_allowance: float | None = None,
) -> dict[str, Any]:
    wt = normalize_window_type(window_type)
    point, evidence = None, None
    if wt == WINDOW_UNMETERED:
        return {"tasks_per_pool": None, "tasks_per_pool_low": None, "tasks_per_pool_high": None, "tasks_per_pool_evidence": "unmetered"}
    if wt == WINDOW_MONTHLY:
        allowance = float(request_allowance or DEFAULT_REQUEST_ALLOWANCE)
        per_task = REQUESTS_PER_TASK.get(int(tier), 2.0)
        if (speed or "").lower() == "fast":
            per_task *= FAST_REQUEST_MULTIPLIER
        point, evidence = allowance / per_task, "est_published_allowance"
    elif api_cost and api_cost > 0:
        if pool_budget and pool_budget > 0:
            point, evidence = pool_budget / api_cost, "est_calibrated"
        elif pool_cost and pool_cost > 0:
            point, evidence = pool_cost * DEFAULT_PRIOR_LEVERAGE / api_cost, "est_prior"
    if point is None:
        return {"tasks_per_pool": None, "tasks_per_pool_low": None, "tasks_per_pool_high": None, "tasks_per_pool_evidence": "unresolved"}
    return {
        "tasks_per_pool": point,
        "tasks_per_pool_low": point * (1.0 - ESTIMATE_BAND),
        "tasks_per_pool_high": point * (1.0 + ESTIMATE_BAND),
        "tasks_per_pool_evidence": evidence,
    }


def pool_economics(
    *,
    tier: int,
    monthly_price: float | None,
    pool_weight: float | None,
    window_type: str | None,
    input_rate: float | None,
    output_rate: float | None,
    cache_rate: float | None = None,
    speed: str | None = None,
    completed: float | None = None,
    attempts: float | None = None,
    tokens_per_completed: float | None = None,
    weekly_delta_pct: float | None = None,
    five_hour_delta_pct: float | None = None,
    granularity_pct: float = 1.0,
    pool_budget: float | None = None,
    request_allowance: float | None = None,
    long_context_multipliers: dict[str, float] | None = None,
    active_5h_windows: float = DEFAULT_ACTIVE_5H_WINDOWS_PER_MONTH,
) -> dict[str, Any]:
    """Every standardized cost field for one model on one workload tier."""
    allocation = pool_allocation(monthly_price, pool_weight)
    cycles = cycles_per_month(window_type, active_5h_windows)
    pool_cost = cost_per_pool(allocation, window_type, active_5h_windows)
    api = api_cost_per_task(
        input_rate, output_rate, tier, cache_rate=cache_rate,
        tokens_per_completed=tokens_per_completed, attempts=attempts, completed=completed,
        long_context_multipliers=long_context_multipliers,
    )
    tpp = measured_tasks_per_pool(completed, window_type, weekly_delta_pct, five_hour_delta_pct, granularity_pct)
    if tpp is None:
        tpp = estimate_tasks_per_pool(window_type, tier, api["api_cost_per_task"], pool_budget, pool_cost, speed, request_allowance)
    tasks = tpp["tasks_per_pool"]
    sub_cost = (pool_cost / tasks) if tasks and pool_cost > 0 else (0.0 if pool_cost == 0 and tasks else None)
    api_value = (tasks * api["api_cost_per_task"]) if tasks and api["api_cost_per_task"] is not None else None
    leverage = (api_value / pool_cost) if api_value is not None and pool_cost > 0 else None
    return {
        "cost_spec_version": SPEC_VERSION,
        "window_type": normalize_window_type(window_type),
        "pool_weight": pool_weight,
        "pool_allocation_monthly": allocation,
        "pool_cycles_per_month": cycles,
        "cost_per_pool": pool_cost,
        **tpp,
        "sub_cost_per_task": sub_cost,
        **api,
        "api_value_per_pool": api_value,
        "leverage": leverage,
    }


def format_tasks_per_pool(econ: dict[str, Any]) -> str:
    """Human label, e.g. '2,000 (1,333-4,000) measured' or '250 est'."""
    t = econ.get("tasks_per_pool")
    ev = econ.get("tasks_per_pool_evidence") or ""
    if ev == "unmetered":
        return "unlimited"
    if t is None:
        return "-"
    lo, hi = econ.get("tasks_per_pool_low"), econ.get("tasks_per_pool_high")
    tag = "measured" if ev == "measured" else "est"
    fmt = (lambda v: f"{v:,.0f}") if t >= 10 else (lambda v: f"{v:,.1f}")
    if lo is not None and hi is not None and not math.isclose(lo, hi):
        return f"{fmt(t)} ({fmt(lo)}-{fmt(hi)}) {tag}"
    return f"{fmt(t)} {tag}"
