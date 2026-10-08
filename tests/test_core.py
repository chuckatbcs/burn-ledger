from __future__ import annotations

import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test-burn-ledger.db"
os.environ["BURN_LEDGER_DB"] = str(TEST_DB)

from app.db import init_db, query  # noqa: E402
from app.seed import seed_all  # noqa: E402
from app.services.catalog import parse_cursor_pricing_html, parse_litellm_payload  # noqa: E402
from app.services.sources import parse_antigravity_models, parse_openai_pricing_html, parse_openai_ranges  # noqa: E402
from app.services.task_cost import calculate_task_cost  # noqa: E402
from app.services.telemetry import compute_metrics, normalize_row  # noqa: E402


def setup_module():
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()
    seed_all()


def teardown_module():
    if TEST_DB.exists():
        TEST_DB.unlink()


def test_seed_subscriptions_and_consensus_metrics():
    subs = query("SELECT plan_name,monthly_price FROM subscriptions ORDER BY plan_name")
    assert any(x["plan_name"] == "Cursor Pro" and x["monthly_price"] == 20 for x in subs)
    metrics = query("SELECT * FROM lane_metrics WHERE evidence_status='consensus_matched'")
    assert len(metrics) == 8
    flash_t2 = next(x for x in metrics if x["model_key"] == "gemini-3.8-flash-medium" and x["task_class"].startswith("Tier 2"))
    assert flash_t2["completed_per_visible_1pct"] == 20
    assert flash_t2["first_pass_rate"] == 0.90


def test_normalize_current_matched_schema():
    row = normalize_row({
        "task_id":"t1","matched_pair_id":"p1","task_class":"Tier 2: Standard Engineering",
        "model_id":"gemini-3.8-flash-medium","reasoning":"medium","quota_pool":"gemini_models",
        "five_hour_before_pct":"100","five_hour_after_pct":"99","weekly_before_pct":"100","weekly_after_pct":"100",
        "completed":"true","first_pass_success":"false","attempt_number":"2","tool_calls":"4","agent_steps":"6",
        "input_tokens":"6000","cache_tokens":"1000","output_tokens":"1000","wall_clock_seconds":"70",
        "sanitized_description":"test task"
    })
    assert row["matched_pair_id"] == "p1"
    assert row["completed"] is True
    assert row["first_pass_success"] is False
    assert row["attempt_number"] == 2
    assert row["five_hour_before_pct"] == 100
    assert row["telemetry_fidelity"] == "exact_reported"


def test_normalize_quantized_quota_without_token_counts():
    row = normalize_row({
        "task_id": "quota-only", "model_id": "m", "five_hour_before_pct": 88,
        "five_hour_after_pct": 87, "subagent_id": "worker-2",
    })
    assert row["telemetry_fidelity"] == "quantized_quota"
    assert row["subagent_id"] == "worker-2"


def test_telemetry_drop_folder_archives_deduplicates_and_redacts(tmp_path, monkeypatch):
    import json
    from app.services import telemetry

    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    archive.mkdir()
    monkeypatch.setattr(telemetry, "TELEMETRY_INBOX_DIR", inbox)
    monkeypatch.setattr(telemetry, "TELEMETRY_ARCHIVE_DIR", archive)
    task_id = "clean-install-drop-test"
    (inbox / "drop-test.jsonl").write_text(json.dumps({
        "task_id": task_id,
        "task_class": "Tier 2: Standard Engineering",
        "model_id": "dummy-test-model",
        "completed": True,
        "first_pass_success": True,
        "description": "private task description",
        "input_tokens": 100,
        "output_tokens": 50,
        "weekly_before_pct": 100,
        "weekly_after_pct": 99,
    }) + "\n", encoding="utf-8")

    first = telemetry.import_telemetry_inbox()
    second = telemetry.import_telemetry_inbox()
    assert first["count"] == 1
    assert second["count"] == 0
    assert len(list(archive.iterdir())) == 1
    stored = query("SELECT description,raw_json,source_path FROM telemetry_attempts JOIN telemetry_runs ON telemetry_runs.id=telemetry_attempts.run_id WHERE task_id=?", (task_id,))[0]
    assert stored["description"] is None
    assert "private task description" not in stored["raw_json"]
    assert stored["source_path"].endswith("__drop-test.jsonl")


