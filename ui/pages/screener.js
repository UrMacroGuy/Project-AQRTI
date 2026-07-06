// ui/pages/screener.js - split from app.js (ARCH-5), see CHANGELOG
// EQUITY SCREENER
// ══════════════════════════════════════════════════════════════
async function hydrateScreener() {
  await loadScreenerPresets();
  await runScreener();
}

async function loadScreenerPresets() {
  const data = await Api.screenerPresets();
  const container = document.getElementById('scr-presets');
  if (!container || !data) return;
  container.innerHTML = (data.presets || []).map(p =>
    `<button class="panel-action-btn" onclick="applyScreenerPreset(${JSON.stringify(JSON.stringify(p.filters))})" style="font-size:0.6rem;padding:3px 7px">${p.name}</button>`
  ).join('');
}

function applyScreenerPreset(filtersJson) {
  const f = JSON.parse(filtersJson);
  const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.value = v; };
  set('scr-rsi-min', f.min_rsi || ''); set('scr-rsi-max', f.max_rsi || '');
  set('scr-chg-min', f.min_change_pct || ''); set('scr-chg-max', f.max_change_pct || '');
  set('scr-vol-min', f.min_volume_ratio || '');
  set('scr-signal', f.signal || 'all');
  set('scr-ema20', f.above_ema20 !== undefined ? String(f.above_ema20) : '');
  set('scr-ema50', f.above_ema50 !== undefined ? String(f.above_ema50) : '');
  runScreener();
}

function clearScreener() {
  ['scr-rsi-min','scr-rsi-max','scr-chg-min','scr-chg-max','scr-vol-min'].forEach(id => { const el = document.getElementById(id); if(el) el.value=''; });
  const sig = document.getElementById('scr-signal'); if(sig) sig.value='all';
  const e20 = document.getElementById('scr-ema20'); if(e20) e20.value='';
  const e50 = document.getElementById('scr-ema50'); if(e50) e50.value='';
  runScreener();
}

async function runScreener() {
  const g = id => { const el = document.getElementById(id); return el ? el.value : ''; };
  const params = {};
  if (g('scr-rsi-min')) params.min_rsi = g('scr-rsi-min');
  if (g('scr-rsi-max')) params.max_rsi = g('scr-rsi-max');
  if (g('scr-chg-min')) params.min_change_pct = g('scr-chg-min');
  if (g('scr-chg-max')) params.max_change_pct = g('scr-chg-max');
  if (g('scr-vol-min')) params.min_volume_ratio = g('scr-vol-min');
  const sig = g('scr-signal'); if (sig && sig !== 'all') params.signal = sig;
  const e20 = g('scr-ema20'); if (e20) params.above_ema20 = e20;
  const e50 = g('scr-ema50'); if (e50) params.above_ema50 = e50;

  const tbody = document.getElementById('scr-results-body');
  if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#666;padding:16px">Loading…</td></tr>';

  const data = await Api.screener(params);
  const stocks = data?.stocks || data || [];
  const matchEl = document.getElementById('scr-match');
  const bullEl  = document.getElementById('scr-bull');
  const bearEl  = document.getElementById('scr-bear');
  const cntEl   = document.getElementById('scr-result-count');

  const totalEl = document.getElementById('scr-total');
  if (totalEl && data?.total_universe) totalEl.textContent = data.total_universe;
  if (matchEl) matchEl.textContent = stocks.length;
  if (bullEl)  bullEl.textContent  = stocks.filter(s => s.signal === 'bullish').length;
  if (bearEl)  bearEl.textContent  = stocks.filter(s => s.signal === 'bearish').length;
  if (cntEl)   cntEl.textContent   = `${stocks.length} stocks`;

  if (!tbody) return;
  if (!stocks.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#444;padding:20px">No stocks match filters</td></tr>'; return; }

  tbody.innerHTML = stocks.map(s => {
    const chgCls = (s.change_pct || 0) >= 0 ? 'positive' : 'negative';
    const sigCls = s.signal === 'bullish' ? 'positive' : s.signal === 'bearish' ? 'negative' : 'neutral';
    const rsiColor = s.rsi > 70 ? '#ff3333' : s.rsi < 30 ? '#00cc66' : '#e0e0e0';
    return `<tr>
      <td><strong>${s.symbol}</strong><br><span style="color:#666;font-size:0.6rem">${s.sector || ''}</span></td>
      <td>₹${(s.price||0).toFixed(1)}</td>
      <td class="${chgCls}">${(s.change_pct||0)>=0?'+':''}${(s.change_pct||0).toFixed(2)}%</td>
      <td style="color:${rsiColor}">${(s.rsi||0).toFixed(1)}</td>
      <td>${(s.volume_ratio||0).toFixed(2)}\xD7</td>
      <td class="${(s.pct_from_52h||0)>-5?'positive':'negative'}">${(s.pct_from_52h||0).toFixed(1)}%</td>
      <td class="${sigCls}">${(s.signal||'').toUpperCase()}</td>
      <td><div style="display:flex;align-items:center;gap:4px"><div style="width:${Math.round(s.score||0)*0.5}px;height:6px;background:#ff8c00;border-radius:2px"></div>${(s.score||0).toFixed(0)}</div></td>
    </tr>`;
  }).join('');
}


// ═══════════════════════════════════════════════════════════════
