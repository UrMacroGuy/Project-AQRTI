/**
 * AQRTI API Layer — Live Mode
 * All data comes from FastAPI backend at localhost:8000.
 * Falls back gracefully to empty/null when endpoint unavailable.
 */

const API_CONFIG = {
  USE_MOCK: false,
  BASE:     'http://localhost:8000/api/v1',
  TIMEOUT:  10000,
};


// ── Fetch Helper ──────────────────────────────────────────────
async function apiFetch(endpoint, params = {}) {
  const url = new URL(`${API_CONFIG.BASE}${endpoint}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT);

  try {
    const res = await fetch(url.toString(), { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    clearTimeout(timer);
    console.warn(`[AQRTI API] ${endpoint} failed:`, err.message);
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

async function apiPostRaw(url, body = {}) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(API_CONFIG.TIMEOUT),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[AQRTI API POST RAW] ${url} failed:`, err.message);
    return null;
  }
}


// ── API object (used by most of app.js) ──────────────────────
const Api = {

  async overview()                      { return apiFetch('/overview'); },
  async market()                        { return apiFetch('/market'); },
  async predictions(p = {})            { return apiFetch('/predictions', p); },
  async news(p = {})                    { return apiFetch('/news', p); },
  async newsStats()                     { return apiFetch('/news/stats'); },
  async sentiment()                     { return apiFetch('/sentiment'); },
  async strategies(p = {})             { return apiFetch('/strategies', p); },
  async strategyStats()                 { return apiFetch('/strategies/stats'); },
  async models(p = {})                  { return apiFetch('/models', p); },
  async modelStats()                    { return apiFetch('/models/stats'); },
  async modelMetrics(p = {})           { return apiFetch('/models/metrics', p); },
  async walkForwardFolds(p = {})       { return apiFetch('/models/walk-forward', p); },
  async learning(p = {})               { return apiFetch('/learning', p); },
  async risk()                          { return apiFetch('/risk'); },
  async portfolio()                     { return apiFetch('/portfolio'); },
  async marketRegime()                  { return apiFetch('/market-regime'); },
  async predictionSummary()            { return apiFetch('/predictions/summary'); },
  async symbolPrediction(sym)          { return apiFetch(`/predictions/symbol/${sym}`); },
  async confidence(p = {})             { return apiFetch('/confidence', p); },
  async symbolConfidence(sym, days=30) { return apiFetch(`/confidence/symbol/${sym}`, { days }); },
  async patterns(p = {})               { return apiFetch('/patterns', p); },
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
  async rebalancePreview()             { return apiFetch('/rebalance'); },

  // Learning engine
  async learningOverview(days = 30)   { return apiFetch('/learning', { days }); },
  async failures(p = {})              { return apiFetch('/failures', p); },
  async failureSummary(days = 30)     { return apiFetch('/failures/summary', { days }); },
  async knowledgeOverview(days = 30)  { return apiFetch('/knowledge', { days }); },
  async knowledgeScoreHistory(days=90){ return apiFetch('/knowledge/score/history', { days }); },
  async symbolKnowledge(sym, days=90) { return apiFetch(`/knowledge/graph/symbol/${sym}`, { days }); },
  async marketKnowledge(days = 30)    { return apiFetch('/knowledge/graph/market', { days }); },
  async driftSummary(days = 90)       { return apiFetch('/drift', { days }); },
  async modelPerformance(days = 30)   { return apiFetch('/drift/performance', { days }); },
  async weightRecommendation(task='direction', days=30) { return apiFetch('/drift/weights', { task, days }); },
  async featureIntelligence(days=30)  { return apiFetch('/feature-intelligence', { days }); },
  async featureRanking(days = 30)     { return apiFetch('/feature-intelligence/ranking', { days }); },
  async featureDecay(days = 30)       { return apiFetch('/feature-intelligence/decay', { days }); },
  async topFeatures(days=30, topN=20) { return apiFetch('/feature-intelligence/importance', { days, top_n: topN }); },
  async lessons(p = {})               { return apiFetch('/lessons', p); },
  async lessonSummary(days = 30)      { return apiFetch('/lessons/summary', { days }); },
  async calibrationCurve(days = 30)   { return apiFetch('/lessons/calibration', { days }); },

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
  async vaultSummary()                { return apiFetch('/vault/summary'); },
  async vaultSnapshots(days = 30)     { return apiFetch('/vault/snapshots', { days }); },
  async vaultSnapshot(date)           { return apiFetch(`/vault/snapshots/${date}`); },
  async replayDate(date)              { return apiFetch(`/replay/${date}`); },
  async archivePredictions(days=30, symbol=null) {
    const p = { days };
    if (symbol) p.symbol = symbol;
    return apiFetch('/archives/predictions', p);
  },
  async archivePortfolio(days = 90)   { return apiFetch('/archives/portfolio', { days }); },
  async archiveStrategies(days = 30)  { return apiFetch('/archives/strategies', { days }); },
  async archiveKnowledge(days = 90)   { return apiFetch('/archives/knowledge', { days }); },
  async archiveResearch(days=30, archiveType=null) {
    const p = { days };
    if (archiveType) p.archive_type = archiveType;
    return apiFetch('/archives/research', p);
  },
  async vaultBriefs()                 { return apiFetch('/vault-briefs'); },
  async listBackups()                 { return apiFetch('/backups'); },

  // Data supremacy
  async corporateFilings(p = {})     { return apiFetch('/corporate', p); },
  async corporateSummary(days = 30)  { return apiFetch('/corporate/summary', { days }); },
  async fiiDii(days = 30)            { return apiFetch('/fii-dii', { days }); },
  async optionsSnapshot(sym = 'NIFTY'){ return apiFetch('/options-intelligence', { symbol: sym }); },
  async optionsHistory(sym='NIFTY', days=30) { return apiFetch('/options-intelligence/history', { symbol: sym, days }); },
  async marketBreadth()              { return apiFetch('/market-breadth'); },
  async marketBreadthHistory(days=30){ return apiFetch('/market-breadth/history', { days }); },
  async sectorRotation()             { return apiFetch('/sector-rotation'); },
  async earningsCalendar(ahead = 14) { return apiFetch('/earnings/calendar', { days_ahead: ahead }); },
  async earningsSummary(days = 90)   { return apiFetch('/earnings/summary', { days }); },
  async dataQuality(days = 7)        { return apiFetch('/data-quality', { days }); },
  async sourceHealth()               { return apiFetch('/data-quality/source-health'); },

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

  // Admin triggers (POST to /admin/*)
  async triggerTraining()            { return apiPostRaw('http://localhost:8000/admin/train'); },
  async triggerPredictions()         { return apiPostRaw('http://localhost:8000/admin/predict'); },
  async triggerIngestion()           { return apiPostRaw('http://localhost:8000/admin/ingest'); },
  async triggerPaperTrade()          { return apiPostRaw('http://localhost:8000/admin/paper-trade'); },
  async triggerLearning()            { return apiPostRaw('http://localhost:8000/admin/learning'); },
  async triggerStrategyResearch()    { return apiPostRaw('http://localhost:8000/admin/strategy-research'); },
  async triggerVault()               { return apiPostRaw('http://localhost:8000/admin/vault'); },
  async triggerDataSupremacy()       { return apiPostRaw('http://localhost:8000/admin/data-supremacy'); },
  async triggerIntelligence()        { return apiPostRaw('http://localhost:8000/admin/intelligence'); },
  async agentPipeline()              { return apiPostRaw('http://localhost:8000/admin/agent-pipeline'); },
  async generateBrief()              { return apiPost('/research-briefs/generate'); },
  async runBackup()                  { return apiPost('/backups/run'); },
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

  async checkBackend() {
    try {
      const res = await fetch('http://localhost:8000/health', { signal: AbortSignal.timeout(2000) });
      return res && res.ok;
    } catch { return false; }
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
