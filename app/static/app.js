const state = {
  dashboard: null,
  recommendationBasis: ['quota','subscription'].includes(localStorage.getItem('burn-ledger-recommendation-basis')) ? 'quota' : 'api',
  models: [],
  sources: [],
  runs: [],
  modelQuery: {
    q: '', provider: '', source: '', scope: 'plan', sort: 'provider', direction: 'asc', page: 1, pageSize: 50, taskProfile: 'standard',
  },
};
let modelAbort = null;
let searchTimer = null;
let toastTimer = null;
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const fmtMoney = (n) => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}).format(Number(n||0));
const fmtNum = (n, d=1) => n == null ? '—' : Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const pct = (n) => n == null ? '—' : `${(Number(n)*100).toFixed(0)}%`;
const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

function toast(message){ const el=$('#toast'); el.textContent=message; el.classList.add('is-visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove('is-visible'),3200); }
async function api(url, options={}){ const r=await fetch(url, options); if(!r.ok){ let msg=`Request failed (${r.status})`; try{const j=await r.json();msg=j.detail||msg}catch{} throw new Error(msg)} return r.json(); }
function setBusy(button,busy,label){ button.disabled=busy; if(busy){button.dataset.old=button.textContent;button.textContent=label}else{button.textContent=button.dataset.old||button.textContent} }
function requestJson(url, method='POST', body=null){ return api(url,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined}); }

function showView(name){
  $$('.view').forEach(v=>v.classList.toggle('is-visible',v.id===`view-${name}`));
  $$('.tab').forEach(t=>{const active=t.dataset.view===name;t.classList.toggle('is-active',active);t.setAttribute('aria-selected',String(active));});
  try { history.replaceState(null,'',`${location.pathname}${location.search}#${name}`); } catch {}
  document.title=`${name==='overview'?'Burn Ledger':name[0].toUpperCase()+name.slice(1)+' — Burn Ledger'}`;
  if(name==='models') loadModels();
  if(name==='sources') loadSources();
  if(name==='telemetry') loadRuns();
}

function renderSpendRail(subs,total){
  const rail=$('#spendRail'); rail.innerHTML='';
  subs.forEach(s=>{ const el=document.createElement('div');el.className=`ruler-segment${Number(s.monthly_price)===0?' free':''}`;el.style.flexGrow=Number(s.monthly_price)||1;el.title=`${s.plan_name}: ${fmtMoney(s.monthly_price)}`;rail.appendChild(el); });
  $('#monthlySpend').textContent=`${fmtMoney(total)} / mo`;
  $('#annualSpend').textContent=`${fmtMoney(total*12)} / yr`;
}
function renderSubscriptions(subs){
  $('#subscriptionCards').innerHTML=subs.map(s=>`<article class="sub-card"><span class="sub-provider">${esc(s.provider)}</span><h3>${esc(s.plan_name)}</h3><div class="sub-price">${fmtMoney(s.monthly_price)}</div><div class="sub-evidence">${esc(s.evidence_status)}</div></article>`).join('');
}

function availabilityButton({scope,key,enabled,label,meta=null}){
  const pressed=enabled?'true':'false';
  const next=enabled?0:1;
  return `<button class="availability-toggle ${enabled?'is-on':'is-off'}" type="button" aria-pressed="${pressed}" data-availability-scope="${esc(scope)}" data-availability-key="${esc(key)}" data-enabled="${next}"><span class="switch-track" aria-hidden="true"><span class="switch-knob"></span></span><span>${esc(label)}</span><small>${esc(meta|| (enabled?'In rotation':'Excluded'))}</small></button>`;
}
function renderProviderToggles(providers=[]){
  const el=$('#providerToggles');
  if(!providers.length){el.innerHTML='<div class="empty-state">No plan providers are available yet.</div>';return;}
  el.innerHTML=providers.map(p=>availabilityButton({scope:'provider',key:p.provider,enabled:!!p.enabled,label:`${p.provider} · ${p.model_count} model${p.model_count===1?'':'s'}`})).join('');
}

function fmtContext(n){
  if(n==null)return '—';
  const x=Number(n);
  if(x>=1_000_000)return `${(x/1_000_000).toFixed(x%1_000_000?2:1).replace(/\.0$/,'')}M`;
  if(x>=1_000)return `${Math.round(x/1_000)}k`;
  return fmtNum(x,0);
}
function costEvidenceBadge(kind){
  if(kind==='measured_subscription')return '<span class="badge badge-measured">measured burn</span>';
  if(kind==='measured')return '<span class="badge badge-measured">measured completion</span>';
  if(kind==='retry-adjusted')return '<span class="badge badge-measured">retry-adjusted</span>';
  return '<span class="badge badge-warning">estimated</span>';
}
function qualityEvidenceBadge(model){
  if(model.quality_evidence==='measured'){
    const sample=model.sample_size==null?'':` · n=${fmtNum(model.sample_size,0)}`;
    return `<span class="badge badge-measured">${esc(model.confidence||'measured')}${sample}</span>`;
  }
  if(model.quality_evidence==='partial')return '<span class="badge badge-warning">partial evidence</span>';
  return '<span class="badge badge-warning">prior only</span>';
}
function fmtQuotaPoint(n){
  if(n==null)return '—';
  const x=Number(n); const digits=x<0.1?3:x<1?2:1;
  return `${x.toFixed(digits)}%`;
}
function syncRecommendationBasisButtons(){
  $$('#recommendationBasisToggle [data-recommendation-basis]').forEach(b=>{const active=b.dataset.recommendationBasis===state.recommendationBasis;b.classList.toggle('is-active',active);b.setAttribute('aria-pressed',String(active));});
}
function renderTierRecommendations(payload){
  const el=$('#tierRecommendationGrid');
  const tiers=payload?.tiers||[];
  const basis=payload?.cost_basis?.key||state.recommendationBasis;
  syncRecommendationBasisButtons();
  if(!tiers.length){el.innerHTML='<div class="empty-state">No recommendation-grade plan models are available yet.</div>';return;}
  if(basis==='quota'){
    $('#recommendationBasis').textContent=`Measured weekly quota burn ranks first. API $ / completed task fills missing quota lanes as an explicit proxy.`;
  }else{
    const mix=payload.cost_basis?.mix||{};
    $('#recommendationBasis').textContent=`Ranked by API $ / completed task. Weekly quota burn remains visible when measured. API estimate basis: ${Math.round((mix.input||0)*100)}% input / ${Math.round((mix.cache_read||0)*100)}% cache / ${Math.round((mix.output||0)*100)}% output.`;
  }
  el.innerHTML=tiers.map(t=>{
    const changed=t.changed_by_availability?'<span class="badge badge-warning">refactored by availability</span>':'';
    const examples=(t.examples||[]).map(x=>`<span>${esc(x)}</span>`).join('');
    const rows=(t.top_models||[]).map((m,i)=>{
      const apiEvidence=costEvidenceBadge(m.api_cost_evidence);
      const weekly=m.weekly_burn_pct_per_completed;
      const tasksWeek=m.tasks_per_weekly_quota;
      const quotaProxy=weekly==null && m.cost_evidence==='api_proxy';
      const quotaMain=weekly==null?(quotaProxy?fmtTaskCost(m.api_cost_per_completed_task):'—'):fmtQuotaPoint(weekly);
      const quotaSub=tasksWeek==null?(quotaProxy?'API proxy; import weekly quota telemetry':'weekly telemetry needed'):`≈ ${fmtNum(tasksWeek,0)} completed tasks / weekly allowance`;
      const quotaEvidence=weekly!=null
        ? '<span class="badge badge-measured">measured quota</span>'
        : quotaProxy
          ? '<span class="badge badge-warning">API proxy · quota needed</span>'
          : '<span class="badge">quota unmeasured</span>';

      const apiMain=fmtTaskCost(m.api_cost_per_completed_task);
      const detail=m.first_pass_rate==null
        ? `${fmtContext(m.context_window)} ctx · ${esc(m.fit_reason||'recommended fit')}`
        : `${pct(m.first_pass_rate)} 1st pass${m.seconds_per_completed==null?'':` · ${fmtNum(m.seconds_per_completed,0)}s/done`}${m.five_hour_burn_pct_per_completed==null?'':` · ${fmtQuotaPoint(m.five_hour_burn_pct_per_completed)} 5h/task`}`;
      return `<div class="tier-rank-row">
        <div class="rank-number">${i+1}</div>
        <div class="rank-model">
          <strong>${esc(m.model_display_name)}</strong>
          <small>${esc(m.plan_name||'plan route')} · ${esc(m.provider)}</small>
          <div class="rank-metric">${detail}</div>
          <div class="rank-metric">Evidence: ${qualityEvidenceBadge(m)}</div>
        </div>
        <div class="rank-compare">
          <div class="rank-economy ${basis==='quota'?'is-ranking':''}">
            <span class="economy-label">${quotaProxy?'Quota proxy / task':'Weekly quota / task'}</span>
            <strong>${quotaMain}</strong>
            <small>${quotaSub}</small>
            ${quotaEvidence}
          </div>
          <div class="rank-economy ${basis==='api'?'is-ranking':''}">
            <span class="economy-label">API $ / task</span>
            <strong>${apiMain}</strong>
            <small>${m.api_cost_per_completed_task==null?'pricing unresolved':'same completed-task workload'}</small>
            ${apiEvidence}
          </div>
        </div>
      </div>`;
    }).join('') || `<div class="empty-state">${basis==='quota'?'No measured weekly quota burn for this tier yet. Switch to API ranking to see price-based picks while you collect quota telemetry.':'No enabled recommendation-grade model for this tier.'}</div>`;
    return `<article class="tier-recommendation-card tier-${t.tier}"><div class="tier-card-head"><div><span class="tier-index">T${t.tier}</span><h3>${esc(t.short_label)}</h3></div>${changed}</div><p>${esc(t.description)}</p><div class="tier-examples">${examples}</div><div class="tier-ranking">${rows}</div></article>`;
  }).join('');
}
function renderOverviewInsights(d){
  const rec=d.tier_recommendations||{}; const s=rec.summary||{}; const basis=rec.cost_basis?.key||state.recommendationBasis;
  const providers=d.availability_providers||[];
  const enabledProviders=providers.filter(p=>p.enabled).length;
  const sourceTotal=(d.sources||[]).filter(x=>Number(x.enabled)).length;
  const healthy=Math.max(0,sourceTotal-Number(s.source_failure_count||0));
  const coverageLabel=basis==='quota'?'Weekly-burn coverage':'Measured Top 3 coverage';
  const coverageValue=basis==='quota'?Math.round(Number(s.ranked_slot_coverage_pct||0)*100):Math.round(Number(s.measured_top_pick_pct||0)*100);
  const coverageDetail=basis==='quota'
    ? `${fmtNum(s.ranked_slot_count||0,0)} of ${fmtNum(s.ranked_slot_total||12,0)} Top-3 slots have comparable measured weekly burn`
    : `${fmtNum(s.measured_top_pick_count||0,0)} of ${fmtNum(s.top_pick_count||0,0)} displayed picks use observed completion data`;
  $('#overviewInsightGrid').innerHTML=`
    <article class="overview-insight"><span>Monthly stack</span><strong>${fmtMoney(d.monthly_spend)}</strong><small>${fmtMoney(d.annual_spend)} / year across enabled subscriptions</small></article>
    <article class="overview-insight"><span>${coverageLabel}</span><strong>${coverageValue}%</strong><small>${coverageDetail}</small></article>
    <article class="overview-insight"><span>Source health</span><strong>${healthy}/${sourceTotal||0}</strong><small>${Number(s.source_failure_count||0)?`${fmtNum(s.source_failure_count,0)} watcher failure${Number(s.source_failure_count)===1?'':'s'}`:'All enabled watchers healthy or not yet checked'}</small></article>
    <article class="overview-insight"><span>Models in rotation</span><strong>${enabledProviders}/${providers.length}</strong><small>${fmtNum(s.disabled_model_family_count||0,0)} recommendation-grade model families currently excluded</small></article>`;

  const tiers=rec.tiers||[];
  const estimatedLeaders=tiers.filter(t=>t.top_models?.[0]&&t.top_models[0].cost_evidence==='estimated');
  const refactored=tiers.filter(t=>t.changed_by_availability);
  const missingBurn=tiers.filter(t=>basis==='quota'&&Number(t.missing_measured_slots||0)>0);
  const notes=[];
  if(basis==='quota'&&missingBurn.length){notes.push(`<article class="recommendation-note"><span class="note-mark">01</span><div><strong>Some quota picks use an API proxy</strong><p>${missingBurn.map(t=>`${esc(t.short_label)}: ${fmtNum(t.missing_measured_slots,0)} slot${Number(t.missing_measured_slots)===1?'':'s'} need weekly-burn telemetry`).join('; ')}. These lanes remain visible and are clearly labeled until telemetry is imported.</p></div></article>`)}
  if(basis==='api'&&estimatedLeaders.length){notes.push(`<article class="recommendation-note"><span class="note-mark">01</span><div><strong>Next telemetry priority</strong><p>Measure the current #1 estimated picks: ${estimatedLeaders.map(t=>`${esc(t.short_label)} → ${esc(t.top_models[0].model_display_name)}`).join('; ')}. Those observations can materially reorder the cost/completion ranking.</p></div></article>`)}
  if(refactored.length){notes.push(`<article class="recommendation-note"><span class="note-mark">02</span><div><strong>Availability changed ${refactored.length} tier${refactored.length===1?'':'s'}</strong><p>${refactored.map(t=>esc(t.short_label)).join(', ')} no longer matches the baseline Top 3 because a model or provider is disabled.</p></div></article>`)}
  if(Number(s.source_failure_count||0)){notes.push(`<article class="recommendation-note"><span class="note-mark">03</span><div><strong>Source health can stale prices</strong><p>${fmtNum(s.source_failure_count,0)} enabled watcher${Number(s.source_failure_count)===1?' is':'s are'} failing. Existing last-known-good economics remain in use until those sources recover.</p></div></article>`)}
  if(Number(s.unacknowledged_change_count||0)){notes.push(`<article class="recommendation-note"><span class="note-mark">04</span><div><strong>Catalog or pricing changes are waiting</strong><p>${fmtNum(s.unacknowledged_change_count,0)} change${Number(s.unacknowledged_change_count)===1?'':'s'} need review in Watch Desk.</p></div></article>`)}
  if(Number(s.inferred_models_waiting_for_fit||0)){notes.push(`<article class="recommendation-note"><span class="note-mark">05</span><div><strong>New models need fit evidence</strong><p>${fmtNum(s.inferred_models_waiting_for_fit,0)} catalog/tier candidate observations are being held out of Top 3 because their workload fit is inferred rather than established.</p></div></article>`)}
  if(!notes.length){notes.push('<div class="empty-state">No active recommendation-quality issues. The current Top 3 set is stable against known availability, source and evidence checks.</div>')}
  $('#recommendationNotes').innerHTML=notes.join('');
  $('#recommendationCoverageBadge').textContent=basis==='quota'?`${coverageValue}% weekly-burn covered`:`${coverageValue}% measured`;
}
function recommendationModel(c){
  if(!c)return '<strong class="route-unavailable">No enabled measured model</strong>';
  return `<strong>${esc(c.model_display_name||c.model_key)}</strong><small>${esc(c.provider)} · ${fmtNum(c.seconds_per_completed,1)}s/done · ${pct(c.first_pass_rate)} 1st pass</small>`;
}
function renderRecommendations(recs=[]){
  const el=$('#routingGrid');
  if(!recs.length){el.innerHTML='<div class="empty-state">No measured recommendations yet.</div>';return;}
  el.innerHTML=recs.map(r=>{
    const changed=r.changed_by_availability?'<span class="badge badge-warning">refactored</span>':'';
    const disabled=r.disabled_candidates?.length?`<p class="route-disabled">Excluded: ${r.disabled_candidates.map(x=>`${esc(x.model_display_name)} (${esc(x.reason||'disabled')})`).join(', ')}</p>`:'';
    return `<article class="route-card${r.available_count===0?' is-unavailable':''}"><div class="route-card-head"><span>${esc(r.pool_name)} · ${esc(r.tier)}</span>${changed}</div><div class="route-choice"><span>Quota-first</span>${recommendationModel(r.quota_first)}</div><div class="route-choice"><span>Time / reliability</span>${recommendationModel(r.time_first)}</div>${disabled}</article>`;
  }).join('');
}
function latestLanes(lanes){
  const map=new Map(); lanes.forEach(l=>{const key=`${l.model_key}|${l.task_class}`; if(!map.has(key)||String(l.observed_at)>String(map.get(key).observed_at))map.set(key,l)});return [...map.values()];
}
function renderLanes(lanes){
  const data=latestLanes(lanes).filter(l=>l.provider==='Google');
  if(!data.length){$('#laneTableWrap').innerHTML='<div class="empty-state">No measured lanes yet. Import telemetry to begin.</div>';return;}
  $('#laneTableWrap').innerHTML=`<table class="data-table"><thead><tr><th>Lane</th><th>Tier</th><th>Done / visible 1%</th><th>1st pass</th><th>Attempts / done</th><th>Sec / done</th><th>Availability</th><th>Evidence</th></tr></thead><tbody>${data.map(l=>`<tr class="${l.available?'':'row-disabled'}"><td><strong>${esc(l.model_display_name||l.model_key)}</strong><div class="muted mono">${esc(l.pool_name||'')}</div></td><td>${esc(l.task_class.replace('Tier 2: ','T2 · ').replace('Tier 3: ','T3 · '))}</td><td class="mono">${fmtNum(l.completed_per_visible_1pct,2)}</td><td class="mono">${pct(l.first_pass_rate)}</td><td class="mono">${fmtNum(Number(l.attempts)/Math.max(1,Number(l.completed)),2)}</td><td class="mono">${fmtNum(l.seconds_per_completed,1)}</td><td>${l.available?'<span class="badge badge-measured">in rotation</span>':`<span class="badge badge-warning">excluded</span><div class="muted">${esc(l.availability_reason||'disabled')}</div>`}</td><td><span class="badge badge-measured">${esc(l.evidence_status)}</span></td></tr>`).join('')}</tbody></table>`;
}

function renderChanges(changes, failures=[]){
  const total=changes.length+failures.length;
  $('#changeCount').textContent=String(total);
  $('#dismissAllChanges').hidden=!changes.length;
  const semantic=changes.map(c=>`<article class="change-item"><div class="change-line"><strong>${esc(c.title)}</strong><button class="button button-ghost button-small" type="button" data-ack-change="${c.id}">Dismiss</button></div><p>${esc(c.detail||'')}</p><time>${esc(c.detected_at)}</time></article>`).join('');
  const operational=failures.map(s=>`<article class="change-item source-failure"><div class="change-line"><strong>${esc(s.label)} failed</strong><span class="badge badge-warning">${fmtNum(s.consecutive_failures,0)}×</span></div><p>${esc(s.last_error||'Source check failed.')}</p><div class="inline-actions"><button class="button button-outline button-small" type="button" data-source-sync="${s.id}">Retry</button><button class="button button-ghost button-small" type="button" data-source-toggle="${s.id}" data-enabled="0">Pause watcher</button><button class="button button-ghost button-small" type="button" data-open-sources="1">Source watch</button></div></article>`).join('');
  $('#changeFeed').innerHTML=(operational+semantic)||'<div class="empty-state">No changes or active source failures need attention.</div>';
}

async function loadDashboard(){
  try{
    const d=await api(`/api/dashboard?recommendation_basis=${encodeURIComponent(state.recommendationBasis)}`);state.dashboard=d;
    renderTierRecommendations(d.tier_recommendations||{});renderOverviewInsights(d);renderProviderToggles(d.availability_providers||[]);renderChanges(d.changes,d.source_failures||[]);$('#catalogCount').textContent=fmtNum(d.catalog_count,0);
    $('#lastSync').textContent=d.last_sync?`Last sync: ${d.last_sync.status} · ${d.last_sync.finished_at||d.last_sync.started_at}`:'No source sync yet';
    $('#syncInterval').value=d.settings.sync_interval_minutes;$('#redactDescriptions').checked=!!d.settings.telemetry_redact_descriptions;
  }catch(e){$('#tierRecommendationGrid').innerHTML=`<div class="error-state">${esc(e.message)}</div>`}
}

function syncModelControls(){
  const q=state.modelQuery;
  $('#modelSearch').value=q.q; $('#modelScope').value=q.scope; $('#providerFilter').value=q.provider; $('#sourceFilter').value=q.source; $('#pageSize').value=String(q.pageSize); $('#taskProfile').value=q.taskProfile; $('#clearSearch').hidden=!q.q;
}
function updateCatalogUrl(){
  const u=new URL(location.href); const q=state.modelQuery;
  for(const key of ['q','provider','source','scope','sort','direction','page','pageSize','taskProfile']) u.searchParams.delete(key);
  if(q.q)u.searchParams.set('q',q.q); if(q.provider)u.searchParams.set('provider',q.provider); if(q.source)u.searchParams.set('source',q.source);
  if(q.scope!=='plan')u.searchParams.set('scope',q.scope); if(q.sort!=='provider')u.searchParams.set('sort',q.sort); if(q.direction!=='asc')u.searchParams.set('direction',q.direction); if(q.page!==1)u.searchParams.set('page',String(q.page)); if(q.pageSize!==50)u.searchParams.set('pageSize',String(q.pageSize)); if(q.taskProfile!=='standard')u.searchParams.set('taskProfile',q.taskProfile);
  try{history.replaceState(null,'',u)}catch{}
}
function sortButton(label,key){
  const q=state.modelQuery; const active=q.sort===key; const arrow=active?(q.direction==='asc'?' ↑':' ↓'):'';
  return `<button class="sort-button${active?' is-active':''}" type="button" data-sort="${key}" aria-label="Sort by ${esc(label)}${active?`, ${q.direction}ending`:''}">${esc(label)}${arrow}</button>`;
}
function fmtTaskCost(n){
  if(n==null)return '—';
  const x=Number(n);
  const digits=x<0.01?5:x<1?3:2;
  return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:digits,maximumFractionDigits:digits}).format(x);
}
function taskCostMeta(m){
  if(m.task_cost_per_task==null)return '<div class="catalog-data catalog-data-unresolved">pricing incomplete</div>';
  const band=m.task_cost_band==='long_context'?'long-context · 2× input/cache · 1.5× output':'short-context';
  if(m.task_cost_status==='cache_at_input_rate')return `<div class="catalog-data catalog-data-partial" title="No cache-read rate was published; cache-read tokens use the normal input rate for this estimate.">${esc(band)} · cache at input rate</div>`;
  return `<div class="catalog-data catalog-data-complete">${esc(band)}</div>`;
}

