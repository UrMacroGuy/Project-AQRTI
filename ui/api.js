/**
 * AQRTI API Layer — Live Mode
 * All data comes from FastAPI backend at localhost:8000.
 * Falls back gracefully to empty/null when endpoint unavailable.
 */

const API_CONFIG = {
  BASE:     'http://localhost:8000/api/v1',
  ADMIN:    'http://localhost:8000/admin',
  TIMEOUT:  10000,
};

// Markov module runs as its own standalone backend process (backend/markov/app.py),
// on its own port — genuinely separate from the main backend above.
const MARKOV_API_CONFIG = {
  BASE:    'http://localhost:8001/api/v1/markov',
  TIMEOUT: 10000,
};


// ── Local Data Cache ─────────────────────────────────────────
// Stores last-known API responses so panels show stale data when backend is offline
const _cache = {
  PREFIX: 'aqrti_cache_',
  TTL: 60 * 1000, // 60s — short enough to stay fresh for a real session

  set(key, data) {
    try {
      localStorage.setItem(this.PREFIX + key, JSON.stringify({ data, ts: Date.now() }));
    } catch (_) { console.warn('[AQRTI Cache] set failed:', _.message); }
  },

  get(key) {
    try {
      const raw = localStorage.getItem(this.PREFIX + key);
      if (!raw) return null;
      const { data, ts } = JSON.parse(raw);
      if (Date.now() - ts > this.TTL) return null;
      return data;
    } catch (_) { console.warn('[AQRTI Cache] get failed:', _.message); return null; }
  },
};

