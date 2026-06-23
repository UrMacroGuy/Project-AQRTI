# PROJECT AQRTI — Phase 1 Complete
## Intelligence Terminal: Architecture, Component Map & Backend Integration Plan

Version: 1.0 — Phase 1 UI Shell
Date: 22 June 2026

---

## FOLDER STRUCTURE

```
Project AQRTI/
├── ui/
│   ├── index.html          ← Shell: layout, nav, all 9 page sections
│   ├── style.css           ← Terminal design system: colors, layout, components
│   └── app.js              ← Data, charts, renderers, navigation logic
├── package.json            ← npm scripts: start, dev, build
├── PROJECT_SUMMARY.md      ← This file
└── [spec docs].md          ← AQRTI architecture documentation
```

---

## ARCHITECTURE EXPLANATION

### Design Philosophy
The terminal is built as a **single-page application** with no framework dependencies.
Vanilla JS + Chart.js only. This keeps it fast, auditable, and easy to connect to a Python/FastAPI backend later.

### Three-Layer Architecture

```
index.html          → Structure Layer
    ↓
style.css           → Presentation Layer (CSS custom properties = design tokens)
    ↓
app.js              → Logic Layer
    ├── DataStore   → Centralized mock data (mirrors future API schemas)
    ├── ChartRegistry → Prevents canvas reuse errors; owns all Chart.js instances
    ├── Page Renderers → One function per page, fully independent
    └── Navigation  → Lazy rendering: pages only rendered on first visit
```

### Key Architectural Decisions

1. **Lazy Rendering**: Pages render on first navigation, not on load. Prevents 9x chart initialization on startup.
2. **ChartRegistry**: Every chart is registered by canvas ID. Re-navigating to a page destroys and recreates the chart cleanly.
3. **DataStore**: All mock data lives in one module-scoped object. Replacing each property with an API call requires changing one line per data type.
4. **CSS Custom Properties**: Every color, spacing, and font is a design token. The entire theme can be modified in `:root {}` without touching component CSS.

---

## UI COMPONENT MAP

### Global Components
| Component | Location | Description |
|---|---|---|
| Sidebar + Nav | `index.html: .sidebar` | Fixed left navigation, group labels, active state, live clock |
| Topbar | `index.html: .topbar` | Page breadcrumb, live index tickers, regime badge, date |
| KPI Row | `.kpi-row` + `.kpi-card` | Metric summary cards used on every page |
| Panel | `.panel` + `.panel-header` + `.panel-body` | Universal content container |
| Data Table | `.data-table` | Styled tables with hover states |
| Confidence Bar | `.conf-bar-wrap` | Inline bar + percentage for confidence visualization |
| Badge / Pill | `.badge .badge-*` | Direction, risk, status, sentiment labels |
| Health Item | `.health-item` | System component status rows |
| Alert Item | `.alert-item` | Structured alert with icon + title + subtitle |

### Page-Specific Components
| Page | Key Components |
|---|---|
| Overview | Equity Curve (Chart.js line), Top Predictions table, Market Regime display, System Health grid, Today's Alerts |
| Market Intelligence | Sector Strength (horizontal bar chart), Top Movers table, Sector Detail cards with score bars, Derivatives signals table |
| Opportunity Rankings | Full opportunity table (15 rows), Confidence filter + Direction filter dropdowns, Confidence Distribution (doughnut), Strategy Breakdown (doughnut) |
| News Intelligence | High-impact event cards (impact ≥ 70), News Sentiment Trend (24hr line chart), Full news feed with impact badges |
| Sentiment Center | Company Sentiment (vertical bar), Sector Sentiment (radar chart), Sentiment Velocity bars, Narrative Shifts list |
| Strategy Lab | Strategy Leaderboard table (14 strategies), Population pie chart, Alpha vs Sharpe scatter plot |
| Model Center | Model Accuracy (horizontal bar), Calibration Curve (line), Model Registry table |
| Learning Center | Knowledge Score Growth (line chart), Failure Category breakdown (bar chart), Recent Failures log, Improvements log |
| Risk Center | Sector Exposure (doughnut), Drawdown History (area chart), Position Risk table, Risk Alerts |

---

## MOCK DATA STRUCTURE — FUTURE API CONTRACTS