function catalogDataMeta(m){
  if(state.modelQuery.scope!=='plan')return '';
  const labels={cursor_official:'Cursor official',official_baseline:'official baseline',provider_official:'provider official',litellm:'LiteLLM'};
  if(m.data_status==='unresolved')return '<div class="catalog-data catalog-data-unresolved" title="No matching catalog economics were found yet. Check Source Watch or run Sync now.">catalog data unresolved</div>';
  const bits=[];
  if(m.pricing_source)bits.push(`price: ${labels[m.pricing_source]||m.pricing_source}`);
  if(m.context_source&&m.context_source!==m.pricing_source)bits.push(`context: ${labels[m.context_source]||m.context_source}`);
  const status=m.data_status==='complete'?'complete':'partial';
  return `<div class="catalog-data catalog-data-${status}">${esc(status)}${bits.length?` · ${esc(bits.join(' · '))}`:''}</div>`;
}
function renderModelTable(models){
  if(!models.length){$('#modelsTableWrap').innerHTML='<div class="empty-state">No models match these filters.</div>';return;}
  const showAvailability=state.modelQuery.scope==='plan';
  $('#modelsTableWrap').innerHTML=`<table class="data-table"><thead><tr><th>${sortButton('Provider','provider')}</th><th>${sortButton('Model','model')}</th><th>${sortButton(showAvailability?'Plan':'Source',showAvailability?'plan':'source')}</th>${showAvailability?'<th>Routing</th>':''}<th>${sortButton('Context','context')}</th><th>${sortButton('Input / M','input')}</th><th>${sortButton('Cache read / M','cache')}</th><th>${sortButton('Output / M','output')}</th><th>${sortButton('Cost / task','task_cost')}</th><th>${sortButton('Last verified','seen')}</th></tr></thead><tbody>${models.map(m=>`<tr class="${showAvailability&&!m.available?'row-disabled':''}"><td>${esc(m.provider||'—')}</td><td><strong>${esc(m.display_name||m.external_id)}</strong><div class="muted mono">${esc(m.external_id)}</div>${m.lifecycle_status&&m.lifecycle_status!=='active'?`<div class="catalog-data catalog-data-warning">${esc(m.lifecycle_status)}${m.superseded_by?` → ${esc(m.superseded_by)}`:''}</div>`:''}${m.pool_name?`<div class="muted">${esc(m.pool_name)}</div>`:''}${catalogDataMeta(m)}</td><td><span class="badge ${showAvailability?'badge-official':m.source==='cursor_official'?'badge-official':'badge-warning'}">${esc(m.plan_name||m.source||'—')}</span></td>${showAvailability?`<td>${availabilityButton({scope:'model',key:m.external_id,enabled:!!m.model_enabled,label:m.model_enabled?'Model enabled':'Model disabled',meta:m.provider_enabled?(m.model_enabled?'In rotation':'Excluded'):'Excluded by provider'})}</td>`:''}<td class="mono">${m.context_window==null?'—':fmtNum(m.context_window,0)}</td><td class="mono">${m.input_per_million==null?'—':fmtMoney(m.input_per_million)}</td><td class="mono">${m.cache_read_per_million==null?'—':fmtMoney(m.cache_read_per_million)}</td><td class="mono">${m.output_per_million==null?'—':fmtMoney(m.output_per_million)}</td><td class="mono task-cost-cell"><strong>${fmtTaskCost(m.task_cost_per_task)}</strong>${taskCostMeta(m)}</td><td class="mono muted">${esc(((m.catalog_last_seen_at||m.last_seen_at)||'—').slice(0,19))}</td></tr>`).join('')}</tbody></table>`;
}
async function loadModels(){
  const q=state.modelQuery; updateCatalogUrl(); syncModelControls();
  const url=new URL('/api/models',document.baseURI); url.searchParams.set('scope',q.scope); url.searchParams.set('sort',q.sort); url.searchParams.set('direction',q.direction); url.searchParams.set('page',String(q.page)); url.searchParams.set('page_size',String(q.pageSize)); url.searchParams.set('task_profile',q.taskProfile); if(q.q)url.searchParams.set('q',q.q); if(q.provider)url.searchParams.set('provider',q.provider); if(q.source)url.searchParams.set('source',q.source);
  if(modelAbort)modelAbort.abort(); modelAbort=new AbortController();
  try{
    const r=await api(url,{signal:modelAbort.signal}); state.models=r.models; q.page=r.page; renderProviderToggles(r.availability_providers||[]);
    const providerCurrent=q.provider; $('#providerFilter').innerHTML='<option value="">All providers</option>'+r.providers.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join(''); $('#providerFilter').value=providerCurrent;
    const sourceCurrent=q.source; const sourceLabel=q.scope==='plan'?'All plans':'All sources'; $('#sourceFilter').innerHTML=`<option value="">${sourceLabel}</option>`+r.sources.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join(''); $('#sourceFilter').value=sourceCurrent;
    renderModelTable(r.models); const profile=r.task_cost_profile||{}; $('#taskCostBasis').textContent=`Cost/task: ${profile.label||q.taskProfile} · ${fmtNum(profile.billable_tokens,0)} billable tokens · ${Math.round((profile.mix?.input||0)*100)}% input / ${Math.round((profile.mix?.cache_read||0)*100)}% cache / ${Math.round((profile.mix?.output||0)*100)}% output · API-equivalent, not subscription cost`; $('#catalogResultCount').textContent=`${fmtNum(r.total,0)} result${r.total===1?'':'s'}`; $('#catalogSortState').textContent=`Sorted by ${q.sort} · ${q.direction}`; $('#pageStatus').textContent=`Page ${r.page} of ${r.total_pages}`; $('#prevPage').disabled=r.page<=1; $('#nextPage').disabled=r.page>=r.total_pages;
    syncModelControls(); updateCatalogUrl();
  }catch(e){ if(e.name!=='AbortError')$('#modelsTableWrap').innerHTML=`<div class="error-state">${esc(e.message)}</div>`; }
}

