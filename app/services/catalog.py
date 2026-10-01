from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.db import connect, query, utcnow

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (BurnLedger/0.8)"


@dataclass
class CatalogModel:
    source: str
    external_id: str
    provider: str | None
    display_name: str | None
    mode: str | None = None
    context_window: int | None = None
    input_per_million: float | None = None
    cache_write_per_million: float | None = None
    cache_read_per_million: float | None = None
    output_per_million: float | None = None
    reasoning_supported: bool | None = None
    capabilities: dict[str, Any] | None = None
    source_url: str | None = None
    lifecycle_status: str = "active"
    superseded_by: str | None = None
    announced_at: str | None = None
    deprecation_date: str | None = None


def _million(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    # LiteLLM explicitly reports per-token prices; scale by 1,000,000 to get per-million.
    # A threshold of 0.005 ($5,000/1M) distinguishes per-token rates while preserving cheap per-million rates.
    return x * 1_000_000 if x < 0.005 else x


def parse_litellm_payload(payload: dict[str, Any], source_url: str) -> list[CatalogModel]:
    result: list[CatalogModel] = []
    for item in payload.get("data", []):
        capabilities = {
            k: item.get(k)
            for k in (
                "supports_function_calling", "supports_vision", "supports_audio_input",
                "supports_response_schema", "supports_prompt_caching", "supports_web_search",
                "supports_pdf_input"
            )
            if item.get(k) is not None
        }
        result.append(CatalogModel(
            source="litellm",
            external_id=str(item.get("id")),
            provider=item.get("provider"),
            display_name=item.get("id"),
            mode=item.get("mode"),
            context_window=item.get("max_input_tokens"),
            input_per_million=_million(item.get("input_cost_per_token")),
            cache_read_per_million=_million(item.get("cache_read_input_token_cost")),
            output_per_million=_million(item.get("output_cost_per_token")),
            reasoning_supported=item.get("supports_reasoning"),
            capabilities=capabilities,
            source_url=source_url,
        ))
    return result


def parse_cursor_pricing_html(html: str, source_url: str) -> list[CatalogModel]:
    soup = BeautifulSoup(html, "html.parser")
    models: list[CatalogModel] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers or "name" not in headers or "input" not in headers or "output" not in headers:
            continue
        rows = table.find_all("tr")[1:]
        heading = ""
        node = table
        for _ in range(8):
            node = node.find_previous() if node else None
            if node and getattr(node, "name", "") in {"h2", "h3"}:
                heading = node.get_text(" ", strip=True)
                break
        source = "cursor_official"
        provider_hint = "cursor" if "Cursor Models" in heading else None
        for tr in rows:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            name = cells[0].replace("Image:", "").strip()
            if not name:
                continue
            values: dict[str, float | None] = {}
            for idx, header in enumerate(headers[1:], start=1):
                raw = cells[idx] if idx < len(cells) else ""
                m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", raw)
                values[header] = float(m.group(1)) if m else None
            provider = provider_hint
            lname = name.lower()
            if provider is None:
                if "claude" in lname:
                    provider = "anthropic"
                elif "gemini" in lname:
                    provider = "google"
                elif "gpt" in lname or "openai" in lname:
                    provider = "openai"
                elif "grok" in lname:
                    provider = "xai"
                elif "meta" in lname or "muse" in lname:
                    provider = "meta"
            ext = re.sub(r"[^a-z0-9]+", "-", lname).strip("-")
            models.append(CatalogModel(
                source=source,
                external_id=ext,
                provider=provider,
                display_name=name,
                input_per_million=values.get("input"),
                cache_write_per_million=values.get("cache write"),
                cache_read_per_million=values.get("cache read"),
                output_per_million=values.get("output"),
                source_url=source_url,
                capabilities={"cursor_pool": "Cursor Models" if provider_hint == "cursor" else "Other Models"},
            ))
    return models


def upsert_models(models: list[CatalogModel], *, emit_new_events: bool = True, complete_snapshot: bool = False) -> dict[str, int]:
    now = utcnow()
    new_count = changed_count = 0
    with connect() as conn:
        for m in models:
            caps = json.dumps(m.capabilities or {}, sort_keys=True)
            signature = json.dumps({
                "provider": m.provider,
                "name": m.display_name,
                "context": m.context_window,
                "input": m.input_per_million,
                "cache_write": m.cache_write_per_million,
                "cache_read": m.cache_read_per_million,
                "output": m.output_per_million,
                "reasoning": m.reasoning_supported,
                "caps": m.capabilities or {},
                "lifecycle_status": m.lifecycle_status,
                "superseded_by": m.superseded_by,
                "announced_at": m.announced_at,
                "deprecation_date": m.deprecation_date,
            }, sort_keys=True)
            raw_hash = hashlib.sha256(signature.encode()).hexdigest()
            old = conn.execute(
                "SELECT * FROM model_catalog WHERE source=? AND external_id=?",
                (m.source, m.external_id),
            ).fetchone()
            if old is None:
                cur = conn.execute(
                    """INSERT INTO model_catalog(source,external_id,provider,display_name,mode,context_window,input_per_million,cache_write_per_million,cache_read_per_million,output_per_million,reasoning_supported,capabilities_json,source_url,first_seen_at,last_seen_at,active,raw_hash,lifecycle_status,superseded_by,announced_at,deprecation_date)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (m.source,m.external_id,m.provider,m.display_name,m.mode,m.context_window,m.input_per_million,m.cache_write_per_million,m.cache_read_per_million,m.output_per_million,None if m.reasoning_supported is None else int(m.reasoning_supported),caps,m.source_url,now,now,1,raw_hash,m.lifecycle_status,m.superseded_by,m.announced_at,m.deprecation_date),
                )
                model_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO model_price_history(model_catalog_id,captured_at,input_per_million,cache_write_per_million,cache_read_per_million,output_per_million,reason) VALUES(?,?,?,?,?,?,?)",
                    (model_id,now,m.input_per_million,m.cache_write_per_million,m.cache_read_per_million,m.output_per_million,"first_seen"),
                )
                new_count += 1
                if emit_new_events and (m.provider or "").lower() in {"openai","anthropic","google","xai","cursor"}:
                    conn.execute(
                        "INSERT INTO change_events(detected_at,event_type,title,detail,new_value,severity) VALUES(?,?,?,?,?,?)",
                        (now,"new_model",f"New catalog model: {m.display_name or m.external_id}",f"Discovered from {m.source}. Entitlement is not assumed.",m.external_id,"info"),
                    )
            else:
                price_changed = any(old[k] != v for k, v in {
                    "input_per_million":m.input_per_million,
                    "cache_write_per_million":m.cache_write_per_million,
                    "cache_read_per_million":m.cache_read_per_million,
                    "output_per_million":m.output_per_million,
                }.items())
                if old["raw_hash"] != raw_hash:
                    changed_count += 1
                conn.execute(
                    """UPDATE model_catalog SET provider=?,display_name=?,mode=?,context_window=?,input_per_million=?,cache_write_per_million=?,cache_read_per_million=?,output_per_million=?,reasoning_supported=?,capabilities_json=?,source_url=?,last_seen_at=?,active=1,raw_hash=?,lifecycle_status=?,superseded_by=?,announced_at=?,deprecation_date=? WHERE id=?""",
                    (m.provider,m.display_name,m.mode,m.context_window,m.input_per_million,m.cache_write_per_million,m.cache_read_per_million,m.output_per_million,None if m.reasoning_supported is None else int(m.reasoning_supported),caps,m.source_url,now,raw_hash,m.lifecycle_status,m.superseded_by,m.announced_at,m.deprecation_date,old["id"]),
                )
                if price_changed:
                    conn.execute(
                        "INSERT INTO model_price_history(model_catalog_id,captured_at,input_per_million,cache_write_per_million,cache_read_per_million,output_per_million,reason) VALUES(?,?,?,?,?,?,?)",
                        (old["id"],now,m.input_per_million,m.cache_write_per_million,m.cache_read_per_million,m.output_per_million,"price_change"),
                    )
                    conn.execute(
                        "INSERT INTO change_events(detected_at,event_type,title,detail,old_value,new_value,severity) VALUES(?,?,?,?,?,?,?)",
                        (now,"price_change",f"Model price changed: {m.display_name or m.external_id}",f"{m.source} reported new token pricing.",json.dumps({k:old[k] for k in ['input_per_million','cache_write_per_million','cache_read_per_million','output_per_million']}),json.dumps({"input":m.input_per_million,"cache_write":m.cache_write_per_million,"cache_read":m.cache_read_per_million,"output":m.output_per_million}),"warning"),
                    )
        retired = 0
        if complete_snapshot and models:
            source_name = models[0].source
            seen = {m.external_id for m in models}
            for old in conn.execute("SELECT id,external_id,display_name,active FROM model_catalog WHERE source=?", (source_name,)).fetchall():
                if old["active"] and old["external_id"] not in seen:
                    conn.execute("UPDATE model_catalog SET active=0,last_seen_at=? WHERE id=?", (now,old["id"]))
                    retired += 1
                    if emit_new_events:
                        conn.execute(
                            "INSERT INTO change_events(detected_at,event_type,title,detail,old_value,severity) VALUES(?,?,?,?,?,?)",
                            (now,"model_removed",f"Catalog model disappeared: {old['display_name'] or old['external_id']}",f"{source_name} no longer returned this model in a complete catalog snapshot.",old["external_id"],"warning"),
                        )
    return {"new": new_count, "changed": changed_count, "retired": retired, "seen": len(models)}


def parse_litellm_raw_map(payload: dict[str, Any], source_url: str) -> list[CatalogModel]:
    result: list[CatalogModel] = []
    for model_id, item in payload.items():
        if not isinstance(item, dict) or model_id == "sample_spec":
            continue
        result.append(CatalogModel(
            source="litellm",
            external_id=str(model_id),
            provider=item.get("litellm_provider"),
            display_name=str(model_id),
            mode=item.get("mode"),
            context_window=item.get("max_input_tokens") or item.get("max_tokens"),
            input_per_million=_million(item.get("input_cost_per_token")),
            cache_write_per_million=_million(item.get("cache_creation_input_token_cost")),
            cache_read_per_million=_million(item.get("cache_read_input_token_cost")),
            output_per_million=_million(item.get("output_cost_per_token")),
            reasoning_supported=item.get("supports_reasoning"),
            capabilities={k:item.get(k) for k in ("supports_function_calling","supports_vision","supports_prompt_caching","supports_web_search","supports_pdf_input") if item.get(k) is not None},
            source_url=source_url,
        ))
    return result


async def fetch_litellm_catalog(client: httpx.AsyncClient) -> list[CatalogModel]:
    page = 1
    result: list[CatalogModel] = []
    try:
        while page <= 20:
            url = f"https://api.litellm.ai/model_catalog?page_size=500&page={page}"
            response = await client.get(url, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            payload = response.json()
            result.extend(parse_litellm_payload(payload, url))
            if not payload.get("has_more"):
                break
            page += 1
        return result
    except Exception:
        raw_url = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
        response = await client.get(raw_url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return parse_litellm_raw_map(response.json(), raw_url)