Each field below maps directly to the AQRTI database schema and backend response format.

### GET /api/v1/overview
```json
{
  "portfolioValue": 104328,
  "paperCapitalStart": 100000,
  "dailyPnl": 1284,
  "dailyPnlPct": 1.25,
  "openPositions": 12,
  "deployedCapital": 67420,
  "activePredictions": 48,
  "avgConfidence": 79.2,
  "winRate30d": 63.4,
  "totalTrades30d": 142,
  "knowledgeScore": 67,
  "regime": "BULL MARKET",
  "regimeConf": 88
}
```

### GET /api/v1/market
```json
{
  "indices": {
    "nifty50":   { "value": 24162.20, "change": 203.1, "changePct": 0.84 },
    "banknifty": { "value": 51847.30, "change": 573.6, "changePct": 1.12 }
  },
  "breadth": 72,
  "vix": 13.24,
  "sectorStrength": [
    { "name": "FMCG", "score": 88, "rs": 91, "momentum": 84, "returns1d": 1.2 }
  ],
  "topMovers": [
    { "symbol": "RELIANCE", "sector": "Energy", "price": "2847.30", "change": "+3.2%", "volume": "12.4M", "direction": "up" }
  ]
}
```

### GET /api/v1/predictions
```json
[
  {
    "rank": 1,
    "symbol": "RELIANCE",
    "sector": "Energy",
    "direction": "Bullish",
    "confidence": 87,
    "expectedReturn": 3.4,
    "risk": "Low",
    "strategy": "Momentum + Event",
    "sentimentScore": 84,
    "positionSize": "5%",
    "reasoning": "Strong sector trend, positive sentiment, earnings momentum, institutional activity detected."
  }
]
```

### GET /api/v1/news
```json
[
  {
    "id": "N001",
    "headline": "HDFCBANK Quarterly Results Beat Estimates",
    "summary": "Net Profit ₹16,812 crore vs estimate ₹15,400 crore...",
    "company": "HDFCBANK",
    "sector": "Banking",
    "source": "NSE Filing",
    "timestamp": "2026-06-22T16:42:00+05:30",
    "sentiment": "positive",
    "sentimentScore": 0.84,
    "impactScore": 92,
    "importanceScore": 95,
    "eventType": "Earnings"
  }
]
```

### GET /api/v1/sentiment
```json
{
  "market": { "label": "Optimistic", "score": 71, "fearGreed": 63 },
  "companies": [
    { "symbol": "RELIANCE", "score": 84, "trend": "Improving", "velocity": 4.2 }
  ],
  "sectors": [
    { "sector": "FMCG", "score": 83 }
  ],
  "narrativeShifts": [
    { "ticker": "RELIANCE", "direction": "improving", "description": "Shift from O2C to new energy story." }
  ]
}
```

### GET /api/v1/strategies
```json
[
  {
    "id": "AQRTI_MOM_001",
    "family": "Momentum",
    "status": "institutional",
    "alphaScore": 92,
    "sharpe": 2.41,
    "sortino": 2.94,
    "winRate": 68,
    "profitFactor": 2.14,
    "maxDrawdown": -6.2,
    "regime": "Bull",
    "tradeCount": 284,
    "created": "2025-01-14",
    "lastUpdated": "2026-06-22"
  }
]
```

### GET /api/v1/models
```json
[
  {
    "id": "LGBM_DIR_v3",
    "type": "LightGBM",
    "target": "Direction",
    "accuracy": 68.2,
    "calibrationECE": 0.031,
    "ensembleWeight": 0.32,
    "status": "production",
    "lastTrained": "2026-06-22T06:28:00+05:30",
    "featuresUsed": 148
  }
]
```

### GET /api/v1/learning
```json
{
  "knowledgeScore": 67,
  "knowledgeHistory": [
    { "date": "2026-05-24", "score": 38 }
  ],
  "failureCategories": {
    "falseBullish": 412,
    "falseBearish": 287,
    "regimeError": 198,
    "sentimentError": 324,
    "dataError": 89,
    "overconfidence": 267,
    "riskError": 270
  },
  "recentFailures": [
    {
      "id": "F-0847",
      "category": "Regime Error",
      "symbol": "INFY",
      "description": "Predicted bullish breakout in early Bear transition.",
      "lesson": "Increase regime model weight during high-volatility transitions.",
      "severity": "medium",
      "resolved": true
    }
  ]
}
```