async function setAvailability(scope,key,enabled){
  try{
    await requestJson(`/api/availability/${scope}/${encodeURIComponent(key)}`,'PATCH',{enabled:!!enabled});
    toast(`${scope==='provider'?'Provider':'Model'} ${enabled?'returned to':'removed from'} rotation`);
    await loadDashboard();
    if(location.hash==='#models')await loadModels();
  }catch(e){toast(e.message)}
}

function sourceStatus(s){
  if(!Number(s.enabled))return '<span class="badge">paused</span>';
  if(s.last_status===200)return '<span class="badge badge-measured">healthy</span>';
  if(s.last_status===0&&s.last_checked)return '<span class="badge badge-warning">error</span>';
  return '<span class="muted">not checked</span>';
}
async function loadSources(){
  try{
    const r=await api('/api/sources');state.sources=r.sources;
    $('#sourcesTableWrap').innerHTML=r.sources.length?`<table class="data-table"><thead><tr><th>Source</th><th>Parser</th><th>Status</th><th>Last checked</th><th>Error</th><th>Controls</th></tr></thead><tbody>${r.sources.map(s=>`<tr><td><strong>${esc(s.label)}</strong><div class="muted mono">${esc(s.source_key)}</div><a class="muted source-link" href="${esc(s.url)}" target="_blank" rel="noreferrer">open source ↗</a></td><td class="mono">${esc(s.parser)}</td><td>${sourceStatus(s)}${Number(s.consecutive_failures)>0?`<div class="muted mono">${fmtNum(s.consecutive_failures,0)} consecutive</div>`:''}</td><td class="mono muted">${esc((s.last_checked||'—').slice(0,19))}</td><td class="source-error">${esc(s.last_error||'—')}</td><td><div class="inline-actions"><button class="button button-outline button-small" type="button" data-source-sync="${s.id}">Check now</button><button class="button button-ghost button-small" type="button" data-source-toggle="${s.id}" data-enabled="${Number(s.enabled)?0:1}">${Number(s.enabled)?'Pause':'Resume'}</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No source watchers configured.</div>';
  }catch(e){$('#sourcesTableWrap').innerHTML=`<div class="error-state">${esc(e.message)}</div>`}
}
async function sourceSync(id,button){
  if(button)setBusy(button,true,'Checking…');
  try{await requestJson(`/api/sources/${id}/sync`);toast('Source check complete')}catch(e){toast(e.message)}finally{if(button)setBusy(button,false);await loadSources();await loadDashboard()}
}
async function sourceToggle(id,enabled){
  try{await requestJson(`/api/sources/${id}`,'PATCH',{enabled:!!enabled});toast(enabled?'Watcher resumed':'Watcher paused');await loadSources();await loadDashboard()}catch(e){toast(e.message)}
}
async function ackChange(id){ try{await requestJson(`/api/changes/${id}/ack`);await loadDashboard()}catch(e){toast(e.message)} }
async function ackAll(){ try{await requestJson('/api/changes/ack-all');toast('Watch Desk alerts dismissed');await loadDashboard()}catch(e){toast(e.message)} }

