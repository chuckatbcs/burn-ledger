from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import DB_PATH, connect, get_setting, init_db, query, set_setting, utcnow
from app.seed import seed_all
from app.services.sources import sync_all_sources, sync_source
from app.services.availability import (
    current_recommendations, decorate_lanes, decorate_model_rows, provider_states, set_override
)
from app.services.telemetry import import_telemetry
from app.services.enrichment import enrich_plan_rows
from app.services.task_cost import DEFAULT_PROFILE, TASK_PROFILES, decorate_task_cost, profile_meta
from app.services.tier_recommendations import tier_recommendations

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
_sync_lock = asyncio.Lock()


async def run_sync_guarded() -> dict[str, Any]:
    if _sync_lock.locked():
        return {"status": "busy", "detail": "A sync is already running."}
    async with _sync_lock:
        return await sync_all_sources()


async def periodic_sync() -> None:
    await asyncio.sleep(3)
    while True:
        try:
            await run_sync_guarded()
        except Exception:
            pass
        interval = max(60, int(get_setting("sync_interval_minutes", 360)) * 60)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_all()
    task = None if os.getenv("BURN_LEDGER_DISABLE_AUTO_SYNC") == "1" else asyncio.create_task(periodic_sync())
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


APP_VERSION = "0.9.0"

app = FastAPI(
    title="Burn Ledger",
    version=APP_VERSION,
    description="Evidence-aware AI subscription burn, model catalog, and task-yield tracker.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SubscriptionPatch(BaseModel):
    monthly_price: float | None = Field(default=None, ge=0)
    enabled: bool | None = None
    auto_update_price: bool | None = None


class SettingsPatch(BaseModel):
    sync_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    telemetry_redact_descriptions: bool | None = None
    catalog_token_mix: dict[str, float] | None = None


class SourcePatch(BaseModel):
    enabled: bool


class AvailabilityPatch(BaseModel):
    enabled: bool


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "db": str(DB_PATH), "time": utcnow()}


@app.get("/api/dashboard")
def dashboard(recommendation_basis: str = Query("api", pattern="^(api|quota|subscription)$")):
    subs = query("SELECT * FROM subscriptions WHERE enabled=1 ORDER BY monthly_price DESC, plan_name")
    total_spend = sum(float(s["monthly_price"] or 0) for s in subs)
    lanes = decorate_lanes(query(
        """SELECT lm.*, s.provider, s.plan_name, qp.name AS pool_name,
                  COALESCE(hm.model_display_name,lm.model_key) AS model_display_name
           FROM lane_metrics lm
           JOIN subscriptions s ON s.id=lm.subscription_id
           LEFT JOIN quota_pools qp ON qp.id=lm.quota_pool_id
           LEFT JOIN harness_models hm ON hm.subscription_id=lm.subscription_id AND hm.model_key=lm.model_key
           WHERE lm.observed_at = (
             SELECT MAX(x.observed_at) FROM lane_metrics x
             WHERE x.subscription_id=lm.subscription_id AND x.model_key=lm.model_key AND x.task_class=lm.task_class
           )
           ORDER BY s.provider, lm.task_class, lm.model_key"""
    ))
    changes = query(
        """SELECT * FROM change_events
           WHERE acknowledged=0 AND event_type!='source_changed'
           ORDER BY detected_at DESC LIMIT 50"""
    )
    sources = query("SELECT * FROM source_watch ORDER BY label")
    failures = [s for s in sources if int(s.get("enabled") or 0) and int(s.get("last_status") or 0) == 0 and s.get("last_checked")]
    last_sync = query("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1")
    catalog_count = query("SELECT COUNT(*) AS n FROM model_catalog WHERE active=1")[0]["n"]
    return {
        "monthly_spend": total_spend,
        "annual_spend": total_spend * 12,
        "subscriptions": subs,
        "lanes": lanes,
        "recommendations": current_recommendations(),
        "tier_recommendations": tier_recommendations(recommendation_basis),
        "availability_providers": provider_states(),
        "changes": changes,
        "source_failures": failures,
        "sources": sources,
        "last_sync": last_sync[0] if last_sync else None,
        "catalog_count": catalog_count,
        "settings": {
            "sync_interval_minutes": get_setting("sync_interval_minutes", 360),
            "telemetry_redact_descriptions": get_setting("telemetry_redact_descriptions", True),
            "catalog_token_mix": get_setting("catalog_token_mix", {"input": .7, "cache_read": .2, "output": .1}),
        },
    }