### GET /api/v1/risk
```json
{
  "exposure": 64.8,
  "varDaily": -2840,
  "varPct": -2.72,
  "maxDrawdown30d": -4.3,
  "sharpe": 1.84,
  "sortino": 2.31,
  "profitFactor": 1.74,
  "sectorExposure": [
    { "sector": "Banking", "weight": 18.4, "limit": 25.0 }
  ],
  "positions": [
    {
      "symbol": "RELIANCE",
      "weight": 5.0,
      "var": -142,
      "volatility": 18.4,
      "riskLevel": "Low"
    }
  ],
  "circuitBreakers": {
    "daily": { "triggered": false, "limit": -3.0, "current": -0.8 },
    "weekly": { "triggered": false, "limit": -6.0, "current": -2.1 },
    "monthly": { "triggered": false, "limit": -12.0, "current": -4.3 }
  }
}
```

---

## BACKEND INTEGRATION PLAN

### Phase 2: Connect Data APIs

Replace `DataStore.*` properties with fetch calls to a Python FastAPI backend.

#### Step 1 — Create API Layer (api.js)
```javascript
// api.js — Add this file to ui/ in Phase 2
const API_BASE = 'http://localhost:8000/api/v1';

async function fetchJSON(endpoint) {
  const res = await fetch(`${API_BASE}${endpoint}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const Api = {
  overview:     () => fetchJSON('/overview'),
  market:       () => fetchJSON('/market'),
  predictions:  () => fetchJSON('/predictions'),
  news:         () => fetchJSON('/news'),
  sentiment:    () => fetchJSON('/sentiment'),
  strategies:   () => fetchJSON('/strategies'),
  models:       () => fetchJSON('/models'),
  learning:     () => fetchJSON('/learning'),
  risk:         () => fetchJSON('/risk'),
  equityCurve:  () => fetchJSON('/portfolio/equity-curve'),
};
```

#### Step 2 — Replace DataStore
In `app.js`, change each renderer to:
```javascript
async function renderOverview() {
  const data = await Api.overview();
  // use data.portfolioValue instead of DataStore.system.portfolioValue
}
```

#### Step 3 — Auto-Refresh
```javascript
// Add to app.js init: refresh active page data every 5 minutes
setInterval(() => renderPage(currentPage, forceRefresh = true), 5 * 60 * 1000);
```

### Phase 3: Real-Time Streaming

Replace poll-based refresh with WebSocket for live feeds:
- Ticker updates (topbar indices)
- News feed (new articles)
- Alert notifications

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/stream');
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === 'ticker_update') updateTopbarTicker(msg.data);
  if (msg.type === 'new_alert')     prependAlert(msg.data);
  if (msg.type === 'new_news')      prependNewsItem(msg.data);
};
```

---

## TECH STACK

| Layer | Technology |
|---|---|
| UI Shell | Vanilla HTML5 + CSS3 + ES2022 JS |
| Charts | Chart.js 4.4 (CDN) |
| Fonts | JetBrains Mono (mono) + Inter (sans) |
| Future API | Python FastAPI + SQLite/PostgreSQL |
| Future Real-Time | FastAPI WebSockets |
| Future Auth | JWT (for multi-user, if needed) |

---

## WHAT PHASE 1 DELIVERS

- Complete 9-page Intelligence Terminal UI shell
- All navigation and page routing functional
- All chart types rendered with realistic mock data
- All AQRTI entities represented: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, WIPRO, AXISBANK, LTIM, etc.
- All confidence scores, sentiment values, risk metrics, strategy names match AQRTI backend schemas
- Filter controls on Opportunity Rankings page
- Lazy rendering for performance
- Live NSE clock in sidebar
- Market regime badge in topbar
- System health indicators
- Alert system
- Zero generic admin-dashboard appearance

## WHAT PHASE 1 DOES NOT DO

- No real data connections (intentional — backend not built yet)
- No autonomous trading (Phase 10 of roadmap)
- No model training (Phase 3 of roadmap)
- No strategy discovery engine (Phase 5 of roadmap)

---

*The terminal is ready for progressive real system connection as each AQRTI backend module is built.*