def test_telemetry_provenance_columns_migrate_in_place():
    cols = {x["name"] for x in query("PRAGMA table_info(telemetry_attempts)")}
    assert {"telemetry_fidelity", "subagent_id"}.issubset(cols)


def test_compute_metrics_uses_tasks_for_first_pass_denominator():
    rows = [
        normalize_row({"task_id":"a1","matched_pair_id":"p1","task_class":"Tier 2","model_id":"m","quota_pool":"gemini_models","five_hour_before_pct":100,"five_hour_after_pct":100,"completed":False,"first_pass_success":False,"attempt_number":1,"input_tokens":100,"output_tokens":10,"agent_steps":1,"wall_clock_seconds":5}),
        normalize_row({"task_id":"a2","matched_pair_id":"p1","task_class":"Tier 2","model_id":"m","quota_pool":"gemini_models","five_hour_before_pct":100,"five_hour_after_pct":99,"completed":True,"first_pass_success":False,"attempt_number":2,"input_tokens":100,"output_tokens":10,"agent_steps":1,"wall_clock_seconds":5}),
        normalize_row({"task_id":"b1","matched_pair_id":"p2","task_class":"Tier 2","model_id":"m","quota_pool":"gemini_models","five_hour_before_pct":99,"five_hour_after_pct":99,"completed":True,"first_pass_success":True,"attempt_number":1,"input_tokens":100,"output_tokens":10,"agent_steps":1,"wall_clock_seconds":5}),
    ]
    metrics = compute_metrics(rows, "test")
    m = metrics[0]
    assert m["sample_size"] == 2
    assert m["attempts"] == 3
    assert m["first_pass_rate"] == 0.5
    assert m["completed_per_visible_1pct"] == 2


def test_parse_litellm_catalog():
    payload = {"data":[{"id":"vendor/model-x","provider":"vendor","mode":"chat","max_input_tokens":123456,"input_cost_per_token":0.000002,"output_cost_per_token":0.00001,"cache_read_input_token_cost":0.0000002,"supports_reasoning":True}],"has_more":False}
    models = parse_litellm_payload(payload, "https://example.test")
    assert len(models) == 1
    assert models[0].input_per_million == 2.0
    assert models[0].output_per_million == 10.0
    assert models[0].context_window == 123456


def test_parse_cursor_pricing_table():
    html = """
    <h2>Other Models</h2><table><thead><tr><th>Name</th><th>Input</th><th>Cache Write</th><th>Cache Read</th><th>Output</th></tr></thead>
    <tbody><tr><td>Claude Sonnet 5</td><td>$2</td><td>$2.5</td><td>$0.2</td><td>$10</td></tr></tbody></table>
    """
    models = parse_cursor_pricing_html(html, "https://cursor.test")
    assert len(models) == 1
    assert models[0].provider == "anthropic"
    assert models[0].cache_read_per_million == 0.2


def test_parse_antigravity_models_table():
    html = """<table><tr><th>Model</th><th>Google AI Pro</th></tr><tr><td>Gemini 3.8 Flash</td><td>✅</td></tr><tr><td>Claude Sonnet 4.6 (thinking)</td><td>✅</td></tr></table>"""
    assert parse_antigravity_models(html) == ["Gemini 3.8 Flash","Claude Sonnet 4.6 (thinking)"]


def test_parse_openai_ranges():
    html = "<p>GPT-6 Astra approximately 5–45 local messages per five hours.</p><p>GPT-5.6 Sol 10-100 local messages.</p><p>GPT-5.6 Terra 25–200.</p><p>GPT-5.6 Luna 250–2,000.</p>"
    out = parse_openai_ranges(html)
    assert out["GPT-6 Astra"] == (5,45)
    assert out["GPT-5.6 Luna"] == (250,2000)