def _catalog_plan_query() -> str:
    return """
        SELECT
          hm.id AS row_id,
          0 AS catalog_id,
          'entitlement' AS source,
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
          hm.model_display_name AS display_name,
          NULL AS mode,
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


SORT_MAP = {
    "provider": "provider",
    "model": "display_name",
    "source": "source",
    "context": "context_window",
    "input": "input_per_million",
    "cache": "cache_read_per_million",
    "output": "output_per_million",
    "seen": "last_seen_at",
    "plan": "plan_name",
    "task_cost": "task_cost_per_task",
}


@app.get("/api/models")
def models(
    q: str = Query(default=""),
    provider: str = Query(default=""),
    source: str = Query(default=""),
    scope: Literal["plan", "official", "all"] = Query(default="plan"),
    sort: str = Query(default="provider"),
    direction: Literal["asc", "desc"] = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=25, le=100),
    task_profile: Literal["micro", "standard", "long_horizon", "massive_context"] = Query(default=DEFAULT_PROFILE),
):
    sort_col = SORT_MAP.get(sort, "provider")
    direction_sql = "DESC" if direction == "desc" else "ASC"
    params: list[Any] = []

    cost_mix = get_setting("catalog_token_mix", {"input": .7, "cache_read": .2, "output": .1})

    if scope == "plan":
        base_rows = decorate_task_cost(enrich_plan_rows(query(_catalog_plan_query())), task_profile, cost_mix)
        providers_all = sorted({r.get("provider") for r in base_rows if r.get("provider")})
        sources_all = sorted({r.get("plan_name") for r in base_rows if r.get("plan_name")})

        def matches(r: dict[str, Any]) -> bool:
            needle = q.strip().lower()
            if needle and needle not in " ".join(str(r.get(k) or "").lower() for k in ("external_id","display_name","plan_name")):
                return False
            if provider and (r.get("provider") or "").lower() != provider.lower():
                return False
            if source and (r.get("plan_name") or "").lower() != source.lower():
                return False
            return True

        filtered_rows = [r for r in base_rows if matches(r)]
        key_map = {
            "provider": "provider", "model": "display_name", "source": "source", "context": "context_window",
            "input": "input_per_million", "cache": "cache_read_per_million", "output": "output_per_million",
            "seen": "catalog_last_seen_at", "plan": "plan_name", "task_cost": "task_cost_per_task",
        }
        field = key_map.get(sort, "provider")
        reverse = direction == "desc"
        # None always sorts last regardless of direction.
        non_null = [r for r in filtered_rows if r.get(field) is not None]
        nulls = [r for r in filtered_rows if r.get(field) is None]
        non_null.sort(key=lambda r: (str(r.get(field)).lower() if isinstance(r.get(field), str) else r.get(field)), reverse=reverse)
        filtered_rows = non_null + nulls
        total = len(filtered_rows)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        rows = decorate_model_rows(filtered_rows[offset:offset+page_size])
        return {
            "models": rows, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages,
            "providers": providers_all, "sources": sources_all, "scope": scope, "sort": sort, "direction": direction,
            "availability_providers": provider_states(),
            "task_cost_profile": profile_meta(task_profile, cost_mix),
            "task_cost_profiles": [profile_meta(k, cost_mix) for k in TASK_PROFILES],
        }
    else:
        clauses = ["active=1"]
        if scope == "official":
            clauses.append("source!='litellm'")
        if q:
            clauses.append("(external_id LIKE ? OR display_name LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if provider:
            clauses.append("LOWER(COALESCE(provider,''))=LOWER(?)")
            params.append(provider)
        if source:
            clauses.append("LOWER(source)=LOWER(?)")
            params.append(source)
        filtered = f"SELECT *, NULL AS entitlement_status, NULL AS plan_name, NULL AS pool_name FROM model_catalog WHERE {' AND '.join(clauses)}"
        scope_clause = "active=1 AND source!='litellm'" if scope == "official" else "active=1"
        provider_rows = query(f"SELECT DISTINCT provider FROM model_catalog WHERE {scope_clause} AND provider IS NOT NULL AND provider!='' ORDER BY provider")
        source_rows = query(f"SELECT DISTINCT source AS label FROM model_catalog WHERE {scope_clause} ORDER BY source")

    all_rows = decorate_task_cost(query(filtered, params), task_profile, cost_mix)
    key_map = {
        "provider": "provider", "model": "display_name", "source": "source", "context": "context_window",
        "input": "input_per_million", "cache": "cache_read_per_million", "output": "output_per_million",
        "seen": "last_seen_at", "plan": "plan_name", "task_cost": "task_cost_per_task",
    }
    field = key_map.get(sort, "provider")
    reverse = direction == "desc"
    non_null = [r for r in all_rows if r.get(field) is not None]
    nulls = [r for r in all_rows if r.get(field) is None]
    non_null.sort(key=lambda r: (str(r.get(field)).lower() if isinstance(r.get(field), str) else r.get(field)), reverse=reverse)
    all_rows = non_null + nulls
    total = len(all_rows)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    rows = decorate_model_rows(all_rows[offset:offset+page_size])
    return {
        "models": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "providers": [r["provider"] for r in provider_rows],
        "sources": [r["label"] for r in source_rows],
        "scope": scope,
        "sort": sort,
        "direction": direction,
        "availability_providers": provider_states(),
        "task_cost_profile": profile_meta(task_profile, cost_mix),
        "task_cost_profiles": [profile_meta(k, cost_mix) for k in TASK_PROFILES],
    }


@app.get("/api/availability")
def availability():
    return {"providers": provider_states(), "recommendations": current_recommendations(), "tier_recommendations": tier_recommendations()}


@app.patch("/api/availability/provider/{provider}")
def patch_provider_availability(provider: str, patch: AvailabilityPatch):
    result = set_override("provider", provider, patch.enabled)
    return {**result, "providers": provider_states(), "recommendations": current_recommendations(), "tier_recommendations": tier_recommendations()}


@app.patch("/api/availability/model/{model_key:path}")
def patch_model_availability(model_key: str, patch: AvailabilityPatch):
    result = set_override("model", model_key, patch.enabled)
    return {**result, "providers": provider_states(), "recommendations": current_recommendations(), "tier_recommendations": tier_recommendations()}


@app.get("/api/subscriptions")
def subscriptions():
    return {
        "subscriptions": query("SELECT * FROM subscriptions ORDER BY monthly_price DESC,plan_name"),
        "pools": query("SELECT * FROM quota_pools ORDER BY subscription_id,name"),
        "harness_models": query("SELECT * FROM harness_models ORDER BY subscription_id,model_display_name"),
    }


@app.patch("/api/subscriptions/{subscription_id}")
def patch_subscription(subscription_id: int, patch: SubscriptionPatch):
    current = query("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))
    if not current:
        raise HTTPException(404, "Subscription not found")
    data = patch.model_dump(exclude_none=True)
    if not data:
        return current[0]
    columns = []
    params: list[Any] = []
    for key, value in data.items():
        columns.append(f"{key}=?")
        params.append(int(value) if isinstance(value, bool) else value)
    columns.append("updated_at=?")
    params.extend([utcnow(), subscription_id])
    with connect() as conn:
        conn.execute(f"UPDATE subscriptions SET {', '.join(columns)} WHERE id=?", params)
    return query("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))[0]


@app.get("/api/sources")
def sources():
    return {
        "sources": query("SELECT * FROM source_watch ORDER BY enabled DESC,label"),
        "changes": query("SELECT * FROM change_events WHERE event_type!='source_changed' ORDER BY detected_at DESC LIMIT 100"),
    }


@app.patch("/api/sources/{source_id}")
def patch_source(source_id: int, patch: SourcePatch):
    current = query("SELECT * FROM source_watch WHERE id=?", (source_id,))
    if not current:
        raise HTTPException(404, "Source not found")
    with connect() as conn:
        conn.execute("UPDATE source_watch SET enabled=? WHERE id=?", (1 if patch.enabled else 0, source_id))
    return query("SELECT * FROM source_watch WHERE id=?", (source_id,))[0]


@app.post("/api/sources/{source_id}/sync")
async def sync_one_source(source_id: int):
    if _sync_lock.locked():
        raise HTTPException(409, "Another source sync is already running")
    async with _sync_lock:
        try:
            result = await sync_source(source_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
    if not result.get("ok"):
        return JSONResponse(status_code=502, content={"detail": result.get("error", "Source check failed"), **result})
    return result


@app.post("/api/changes/{event_id}/ack")
def acknowledge(event_id: int):
    with connect() as conn:
        cur = conn.execute("UPDATE change_events SET acknowledged=1 WHERE id=?", (event_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Change event not found")
    return {"ok": True}


@app.post("/api/changes/ack-all")
def acknowledge_all():
    with connect() as conn:
        cur = conn.execute("UPDATE change_events SET acknowledged=1 WHERE acknowledged=0 AND event_type!='source_changed'")
    return {"ok": True, "acknowledged": cur.rowcount}


# v0.1 compatibility alias.
@app.post("/api/sources/{event_id}/ack")
def acknowledge_legacy(event_id: int):
    return acknowledge(event_id)


@app.post("/api/sync")
async def sync_now():
    return JSONResponse(await run_sync_guarded())


@app.post("/api/telemetry/import")
async def telemetry_import(file: UploadFile = File(...), source: str = "Antigravity"):
    name = file.filename or "telemetry.csv"
    if not name.lower().endswith((".csv", ".jsonl")):
        raise HTTPException(400, "Upload a .csv or .jsonl telemetry file")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Telemetry file exceeds 20 MB")
    try:
        return import_telemetry(data, name, source)
    except Exception as exc:
        raise HTTPException(400, f"Could not import telemetry: {exc}") from exc


@app.get("/api/telemetry/runs")
def telemetry_runs():
    return {"runs": query("SELECT * FROM telemetry_runs ORDER BY id DESC LIMIT 100")}


@app.get("/api/metrics")
def metrics():
    return {"lanes": query(
        """SELECT lm.*,s.provider,s.plan_name,qp.name AS pool_name
           FROM lane_metrics lm JOIN subscriptions s ON s.id=lm.subscription_id
           LEFT JOIN quota_pools qp ON qp.id=lm.quota_pool_id
           ORDER BY lm.observed_at DESC,lm.task_class,lm.model_key"""
    )}


@app.get("/api/export.json")
def export_json():
    payload = {
        "generated_at": utcnow(),
        "subscriptions": query("SELECT * FROM subscriptions"),
        "quota_pools": query("SELECT * FROM quota_pools"),
        "harness_models": query("SELECT * FROM harness_models"),
        "lane_metrics": query("SELECT * FROM lane_metrics"),
        "sources": query("SELECT * FROM source_watch"),
        "change_events": query("SELECT * FROM change_events"),
        "catalog": query("SELECT * FROM model_catalog WHERE active=1"),
        "availability_overrides": query("SELECT * FROM availability_overrides ORDER BY scope,key"),
        "recommendations": current_recommendations(),
        "tier_recommendations": tier_recommendations(),
    }
    return JSONResponse(payload, headers={"Content-Disposition": "attachment; filename=burn-ledger-export.json"})


@app.get("/api/export.csv")
def export_csv():
    rows = query(
        """SELECT s.plan_name,qp.name AS quota_pool,lm.model_key,lm.task_class,lm.sample_size,lm.attempts,lm.completed,lm.first_pass_rate,lm.visible_quota_delta_pct,lm.weekly_quota_delta_pct,lm.completed_per_visible_1pct,lm.visible_100point_extrapolation,lm.tokens_per_completed,lm.steps_per_completed,lm.seconds_per_completed,lm.evidence_status,lm.observed_at,lm.source_label
           FROM lane_metrics lm JOIN subscriptions s ON s.id=lm.subscription_id
           LEFT JOIN quota_pools qp ON qp.id=lm.quota_pool_id ORDER BY lm.observed_at DESC"""
    )
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return PlainTextResponse(
        output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=burn-ledger-metrics.csv"},
    )


@app.get("/api/settings")
def settings():
    return {
        "sync_interval_minutes": get_setting("sync_interval_minutes", 360),
        "telemetry_redact_descriptions": get_setting("telemetry_redact_descriptions", True),
        "catalog_token_mix": get_setting("catalog_token_mix", {"input": .7, "cache_read": .2, "output": .1}),
    }


@app.patch("/api/settings")
def patch_settings(patch: SettingsPatch):
    data = patch.model_dump(exclude_none=True)
    if "catalog_token_mix" in data:
        mix = data["catalog_token_mix"]
        needed = {"input", "cache_read", "output"}
        if not needed.issubset(mix) or abs(sum(float(mix[k]) for k in needed) - 1.0) > 0.001:
            raise HTTPException(400, "catalog_token_mix must contain input, cache_read, output summing to 1.0")
    for key, value in data.items():
        set_setting(key, value)
    return settings()


@app.get("/api/classify")
def classify_workload_endpoint(prompt: str | None = None, dir: str | None = None):
    import sys
    import os
    tracker_dir = "/home/chuck/.gemini/antigravity/scratch/ai-burn-rate-tracker"
    if tracker_dir not in sys.path:
        sys.path.insert(0, tracker_dir)
    from engine.classifier import classify_workload
    return classify_workload(prompt=prompt, repo_path=dir)


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}"})