// ── Fetch Helper ──────────────────────────────────────────────
async function apiFetch(endpoint, params = {}) {
  const url = new URL(`${API_CONFIG.BASE}${endpoint}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));

  // Cache key = endpoint + sorted params (ignore page/limit for cache hits)
  const cacheKey = endpoint.replace(/\//g, '_');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT);

  try {
    const res = await fetch(url.toString(), { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Cache successful responses for offline fallback
    if (data) _cache.set(cacheKey, data);
    return data;
  } catch (err) {
    clearTimeout(timer);
    console.warn(`[AQRTI API] ${endpoint} failed:`, err.message);
    // Return last cached data if available
    const cached = _cache.get(cacheKey);
    if (cached) {
      console.info(`[AQRTI API] Using cached data for ${endpoint}`);
      return cached;
    }
    return null;
  }
}

async function apiPost(endpoint, body = {}) {
  try {
    const res = await fetch(`${API_CONFIG.BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(API_CONFIG.TIMEOUT),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[AQRTI API POST] ${endpoint} failed:`, err.message);
    return null;
  }
}

// ── Markov backend (separate process/port) fetch helpers ──────
// Deliberately not sharing _cache/apiFetch's localStorage keys with the main
// backend — a stale Markov response should never be mistaken for main-backend
// data or vice versa.
async function markovFetch(endpoint, params = {}) {
  const url = new URL(`${MARKOV_API_CONFIG.BASE}${endpoint}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  try {
    const res = await fetch(url.toString(), { signal: AbortSignal.timeout(MARKOV_API_CONFIG.TIMEOUT) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[Markov API] ${endpoint} failed:`, err.message);
    return null;
  }
}

async function markovPost(endpoint, body = {}) {
  try {
    const res = await fetch(`${MARKOV_API_CONFIG.BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(MARKOV_API_CONFIG.TIMEOUT),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[Markov API POST] ${endpoint} failed:`, err.message);
    return null;
  }
}

async function apiPostRaw(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(API_CONFIG.TIMEOUT),
  });
  if (!res.ok) {
    let detail = '';
    try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
    throw new Error(`HTTP ${res.status}${detail ? ': ' + detail : ''}`);
  }
  return await res.json();
}


// ── API object (used by most of app.js) ──────────────────────
const Api = {

  async overview()                      { return apiFetch('/overview'); },
  async market()                        { return apiFetch('/market'); },
  async topbarPrices() {
    // Fast: only 4 symbols, server-side cached 4s — ideal for 5s polling
    const url = `${API_CONFIG.BASE}/market/topbar`;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await fetch(url, { signal: ctrl.signal });
      clearTimeout(t);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) { clearTimeout(t); console.warn('[AQRTI] /market/topbar failed:', e.message); return null; }
  },
  async liveStockPrices() {
    // 18-stock universe live prices (60s server cache)
    const url = `${API_CONFIG.BASE}/market/live/stocks`;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 30000);
    try {
      const res = await fetch(url, { signal: ctrl.signal });
      clearTimeout(t);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) { clearTimeout(t); console.warn('[AQRTI] /market/live/stocks failed:', e.message); return null; }
  },
  async predictions(p = {})            { return apiFetch('/predictions', p); },
  async news(p = {})                    { return apiFetch('/news', p); },
  async newsStats()                     { return apiFetch('/news/stats'); },
  async sentiment()                     { return apiFetch('/sentiment'); },
  async strategies(p = {})             { return apiFetch('/strategies', p); },
  async strategyStats()                 { return apiFetch('/strategies/stats'); },
  async learning(p = {})               { return apiFetch('/learning', p); },
  async risk()                          { return apiFetch('/risk'); },
  async tradeReconciliation()           { return apiFetch('/reconciliation/trades'); },
  async portfolio()                     { return apiFetch('/portfolio'); },
  async marketRegime()                  { return apiFetch('/market-regime'); },
  async symbolPrediction(sym)          { return apiFetch(`/predictions/symbol/${sym}`); },
  async symbolConfidence(sym, days=30) { return apiFetch(`/confidence/symbol/${sym}`, { days }); },
  async symbolPattern(sym)             { return apiFetch(`/patterns/symbol/${sym}`); },

  // Paper trading
  async paperPortfolio()               { return apiFetch('/paper-portfolio'); },
  async paperPositions()               { return apiFetch('/paper-portfolio/positions'); },
  async paperAllocation(method = 'confidence_weighted') { return apiFetch('/paper-portfolio/allocation', { method }); },
  async paperTrades(limit = 100)       { return apiFetch('/paper-trades', { limit }); },
  async paperTradeStats()              { return apiFetch('/paper-trades/stats'); },
  async performance()                  { return apiFetch('/performance'); },
  async performanceSummary()           { return apiFetch('/performance/summary'); },
  async equityCurve(days = 90)         { return apiFetch('/equity-curve', { days }); },
  async backfillEquity()               { return apiPost('/paper-portfolio/backfill-equity'); },

  // Learning engine
  async failures(p = {})              { return apiFetch('/failures', p); },
  async failureSummary(days = 30)     { return apiFetch('/failures/summary', { days }); },
  async knowledgeOverview(days = 30)  { return apiFetch('/knowledge', { days }); },
  async knowledgeScoreHistory(days=90){ return apiFetch('/knowledge/score/history', { days }); },
  async symbolKnowledge(sym, days=90) { return apiFetch(`/knowledge/graph/symbol/${sym}`, { days }); },
  async marketKnowledge(days = 30)    { return apiFetch('/knowledge/graph/market', { days }); },
  async modelPerformance(days = 30)   { return apiFetch('/drift/performance', { days }); },
  async weightRecommendation(task='direction', days=30) { return apiFetch('/drift/weights', { task, days }); },
  async featureIntelligence(days=30)  { return apiFetch('/feature-intelligence', { days }); },
  async featureDecay(days = 30)       { return apiFetch('/feature-intelligence/decay', { days }); },
  async topFeatures(days=30, topN=20) { return apiFetch('/feature-intelligence/importance', { days, top_n: topN }); },
  async lessonSummary(days = 30)      { return apiFetch('/lessons/summary', { days }); },

  // Strategy research
  async strategyPopulation()          { return apiFetch('/strategies/population'); },
  async strategyLeaderboard(topN=15, status=null) {
    const p = { top_n: topN };
    if (status) p.status = status;
    return apiFetch('/strategies/leaderboard', p);
  },
  async strategyDetail(id)            { return apiFetch(`/strategies/${id}`); },
  async evolutionTree(days = 90)      { return apiFetch('/strategy-evolution/tree', { days }); },
  async familySurvival()              { return apiFetch('/strategy-evolution/family-survival'); },
  async regimeAffinity()              { return apiFetch('/strategy-evolution/regime-affinity'); },
  async graveyard(p = {})            { return apiFetch('/graveyard', p); },
  async graveyardSummary()            { return apiFetch('/graveyard/summary'); },
  async resurrectionCandidates()      { return apiFetch('/graveyard/resurrection-candidates'); },
  async researchReports(p = {})       { return apiFetch('/research', p); },
  async latestResearch()              { return apiFetch('/research/latest'); },

  // Research ops / agents
  async agents()                      { return apiFetch('/agents'); },
  async agentDetail(id)               { return apiFetch(`/agents/${id}`); },
  async agentMessages(days = 2)       { return apiFetch('/agents/messages/all', { days }); },
  async agentMessageSummary(days = 7) { return apiFetch('/agents/messages/summary', { days }); },
  async agentPerformance(days = 30)   { return apiFetch('/agents/performance/stats', { days }); },
  async todayBrief()                  { return apiFetch('/research-briefs/today'); },
  async briefList(limit = 30)         { return apiFetch('/research-briefs', { limit }); },
  async researchFindings(p = {})      { return apiFetch('/research-findings', p); },
  async findingsSummary(days = 7)     { return apiFetch('/research-findings/summary', { days }); },
  async taskStats(days = 7)           { return apiFetch('/research-findings/tasks/stats', { days }); },

  // Vault
  async vaultSnapshot(date)           { return apiFetch(`/vault/snapshots/${date}`); },
  async archivePredictions(days=30, symbol=null) {
    const p = { days };
    if (symbol) p.symbol = symbol;
    return apiFetch('/archives/predictions', p);
  },
  async archiveStrategies(days = 30)  { return apiFetch('/archives/strategies', { days }); },

  // Data supremacy
  async corporateSummary(days = 30)  { return apiFetch('/corporate/summary', { days }); },
  async optionsHistory(sym='NIFTY', days=30) { return apiFetch('/options-intelligence/history', { symbol: sym, days }); },
  async marketBreadth()              { return apiFetch('/market-breadth'); },
  async earningsSummary(days = 90)   { return apiFetch('/earnings/summary', { days }); },

  // Intelligence lab
  async regimeDatasets()             { return apiFetch('/regime-datasets'); },
  async metaLearning(limit = 20)     { return apiFetch('/meta-learning', { limit }); },
  async featureProposals()           { return apiFetch('/feature-proposals'); },
  async modelMemory()                { return apiFetch('/model-memory'); },
  async strategyMemory()             { return apiFetch('/strategy-memory'); },
  async researchMemoryLatest()       { return apiFetch('/research-memory/latest'); },
  async failurePatterns()            { return apiFetch('/failure-patterns'); },
  async predictionPatterns()         { return apiFetch('/prediction-patterns'); },
  async replayHistory()              { return apiFetch('/replay/history'); },

  // Admin triggers (POST to /admin/* — no /api/v1 prefix)
  async triggerTraining()            { return apiPostRaw(`${API_CONFIG.ADMIN}/train`); },
  async triggerPredictions()         { return apiPostRaw(`${API_CONFIG.ADMIN}/predict`); },
  async triggerIngestion()           { return apiPostRaw(`${API_CONFIG.ADMIN}/ingest`); },
  async triggerPaperTrade()          { return apiPostRaw(`${API_CONFIG.ADMIN}/paper-trade`); },
  async triggerLearning()            { return apiPostRaw(`${API_CONFIG.ADMIN}/learning`); },
  async triggerStrategyResearch()    { return apiPostRaw(`${API_CONFIG.ADMIN}/strategy-research`); },
  async triggerIntelligence()        { return apiPostRaw(`${API_CONFIG.ADMIN}/intelligence`); },
  async runLearningLoop(days = 7)    { return apiPost(`/learning/run?days=${days}`); },
  async triggerEvolve(n = 20)        { return apiPost(`/strategies/admin/evolve?n_offspring=${n}`); },
  async activateStrategy(id)         { return apiPost(`/strategies/${id}/activate`); },
  async retireStrategy(id, reason = 'manual_retirement') { return apiPost(`/strategies/${id}/retire?reason=${reason}`); },
  async runAgent(id)                 { return apiPost(`/agents/${id}/run`); },
  async resolveFailure(id)           { return apiPost(`/failures/${id}/resolve`); },
  async applyLesson(id)              { return apiPost(`/lessons/${id}/apply`); },
  async executeRebalance()           { return apiPost('/rebalance/execute'); },
  async approveFeatureProposal(pid)  { return apiPost(`/feature-proposals/${pid}/approve`); },
  async runFeatureDiscovery()        { return apiPost('/feature-proposals/discover'); },
  async runMetaLearning()            { return apiPost('/meta-learning/run'); },
  async triggerReplay(body = {})     { return apiPost('/replay', body); },
  async runIntelligencePipeline()    { return apiPostRaw('http://localhost:8000/admin/intelligence'); },

  async researchSynthesisLatest()      { return apiFetch('/research-synthesis/latest'); },
  async researchSynthesisSymbol(sym, days = 30) { return apiFetch(`/research-synthesis/${sym}`, { days }); },

  async correlationMatrix(days = 60) { return apiFetch('/market/correlation', { days }); },
  async sectorBreadth() { return apiFetch('/market/breadth/by-sector'); },
  async stressTestRun(niftyShock = -10, sectorShock = null, sectorShockPct = -15) {
    const p = { nifty_shock_pct: niftyShock };
    if (sectorShock) { p.sector_shock = sectorShock; p.sector_shock_pct = sectorShockPct; }
    return apiPost('/stress-test/run?' + new URLSearchParams(p).toString());
  },
  async stressTestPresets()              { return apiFetch('/stress-test/presets'); },

  // ── Historical Backtest ────────────────────────────────────────
  async runBacktest(strategyId = null, years = 2) {
    const params = years !== 2 ? `?years=${years}` : '';
    const path   = strategyId
      ? `/paper-portfolio/backtest?strategy_id=${strategyId}${years !== 2 ? `&years=${years}` : ''}`
      : `/paper-portfolio/backtest${params}`;
    return apiPost(path);
  },
  async backtestStatus(strategyId = null) {
    const path = strategyId
      ? `/paper-portfolio/backtest/status?strategy_id=${strategyId}`
      : '/paper-portfolio/backtest/status';
    return apiFetch(path);
  },

  // ── Arena ──────────────────────────────────────────────────────
  async arenaStatus()          { return apiFetch('/arena'); },
  async arenaChampions()       { return apiFetch('/arena/champions'); },
  async arenaRuns(limit = 100, status = 'all') {
    return apiFetch('/arena/runs', { limit, status });
  },
  async arenaEquity(strategyId) { return apiFetch(`/arena/equity/${strategyId}`); },
  async triggerArena()         { return apiPost('/arena/run'); },
  async arenaPromote()         { return apiPost('/arena/promote'); },
  async arenaNeedsReview()     { return apiFetch('/arena/needs-review'); },
  async arenaRetryReview(strategyId) { return apiPost(`/arena/needs-review/${strategyId}/retry`); },

  async checkBackend() {
    try {
      const res = await fetch('http://localhost:8000/health', { signal: AbortSignal.timeout(2000) });
      return res && res.ok;
    } catch { return false; }
  },

  // Strategy DNA + trade recommendations
  async strategyDna(id)               { return apiFetch(`/strategies/${id}/dna`); },
  async tradeRecommendations()        { return apiFetch('/strategies/recommendations'); },
  async runValidationSweep(days = 90) { return apiPost(`/strategy-performance/validate?days=${days}`); },
  async strategyValidation(id)        { return apiFetch(`/strategy-performance/${id}/validation`); },
  async rescoreStrategies()           { return apiPost('/strategies/admin/rescore'); },

  // Meta-learning
  async metaState()                   { return apiFetch('/strategy-evolution/meta-state'); },
  async runMetaLearning()             { return apiPost('/strategy-evolution/meta-learn'); },

  // Model self-improvement
  async modelRetrainStatus()          { return apiFetch('/models/retrain-status'); },
  async triggerModelRetrain(force = false) { return apiPost(`/models/retrain?force=${force}`); },

  // Global universe
  async universeSummary()             { return apiFetch('/universe/summary'); },
  async universeList(region = 'all', sector = 'all') { return apiFetch(`/universe/list?region=${region}&sector=${sector}`); },
  async universeRegions()             { return apiFetch('/universe/regions'); },
  async seedUniverse()                { return apiPost('/universe/seed'); },
  async downloadUniverse(years = 3, region = 'all', workers = 4) {
    return apiPost(`/universe/download?years=${years}&region=${region}&workers=${workers}`);
  },
  async universeDownloadStatus()      { return apiFetch('/universe/status'); },
  async systemHealth()                { return apiFetch('/system-health'); },
  async systemRestartLog()            { return apiFetch('/system/restart-log'); },

  // ── Go/No-Go Scorecard ────────────────────────────────────────
  async goNogo()          { return apiFetch('/go-nogo'); },
  async goNogoUptimeLog() { return apiFetch('/go-nogo/uptime-log'); },
  async goNogoRiskRails()     { return apiFetch('/go-nogo/risk-rails'); },
  async goNogoMonthlyReview() { return apiFetch('/go-nogo/monthly-review'); },

  // ── GO-7: Morning Decision Screen ─────────────────────────────
  async morningDecision() { return apiFetch('/morning/decision'); },
  async morningAct(strategyId, symbol, action, note) {
    return apiPost('/morning/act', { strategy_id: strategyId, symbol, action, note });
  },
  async morningActLog(limit) { return apiFetch('/morning/act-log', { limit }); },

  // ── Markov regime module — separate backend process, port 8001 ─
  async markovStatus()  { return markovFetch('/status'); },
  async markovRefresh() { return markovPost('/refresh'); },
  async markovWatchlist()               { return markovFetch('/watchlist'); },
  async markovWatchlistAdd(symbol)      { return markovPost(`/watchlist/add?symbol=${symbol}`); },
  async markovWatchlistRemove(symbol)   { return markovPost(`/watchlist/remove?symbol=${symbol}`); },
  async markovStrategies(family)        { return markovFetch('/strategies', family ? { family } : {}); },
  async markovGenerateStrategies(symbol, n = 20) {
    return markovPost(`/strategies/generate?symbol=${symbol}&n=${n}`);
  },
};

// ── Legacy uppercase API shim (used in intelligence-lab + replay) ──
// Maps API.get(url) / API.post(url, body) → apiFetch / apiPost
const API = {
  async get(url) {
    // strip base prefix if present, else use raw path after /api/v1
    const path = url.replace(/^https?:\/\/localhost:\d+\/api\/v1/, '').replace(/^\/api\/v1/, '');
    return apiFetch(path);
  },
  async post(url, body = {}) {
    const isAbsolute = url.startsWith('http');
    if (isAbsolute) return apiPostRaw(url, body);
    const path = url.replace(/^\/api\/v1/, '');
    return apiPost(path, body);
  },
};


// ── Connection Status Banner ──────────────────────────────────
async function initConnectionBanner() {
  const alive = await Api.checkBackend();
  const sysLabel = document.getElementById('sys-status-label');

  if (!alive) {
    const banner = document.createElement('div');
    banner.style.cssText = `
      position: fixed; bottom: 16px; right: 16px; z-index: 9999;
      background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4);
      color: #ef4444; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
      padding: 8px 14px; border-radius: 6px; letter-spacing: 0.06em;
    `;
    banner.textContent = '[!] BACKEND OFFLINE — start the backend server';
    document.body.appendChild(banner);
    if (sysLabel) sysLabel.textContent = 'BACKEND OFFLINE';
  } else {
    if (sysLabel) sysLabel.textContent = 'LIVE';
  }
}

window.addEventListener('DOMContentLoaded', initConnectionBanner);