def test_v09_openai_pricing_parser_and_long_context_band():
    html = """
      <table><tr><td>GPT-6.1 Sol</td><td>$2.00</td><td>$0.10</td><td>$2.50</td><td>$10.00</td>
      <td>$4.00</td><td>$0.20</td><td>$5.00</td><td>$15.00</td></tr></table>
    """
    parsed = parse_openai_pricing_html(html)
    assert parsed[0]["external_id"] == "gpt-6.1-sol"
    assert parsed[0]["long_context"]["output_per_million"] == 15.0
    short = calculate_task_cost({"input_per_million": 2.0, "cache_read_per_million": .1, "output_per_million": 10.0}, "standard")
    long = calculate_task_cost({"input_per_million": 2.0, "cache_read_per_million": .1, "output_per_million": 10.0}, "massive_context")
    assert short["task_cost_band"] == "short_context"
    assert long["task_cost_band"] == "long_context"
    assert long["task_cost_band_multipliers"] == {"input": 1.0, "cache_read": 1.0, "output": 1.0}
    assert long["task_cost_pricing_basis"] == "standard_rates"

    provider_band = calculate_task_cost({
        "input_per_million": 2.0,
        "cache_read_per_million": .1,
        "output_per_million": 10.0,
        "long_context_pricing": {"input_per_million": 4.0, "cache_read_per_million": .2, "output_per_million": 15.0},
        "long_context_threshold": 272_000,
    }, "massive_context")
    assert provider_band["task_cost_pricing_basis"] == "provider_long_context_band"
    assert provider_band["task_cost_band_multipliers"] == {"input": 1.0, "cache_read": 1.0, "output": 1.0}


def test_openai_pricing_parser_rejects_ambiguous_currency_windows():
    html = "<h2>GPT-6.1 Sol</h2><p>$5 promotional credit $2 $0.1 $2.5 $10 $4 $0.2 $5 $15</p>"
    assert parse_openai_pricing_html(html) == []


def test_v09_lifecycle_metadata_and_migration_are_idempotent():
    init_db()
    init_db()
    superseded = query("SELECT lifecycle_status,superseded_by FROM model_catalog WHERE external_id='gpt-6-sol' AND source='official_baseline'")
    assert superseded == [{"lifecycle_status": "superseded", "superseded_by": "gpt-6.1-sol"}]
    assert query("SELECT COUNT(*) AS n FROM harness_models WHERE model_key='gpt-6.1-sol'")[0]["n"] >= 1


def test_v09_superseded_routes_are_not_recommended():
    from app.services.tier_recommendations import _route_candidate, TIER_DEFINITIONS
    row = {"external_id": "gpt-6-sol", "display_name": "GPT-6 Sol", "lifecycle_status": "superseded", "superseded_by": "gpt-6.1-sol"}
    assert _route_candidate(row, TIER_DEFINITIONS[2], {}, {"input": .7, "cache_read": .2, "output": .1}, "api") is None


def test_v02_source_watch_migration_columns_exist():
    cols = {x["name"] for x in query("PRAGMA table_info(source_watch)")}
    assert "last_error" in cols
    assert "consecutive_failures" in cols


def test_cursor_baseline_is_seeded():
    rows = query(
        """SELECT hm.model_display_name, hm.entitlement_status
           FROM harness_models hm JOIN subscriptions s ON s.id=hm.subscription_id
           WHERE s.plan_name='Cursor Pro'"""
    )
    names = {r["model_display_name"] for r in rows}
    assert "Composer 2.5" in names
    assert "Claude Opus 5.5 Medium" in names