async function loadRuns(){
  try{const r=await api('/api/telemetry/runs');state.runs=r.runs;$('#telemetryRuns').innerHTML=r.runs.length?r.runs.map(x=>`<article class="run-item"><div><strong>${esc(x.file_name||x.source)}</strong><small>${esc(x.imported_at)}</small></div><span class="badge badge-measured">${fmtNum(x.row_count,0)} rows</span></article>`).join(''):'<div class="empty-state">No imported telemetry yet.</div>'}catch(e){$('#telemetryRuns').innerHTML=`<div class="error-state">${esc(e.message)}</div>`}
}
async function syncNow(){const b=$('#syncBtn');setBusy(b,true,'Syncing…');$('#syncState').textContent='Checking catalogs and official sources…';try{const r=await api('/api/sync',{method:'POST'});toast(r.status==='ok'?'Source sync complete':'Sync completed with some source errors');await loadDashboard();if(location.hash==='#models')await loadModels();if(location.hash==='#sources')await loadSources()}catch(e){toast(e.message)}finally{setBusy(b,false);$('#syncState').textContent='Ready'}}

$$('.tab').forEach(t=>t.addEventListener('click',()=>showView(t.dataset.view)));
$('#syncBtn').addEventListener('click',syncNow);
$('#dismissAllChanges').addEventListener('click',ackAll);
$('#recommendationBasisToggle').addEventListener('click',e=>{const b=e.target.closest('[data-recommendation-basis]');if(!b)return;const basis=b.dataset.recommendationBasis;if(!['api','quota'].includes(basis)||basis===state.recommendationBasis)return;state.recommendationBasis=basis;localStorage.setItem('burn-ledger-recommendation-basis',basis);syncRecommendationBasisButtons();loadDashboard();});
$('#changeFeed').addEventListener('click',e=>{const ack=e.target.closest('[data-ack-change]');if(ack){ackChange(ack.dataset.ackChange);return}const sync=e.target.closest('[data-source-sync]');if(sync){sourceSync(sync.dataset.sourceSync,sync);return}const toggle=e.target.closest('[data-source-toggle]');if(toggle){sourceToggle(toggle.dataset.sourceToggle,Number(toggle.dataset.enabled));return}if(e.target.closest('[data-open-sources]'))showView('sources')});
$('#sourcesTableWrap').addEventListener('click',e=>{const sync=e.target.closest('[data-source-sync]');if(sync){sourceSync(sync.dataset.sourceSync,sync);return}const toggle=e.target.closest('[data-source-toggle]');if(toggle)sourceToggle(toggle.dataset.sourceToggle,Number(toggle.dataset.enabled))});
$('#modelsTableWrap').addEventListener('click',e=>{const availability=e.target.closest('[data-availability-scope]');if(availability){setAvailability(availability.dataset.availabilityScope,availability.dataset.availabilityKey,Number(availability.dataset.enabled));return}const b=e.target.closest('[data-sort]');if(!b)return;const key=b.dataset.sort;if(state.modelQuery.sort===key)state.modelQuery.direction=state.modelQuery.direction==='asc'?'desc':'asc';else{state.modelQuery.sort=key;state.modelQuery.direction='asc'}state.modelQuery.page=1;loadModels()});
$('#providerToggles').addEventListener('click',e=>{const b=e.target.closest('[data-availability-scope]');if(b)setAvailability(b.dataset.availabilityScope,b.dataset.availabilityKey,Number(b.dataset.enabled))});
$('#modelSearch').addEventListener('input',()=>{clearTimeout(searchTimer);state.modelQuery.q=$('#modelSearch').value;$('#clearSearch').hidden=!state.modelQuery.q;searchTimer=setTimeout(()=>{state.modelQuery.page=1;loadModels()},300)});
$('#clearSearch').addEventListener('click',()=>{$('#modelSearch').value='';state.modelQuery.q='';state.modelQuery.page=1;$('#clearSearch').hidden=true;$('#modelSearch').focus();loadModels()});
$('#modelScope').addEventListener('change',()=>{state.modelQuery.scope=$('#modelScope').value;state.modelQuery.provider='';state.modelQuery.source='';state.modelQuery.page=1;loadModels()});
$('#providerFilter').addEventListener('change',()=>{state.modelQuery.provider=$('#providerFilter').value;state.modelQuery.page=1;loadModels()});
$('#sourceFilter').addEventListener('change',()=>{state.modelQuery.source=$('#sourceFilter').value;state.modelQuery.page=1;loadModels()});
$('#pageSize').addEventListener('change',()=>{state.modelQuery.pageSize=Number($('#pageSize').value);state.modelQuery.page=1;loadModels()});
$('#taskProfile').addEventListener('change',()=>{state.modelQuery.taskProfile=$('#taskProfile').value;state.modelQuery.page=1;loadModels()});
$('#prevPage').addEventListener('click',()=>{if(state.modelQuery.page>1){state.modelQuery.page-=1;loadModels()}});
$('#nextPage').addEventListener('click',()=>{state.modelQuery.page+=1;loadModels()});
$('#uploadForm').addEventListener('submit',async e=>{e.preventDefault();const input=$('#telemetryFile');if(!input.files?.length){$('#uploadResult').textContent='Choose a CSV or JSONL file first.';input.focus();return}const b=$('#uploadBtn');setBusy(b,true,'Importing…');const fd=new FormData();fd.append('file',input.files[0]);try{const r=await api('/api/telemetry/import',{method:'POST',body:fd});$('#uploadResult').textContent=`Imported ${r.rows} attempts. Computed ${r.metrics.length} lane summaries.`;toast('Telemetry imported');await loadDashboard();await loadRuns()}catch(err){$('#uploadResult').textContent=err.message}finally{setBusy(b,false)}});
$('#settingsForm').addEventListener('submit',async e=>{e.preventDefault();const payload={sync_interval_minutes:Number($('#syncInterval').value),telemetry_redact_descriptions:$('#redactDescriptions').checked};try{await api('/api/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});toast('Settings saved')}catch(err){toast(err.message)}});

const params=new URLSearchParams(location.search);
state.modelQuery.q=params.get('q')||''; state.modelQuery.provider=params.get('provider')||''; state.modelQuery.source=params.get('source')||''; state.modelQuery.scope=['plan','official','all'].includes(params.get('scope'))?params.get('scope'):'plan'; state.modelQuery.sort=params.get('sort')||'provider'; state.modelQuery.direction=params.get('direction')==='desc'?'desc':'asc'; state.modelQuery.page=Math.max(1,Number(params.get('page')||1)); state.modelQuery.pageSize=[25,50,100].includes(Number(params.get('pageSize')))?Number(params.get('pageSize')):50; state.modelQuery.taskProfile=['micro','standard','long_horizon','massive_context'].includes(params.get('taskProfile'))?params.get('taskProfile'):'standard';
syncModelControls();syncRecommendationBasisButtons();
const initial=(location.hash||'#overview').slice(1);showView(['overview','models','sources','telemetry','settings'].includes(initial)?initial:'overview');loadDashboard();