def test_v02_api_catalog_and_watch_controls():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import connect, utcnow

    with connect() as conn:
        # Add enough catalog rows to exercise server-side paging and sorting.
        now = utcnow()
        for i in range(65):
            conn.execute(
                """INSERT OR IGNORE INTO model_catalog(
                       source,external_id,provider,display_name,mode,context_window,
                       input_per_million,cache_write_per_million,cache_read_per_million,
                       output_per_million,reasoning_supported,capabilities_json,source_url,
                       first_seen_at,last_seen_at,active,raw_hash)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "litellm", f"test-model-{i:03d}", "test-provider", f"Test Model {i:03d}",
                    "chat", 1000+i, float(i), None, None, float(i)+1, 0, "{}",
                    "https://example.test", now, now, 1, f"hash-{i}",
                ),
            )
        watch = conn.execute("SELECT id FROM source_watch ORDER BY id LIMIT 1").fetchone()
        conn.execute(
            "INSERT INTO change_events(detected_at,event_type,title,detail,severity) VALUES(?,?,?,?,?)",
            (now,"new_model","test alert","detail","info"),
        )
        event_id = conn.execute("SELECT id FROM change_events WHERE title='test alert' ORDER BY id DESC LIMIT 1").fetchone()["id"]

    with TestClient(app) as client:
        r = client.get("/api/models", params={"scope":"all","provider":"test-provider","page_size":25,"page":2,"sort":"model","direction":"desc"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["total"] == 65
        assert payload["total_pages"] == 3
        assert payload["page"] == 2
        assert len(payload["models"]) == 25
        assert payload["models"][0]["display_name"] > payload["models"][-1]["display_name"]

        r = client.get("/api/models")
        assert r.status_code == 200
        plan = r.json()
        assert plan["scope"] == "plan"
        assert any(m["plan_name"] == "Cursor Pro" for m in plan["models"])

        r = client.patch(f"/api/sources/{watch['id']}", json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] == 0
        r = client.patch(f"/api/sources/{watch['id']}", json={"enabled": True})
        assert r.status_code == 200 and r.json()["enabled"] == 1

        r = client.post(f"/api/changes/{event_id}/ack")
        assert r.status_code == 200
        assert query("SELECT acknowledged FROM change_events WHERE id=?", (event_id,))[0]["acknowledged"] == 1


def test_v03_availability_refactors_recommendations():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        d = client.get('/api/dashboard').json()
        gem_t3 = next(r for r in d['recommendations'] if r['pool_name'] == 'Gemini Models' and r['tier'] == 'Tier 3')
        assert gem_t3['quota_first']['model_key'] == 'gemini-3.8-flash-medium'
        assert gem_t3['time_first']['model_key'] == 'gemini-3.1-pro-high'

        r = client.patch('/api/availability/model/gemini-3.8-flash-medium', json={'enabled': False})
        assert r.status_code == 200
        d = client.get('/api/dashboard').json()
        gem_t2 = next(r for r in d['recommendations'] if r['pool_name'] == 'Gemini Models' and r['tier'] == 'Tier 2')
        gem_t3 = next(r for r in d['recommendations'] if r['pool_name'] == 'Gemini Models' and r['tier'] == 'Tier 3')
        assert gem_t2['quota_first']['model_key'] == 'gemini-3.1-pro-high'
        assert gem_t3['quota_first']['model_key'] == 'gemini-3.1-pro-high'
        assert gem_t3['changed_by_availability'] is True

        # Provider-level disable excludes all Anthropic measured candidates without deleting history.
        r = client.patch('/api/availability/provider/Anthropic', json={'enabled': False})
        assert r.status_code == 200
        d = client.get('/api/dashboard').json()
        claude_routes = [r for r in d['recommendations'] if r['pool_name'] == 'Claude & GPT Models']
        assert claude_routes
        assert all(r['available_count'] == 0 for r in claude_routes)
        assert all(r['quota_first'] is None and r['time_first'] is None for r in claude_routes)
        lanes = [l for l in d['lanes'] if l['pool_name'] == 'Claude & GPT Models']
        assert lanes and all(l['available'] is False for l in lanes)

        # Re-enable so the test DB remains representative.
        client.patch('/api/availability/model/gemini-3.8-flash-medium', json={'enabled': True})
        client.patch('/api/availability/provider/Anthropic', json={'enabled': True})


def test_v03_plan_catalog_exposes_vendor_and_model_toggle_state():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get('/api/models', params={'scope': 'plan', 'provider': 'Anthropic', 'page_size': 100})
        assert r.status_code == 200
        data = r.json()
        assert data['models']
        assert all(m['provider'] == 'Anthropic' for m in data['models'])
        assert all('available' in m and 'model_enabled' in m and 'provider_enabled' in m for m in data['models'])
        providers = {p['provider'] for p in data['availability_providers']}
        assert {'Anthropic', 'Google', 'OpenAI', 'Cursor', 'xAI'}.issubset(providers)


def test_v04_plan_catalog_enriches_official_economics_and_context():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        data = client.get('/api/models', params={'scope':'plan','page_size':100}).json()
        by_key = {m['external_id']: m for m in data['models']}
        assert by_key['gpt-5-6-sol-medium']['context_window'] == 1_050_000
        assert by_key['gpt-5-6-sol-medium']['input_per_million'] == 4.0
        assert by_key['gpt-5-6-sol-medium']['cache_read_per_million'] == 0.4
        assert by_key['gpt-5-6-sol-medium']['output_per_million'] == 20.0
        assert by_key['gpt-5-6-sol-medium']['data_status'] == 'complete'
        assert by_key['claude-opus-5-5-medium']['context_window'] == 300_000
        assert by_key['claude-opus-5-5-medium']['pricing_source'] in {'official_baseline','cursor_official'}
        assert by_key['claude-sonnet-4-6']['input_per_million'] == 3.0


def test_v04_enrichment_matches_effort_suffix_variants():
    from app.services.enrichment import enrich_plan_rows
    from app.db import connect, utcnow

    now = utcnow()
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO model_catalog(source,external_id,provider,display_name,mode,context_window,input_per_million,cache_write_per_million,cache_read_per_million,output_per_million,reasoning_supported,capabilities_json,source_url,first_seen_at,last_seen_at,active,raw_hash)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('litellm','synthetic-gemini-9-pro','Google','Gemini 9 Pro','chat',777000,9.0,None,0.9,45.0,1,'{}','https://example.test',now,now,1,'synthetic')
        )
    row = {'external_id':'synthetic-gemini-9-pro-high','display_name':'Gemini 9 Pro High','provider':'Google','plan_name':'Example','last_seen_at':now,
           'context_window':None,'input_per_million':None,'cache_write_per_million':None,'cache_read_per_million':None,'output_per_million':None}
    out = enrich_plan_rows([row])[0]
    assert out['context_window'] == 777000
    assert out['input_per_million'] == 9.0
    assert out['data_status'] == 'complete'


def test_v05_task_cost_profile_calculation_and_sorting():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get('/api/models', params={
            'scope':'plan', 'page_size':100, 'task_profile':'standard',
            'sort':'task_cost', 'direction':'asc'
        })
        assert r.status_code == 200
        data = r.json()
        assert data['task_cost_profile']['key'] == 'standard'
        assert data['task_cost_profile']['billable_tokens'] == 10_000
        priced = [m for m in data['models'] if m['task_cost_per_task'] is not None]
        assert priced
        assert all(priced[i]['task_cost_per_task'] <= priced[i+1]['task_cost_per_task'] for i in range(len(priced)-1))

        by_key = {m['external_id']: m for m in data['models']}
        sol = by_key['gpt-5-6-sol-medium']
        # Standard profile = 10k billable tokens at 70% input / 20% cache-read / 10% output.
        # GPT-5.6 Sol baseline = $4 input / $0.40 cache-read / $20 output per million.
        assert abs(sol['task_cost_per_task'] - 0.0488) < 1e-9
        assert sol['task_cost_status'] == 'priced'

        long = client.get('/api/models', params={
            'scope':'plan', 'page_size':100, 'task_profile':'long_horizon',
            'sort':'task_cost', 'direction':'asc'
        }).json()
        long_sol = next(m for m in long['models'] if m['external_id'] == 'gpt-5-6-sol-medium')
        assert abs(long_sol['task_cost_per_task'] - 0.244) < 1e-9


def test_v05_task_cost_cache_fallback_is_explicit():
    from app.services.task_cost import calculate_task_cost

    row = {'input_per_million': 2.0, 'cache_read_per_million': None, 'output_per_million': 10.0}
    out = calculate_task_cost(row, 'standard', {'input': .7, 'cache_read': .2, 'output': .1})
    assert abs(out['task_cost_per_task'] - 0.028) < 1e-9
    assert out['task_cost_status'] == 'cache_at_input_rate'


def test_v06_tier_top3_are_unique_cost_sorted_and_fit_gated():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        data = client.get('/api/dashboard').json()['tier_recommendations']
        tiers = {t['key']: t for t in data['tiers']}
        assert set(tiers) == {'tier1','tier2','tier3','tier4'}
        for t in tiers.values():
            top = t['top_models']
            assert len(top) <= 3
            families = [m['family_key'] for m in top]
            assert len(families) == len(set(families))
            costs = [m['cost_per_completed_task'] for m in top]
            assert costs == sorted(costs)
            assert all(m['fit_score'] >= 2 for m in top)

        assert [m['model_display_name'] for m in tiers['tier1']['top_models']] == [
            'GPT-5.6 Luna', 'Composer 2.5', 'Gemini 3.8 Flash'
        ]
        assert [m['model_display_name'] for m in tiers['tier2']['top_models']] == [
            'Composer 2.5', 'Gemini 3.8 Flash', 'Claude Sonnet 5 High'
        ]
        assert [m['model_display_name'] for m in tiers['tier4']['top_models']][:2] == [
            'Gemini 3.1 Pro', 'Claude Opus 5.5 Medium'
        ]
        # Measured Antigravity lanes upgrade the displayed cost evidence.
        flash_t2 = next(m for m in tiers['tier2']['top_models'] if 'Gemini 3.8 Flash' in m['model_display_name'])
        assert flash_t2['cost_evidence'] == 'measured'
        assert flash_t2['first_pass_rate'] == 0.90


def test_v06_availability_refactors_tier_top3_without_erasing_history():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        before = client.get('/api/dashboard').json()['tier_recommendations']
        tier4_before = next(t for t in before['tiers'] if t['key'] == 'tier4')
        assert any(m['provider'] == 'Anthropic' for m in tier4_before['top_models'])

        r = client.patch('/api/availability/provider/Anthropic', json={'enabled': False})
        assert r.status_code == 200
        after = client.get('/api/dashboard').json()['tier_recommendations']
        tier4_after = next(t for t in after['tiers'] if t['key'] == 'tier4')
        assert all(m['provider'] != 'Anthropic' for m in tier4_after['top_models'])
        assert tier4_after['changed_by_availability'] is True

        client.patch('/api/availability/provider/Anthropic', json={'enabled': True})


def test_v08_quota_basis_ranks_measured_weekly_burn_and_keeps_api_cost_visible():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        api_data = client.get('/api/dashboard').json()['tier_recommendations']
        assert api_data['cost_basis']['key'] == 'api'
        tier1 = next(t for t in api_data['tiers'] if t['key'] == 'tier1')
        assert tier1['top_models'][0]['model_display_name'] == 'GPT-5.6 Luna'
        assert tier1['top_models'][0]['api_cost_per_completed_task'] is not None
        assert tier1['top_models'][0]['weekly_burn_pct_per_completed'] is None

        quota_data = client.get('/api/dashboard?recommendation_basis=quota').json()['tier_recommendations']
        assert quota_data['cost_basis']['key'] == 'quota'
        tiers = {t['key']: t for t in quota_data['tiers']}
        assert len(tiers['tier1']['top_models']) == 3
        assert len(tiers['tier4']['top_models']) == 3
        assert all(m['cost_evidence'] == 'api_proxy' for m in tiers['tier1']['top_models'])
        assert all(m['cost_evidence'] == 'api_proxy' for m in tiers['tier4']['top_models'])

        t2 = tiers['tier2']['top_models']
        assert len(t2) == 3
        assert t2[0]['model_display_name'] == 'Gemini 3.8 Flash'
        assert t2[0]['cost_evidence'] == 'measured_subscription'
        assert abs(t2[0]['weekly_burn_pct_per_completed'] - 0.05) < 1e-12
        assert abs(t2[0]['five_hour_burn_pct_per_completed'] - 0.05) < 1e-12
        assert abs(t2[0]['tasks_per_weekly_quota'] - 2000.0) < 1e-12
        assert t2[0]['api_cost_per_completed_task'] is not None
        assert abs(t2[0]['cost_per_completed_task'] - 0.05) < 1e-12

        t3 = tiers['tier3']['top_models']
        assert len(t3) == 3
        assert t3[0]['model_display_name'] == 'Gemini 3.8 Flash'
        assert all(m['weekly_burn_pct_per_completed'] is not None for m in t3)
        assert all(m['api_cost_per_completed_task'] is not None for m in t3)
        assert quota_data['summary']['ranked_slot_coverage_pct'] == 0.5
        assert quota_data['summary']['quota_fallback_slot_count'] == 6

        # Legacy query value remains supported but resolves to the new quota-first basis.
        legacy = client.get('/api/dashboard?recommendation_basis=subscription')
        assert legacy.status_code == 200
        assert legacy.json()['tier_recommendations']['cost_basis']['key'] == 'quota'


def test_v08_quota_basis_respects_availability():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        client.patch('/api/availability/provider/Anthropic', json={'enabled': False})
        quota_data = client.get('/api/dashboard?recommendation_basis=quota').json()['tier_recommendations']
        t2 = next(t for t in quota_data['tiers'] if t['key'] == 'tier2')
        assert all(m['provider'] != 'Anthropic' for m in t2['top_models'])
        assert t2['changed_by_availability'] is True
        client.patch('/api/availability/provider/Anthropic', json={'enabled': True})


def test_v10_standardized_pool_economics_in_tier_recommendations():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        data = client.get('/api/dashboard').json()['tier_recommendations']
        t2 = next(t for t in data['tiers'] if t['key'] == 'tier2')
        flash = next(m for m in t2['top_models'] if 'Gemini 3.8 Flash' in m['model_display_name'])
        assert flash['cost_per_pool'] == 2.3065
        assert flash['tasks_per_pool'] == 2000.0
        assert flash['tasks_per_pool_evidence'] == 'measured'
        assert '2,000' in flash['formatted_tasks_per_pool']
        assert 'measured' in flash['formatted_tasks_per_pool']

        composer = next(m for m in t2['top_models'] if 'Composer 2.5' in m['model_display_name'])
        assert composer['cost_per_pool'] == 10.0
        assert composer['tasks_per_pool'] == 250.0
        assert composer['tasks_per_pool_evidence'] == 'est_published_allowance'
        assert '250' in composer['formatted_tasks_per_pool']


def test_v11_standardized_pool_economics_in_models_catalog():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get('/api/models', params={'scope': 'plan', 'page_size': 100})
        assert r.status_code == 200
        data = r.json()
        models = data['models']
        assert len(models) > 0
        flash_google = next((m for m in models if m['external_id'] == 'gemini-3.8-flash-medium' and 'Google' in m['plan_name']), None)
        assert flash_google is not None
        assert flash_google['cost_per_pool'] == 2.3065
        assert flash_google['tasks_per_pool'] == 2000.0
        assert flash_google['tasks_per_pool_evidence'] == 'measured'
        assert flash_google['sub_cost_per_task'] is not None
        assert flash_google['api_cost_per_task'] is not None
        assert flash_google['api_value_per_pool'] is not None
        assert flash_google['leverage'] is not None
        assert '2,000' in flash_google['formatted_tasks_per_pool']

        flash_cursor = next((m for m in models if 'gemini-3-8-flash' in m['external_id'] and 'Cursor' in m['plan_name']), None)
        assert flash_cursor is not None
        assert flash_cursor['cost_per_pool'] == 10.0

        r_sorted = client.get('/api/models', params={'scope': 'plan', 'sort': 'cost_pool', 'direction': 'asc'})
        assert r_sorted.status_code == 200
        sorted_models = [m for m in r_sorted.json()['models'] if m['cost_per_pool'] is not None]
        assert len(sorted_models) >= 2
        assert sorted_models[0]['cost_per_pool'] <= sorted_models[1]['cost_per_pool']
