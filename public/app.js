/* ── Morning Brief v3.1 · app.js ─────────────────────────────────────────── */

// ── Constants ─────────────────────────────────────────────────────────────
const PRESET_GROUPS = {
  mag7:    ['AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA'],
  sti:     ['D05.SI','O39.SI','U11.SI','Z74.SI','C6L.SI'],
  crypto:  ['BTC-USD','ETH-USD','SOL-USD'],
  sectors: ['XLK','XLV','XLF','XLE','SMH','XBI'],
};
const ALL_PRESETS = Object.values(PRESET_GROUPS).flat();

const WMO = {
  0:{icon:'☀️',label:'Clear'},1:{icon:'🌤️',label:'Mainly Clear'},
  2:{icon:'⛅',label:'Partly Cloudy'},3:{icon:'☁️',label:'Overcast'},
  45:{icon:'🌫️',label:'Foggy'},48:{icon:'🌫️',label:'Icy Fog'},
  51:{icon:'🌦️',label:'Light Drizzle'},53:{icon:'🌦️',label:'Drizzle'},
  55:{icon:'🌧️',label:'Heavy Drizzle'},61:{icon:'🌧️',label:'Light Rain'},
  63:{icon:'🌧️',label:'Rain'},65:{icon:'🌧️',label:'Heavy Rain'},
  80:{icon:'🌦️',label:'Showers'},81:{icon:'🌧️',label:'Rain Showers'},
  82:{icon:'⛈️',label:'Heavy Showers'},95:{icon:'⛈️',label:'Thunderstorm'},
  99:{icon:'⛈️',label:'Heavy Thunderstorm'},
};
function wmo(c){ return WMO[c]||WMO[Math.floor(c/10)*10]||{icon:'🌡️',label:'Variable'}; }

// ── State ─────────────────────────────────────────────────────────────────
let watchlistTickers = ['^GSPC','^IXIC','^STI','BTC-USD','GC=F','CL=F','AAPL','NVDA','MSFT'];
let watchlistTab     = 'all';
let watchlistData    = {};
let stockInsights    = {};
let chatHistory      = [];
let histSymbol       = '^GSPC';
let histDays         = 30;
let allArticles      = [];
let newsBullets      = {};
let newsTab          = 'all';

// ── Utilities ─────────────────────────────────────────────────────────────
const qs  = s => document.querySelector(s);
const pad = n => String(n).padStart(2,'0');
const fmtTime = s => { if(!s)return'—'; const d=new Date(s); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const tsAgo   = s => { const m=Math.round((Date.now()-new Date(s))/60000); return m<1?'just now':m<60?`${m}m ago`:`${Math.floor(m/60)}h ago`; };

function fmtPrice(p, sym='') {
  if(p==null) return '—';
  if(['BTC-USD','ETH-USD','SOL-USD'].includes(sym))
    return '$'+p.toLocaleString('en-US',{maximumFractionDigits:0});
  if(p<10)   return p.toFixed(4);
  if(p<1000) return p.toFixed(2);
  return p.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

function sparkline(vals, up) {
  if(!vals||vals.length<2) return '';
  const w=100,h=44,p=3;
  const mn=Math.min(...vals),mx=Math.max(...vals),rng=mx-mn||1;
  const pts=vals.map((v,i)=>`${(p+i/(vals.length-1)*(w-p*2)).toFixed(1)},${(h-p-(v-mn)/rng*(h-p*2)).toFixed(1)}`).join(' ');
  const c=up?'#00e5a0':'#ff4f6d';
  const gid=`sg${up?'u':'d'}`;
  return `<svg width="100%" height="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${c}" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="${c}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points="${p},${h} ${pts} ${w-p},${h}" fill="url(#${gid})"/>
    <polyline points="${pts}" fill="none" stroke="${c}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// ── Fetch with timeout ─────────────────────────────────────────────────────
// Prevents pages from loading forever if the backend is slow or Vercel times out.
async function fetchWithTimeout(url, timeoutMs = 55000, options = {}) {
  const ctrl  = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new Error('Request timed out');
    throw e;
  }
}

async function fetchJson(url, timeoutMs, options = {}) {
  const res = await fetchWithTimeout(url, timeoutMs, options);
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(`Expected JSON, got ${contentType || 'unknown content'}`);
  }
  return res.json();
}

// ── Clock ─────────────────────────────────────────────────────────────────
function updateClock() {
  const now=new Date();
  const days=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const mons=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  qs('#clock').textContent=`${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  qs('#date-str').textContent=`${days[now.getDay()]}, ${now.getDate()} ${mons[now.getMonth()]} ${now.getFullYear()}`;
}

// ── Name / Session ────────────────────────────────────────────────────────
function getName(){ return localStorage.getItem('mbName')||'Jeremy'; }
function setName(n){ localStorage.setItem('mbName',n.trim()||'Jeremy'); qs('#display-name').textContent=getName(); }
function openNameModal(){ qs('#name-input').value=getName(); qs('#name-modal').classList.remove('hidden'); qs('#name-input').focus(); }
function closeNameModal(){ qs('#name-modal').classList.add('hidden'); }
function getSession(){ let s=localStorage.getItem('mbSession'); if(!s){s=crypto.randomUUID();localStorage.setItem('mbSession',s);} return s; }

// ── Brief ─────────────────────────────────────────────────────────────────
function renderBrief(data) {
  const el=qs('#brief-text');
  el.textContent=data.brief||'';
  el.style.opacity='0'; el.style.transition='opacity .7s ease';
  requestAnimationFrame(()=>{ el.style.opacity='1'; });
  const ns=data.news_summary||{};
  const sentEl=qs('#brief-sentiment');
  const sent=(ns.sentiment||'neutral').toLowerCase();
  sentEl.textContent=sent.toUpperCase(); sentEl.className=`sentiment-chip ${sent}`; sentEl.style.display='';
  if(ns.top_theme){ const t=qs('#brief-theme'); t.textContent=`"${ns.top_theme}"`; t.style.display=''; }
  if(data.timestamp){ const t=qs('#brief-ts'); t.textContent=tsAgo(data.timestamp); t.style.display=''; }
}

// ── News ──────────────────────────────────────────────────────────────────
function filterArticles(articles, tab) {
  if(tab==='all') return articles;
  return articles.filter(a=>a.category===tab||(tab==='world'&&a.category==='global'));
}

function renderNewsBullets(bullets, tab) {
  const bulletsEl=qs('#news-bullets'), listEl=qs('#bullets-list');
  let items=[];
  if(typeof bullets==='object'&&!Array.isArray(bullets)){
    items=tab==='all'?Object.values(bullets).flat():
      (bullets[tab]||[]);
  } else if(Array.isArray(bullets)){
    items=bullets;
  }
  if(!items.length){ bulletsEl.style.display='none'; return; }
  listEl.innerHTML=items.map(b=>`<li class="bullet-item">${b}</li>`).join('');
  bulletsEl.style.display='block';
}

function renderNewsArticles(articles, tab) {
  const filtered=filterArticles(articles,tab);
  const list=qs('#news-list');
  if(!filtered.length){
    list.innerHTML='<li class="error-msg" style="padding:12px 0">No headlines for this category yet.</li>';
    return;
  }
  list.innerHTML=filtered.slice(0,8).map(a=>{
    const cat=a.category==='global'?'world':a.category;
    const href=a.link||'#';
    return `<li class="news-item"><span class="news-cat cat-${cat}">${cat}</span><span class="news-title">${href!=='#'?`<a href="${href}" target="_blank" rel="noopener">${a.title}</a>`:a.title}</span></li>`;
  }).join('');
}

function renderNews(data) {
  const ns=data.news_summary||{};
  allArticles=data.articles||[];
  newsBullets=ns.bullets||{};
  renderNewsBullets(newsBullets, newsTab);
  renderNewsArticles(allArticles, newsTab);
  const ents=ns.key_entities||[];
  if(ents.length){
    const r=qs('#news-entities');
    r.innerHTML=ents.map(e=>`<span class="entity-chip">${e}</span>`).join('');
    r.style.display='flex';
  }
}

// ── Weather ───────────────────────────────────────────────────────────────
function renderWeather(data) {
  const cur=data.current||{}, daily=data.daily||{}, hourly=data.hourly||[], aq=data.air_quality||{};
  const info=wmo(cur.weather_code);
  qs('#weather-main').innerHTML=`
    <div class="weather-hero">
      <span class="weather-icon">${info.icon}</span>
      <div>
        <div class="weather-temp">${Math.round(cur.temperature??0)}<span class="weather-temp-unit">°C</span></div>
        <div class="weather-label">${info.label}</div>
        <div class="weather-feels">Feels like ${Math.round(cur.feels_like??0)}°C · ${daily.min_temp??'—'}–${daily.max_temp??'—'}°C</div>
      </div>
    </div>`;
  if(hourly.length){
    qs('#weather-hourly').innerHTML=hourly.slice(0,7).map(h=>{
      const hi=wmo(h.weather_code);
      return `<div class="hourly-slot"><span class="hourly-time">${pad(new Date(h.time).getHours())}:00</span><span class="hourly-icon">${hi.icon}</span><span class="hourly-temp">${Math.round(h.temp)}°</span><span class="hourly-rain ${h.rain_prob>=60?'high':''}">${h.rain_prob}%</span></div>`;
    }).join('');
  }
  qs('#wval-rain').textContent=`${daily.rain_prob??'—'}%`;
  qs('#wval-humidity').textContent=`${cur.humidity??'—'}%`;
  qs('#wval-wind').textContent=`${Math.round(cur.wind_speed??0)} km/h`;
  const aqiVal=aq.us_aqi;
  const aqiEl=qs('#wval-aqi');
  aqiEl.textContent=aqiVal?`${aqiVal} · ${aq.label||''}` : '—';
  if(aqiVal&&aqiVal>100) aqiEl.style.color='var(--amber)';
  qs('#weather-stats').style.display='grid';
}

function renderWeatherTip(tip) {
  if(!tip) return;
  qs('#weather-tip-text').textContent=tip;
  qs('#weather-tip').style.display='flex';
}

// ── Watchlist ─────────────────────────────────────────────────────────────
function saveWatchlistLocal(){ localStorage.setItem('mbWatchlist',JSON.stringify(watchlistTickers)); }
function loadWatchlistLocal(){ try{ const s=localStorage.getItem('mbWatchlist'); if(s){watchlistTickers=JSON.parse(s);return true;}} catch(e){} return false; }

async function saveWatchlist() {
  saveWatchlistLocal();
  try{
    await fetchWithTimeout(`/api/watchlist/${getSession()}`, 10000, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tickers:watchlistTickers})
    });
  } catch(e){}
}

async function loadWatchlist() {
  const hadLocal=loadWatchlistLocal();
  if(!hadLocal){
    try{
      const r=await fetchWithTimeout(`/api/watchlist/${getSession()}`,10000).then(r=>r.json());
      if(r.tickers?.length){ watchlistTickers=r.tickers; saveWatchlistLocal(); }
    } catch(e){}
  }
  await refreshWatchlistData();
}

async function refreshWatchlistData() {
  if(!watchlistTickers.length) return;
  try{
    const r=await fetchJson(`/api/watchlist-data?tickers=${watchlistTickers.join(',')}`, 20000);
    watchlistData=r.data||{};
    renderWatchlistCards();
    loadStockInsights();
  } catch(e){
    qs('#watchlist-grid').innerHTML='<div class="error-msg" style="grid-column:1/-1">Market data unavailable — will retry on next refresh.</div>';
  }
}

function filterWatchlistTickers(tickers,group) {
  if(group==='all') return tickers;
  if(group==='custom') return tickers.filter(t=>!ALL_PRESETS.includes(t));
  return tickers.filter(t=>(PRESET_GROUPS[group]||[]).includes(t));
}

function renderWatchlistCards() {
  const filtered=filterWatchlistTickers(watchlistTickers,watchlistTab);
  const grid=qs('#watchlist-grid');
  if(!filtered.length){
    grid.innerHTML='<div class="wl-empty">No tickers here. Use preset buttons or add one below.</div>';
    return;
  }
  grid.innerHTML=filtered.map(sym=>{
    const d=watchlistData[sym];
    if(!d) return `<div class="wl-card"><div class="wl-symbol">${sym}</div><div class="wl-na">Loading…</div></div>`;
    const cls=d.up?'up':'down', arr=d.up?'▲':'▼';
    const insight=stockInsights[sym]||'';
    return `<div class="wl-card ${cls}">
      <button class="wl-remove" data-sym="${sym}" title="Remove">✕</button>
      <div class="wl-symbol">${sym}</div>
      <div class="wl-name">${d.name}</div>
      ${d.price!=null
        ?`<div class="wl-price">${fmtPrice(d.price,sym)}</div>
          <div class="wl-change ${cls}">${arr} ${Math.abs(d.change_pct).toFixed(2)}%</div>
          ${insight?`<span class="wl-insight">${insight}</span>`:''}
          <div class="wl-sparkline">${sparkline(d.sparkline,d.up)}</div>`
        :`<div class="wl-na">Unavailable</div>`}
    </div>`;
  }).join('');
  grid.querySelectorAll('.wl-remove').forEach(btn=>{
    btn.addEventListener('click',e=>{e.stopPropagation();removeTicker(btn.dataset.sym);});
  });
}

async function loadStockInsights() {
  const tickers=watchlistTickers.filter(t=>watchlistData[t]?.price!=null).slice(0,8);
  if(!tickers.length) return;
  try{
    const r=await fetchJson(`/api/stock-insights?tickers=${tickers.join(',')}`, 25000);
    stockInsights=r.insights||{};
    renderWatchlistCards();
  } catch(e){}
}

async function addTicker(sym) {
  sym=sym.trim().toUpperCase();
  if(!sym||watchlistTickers.includes(sym)) return;
  watchlistTickers.push(sym);
  await saveWatchlist();
  await refreshWatchlistData();
}

async function removeTicker(sym) {
  watchlistTickers=watchlistTickers.filter(t=>t!==sym);
  delete watchlistData[sym]; delete stockInsights[sym];
  renderWatchlistCards();
  await saveWatchlist();
}

async function addPresetGroup(group) {
  const syms=(PRESET_GROUPS[group]||[]).filter(s=>!watchlistTickers.includes(s));
  if(!syms.length) return;
  watchlistTickers=[...watchlistTickers,...syms];
  await saveWatchlist();
  await refreshWatchlistData();
}

// ── Sentiment gauge (sweep=1 = top-half arc) ──────────────────────────────
function buildGaugeSVG(score) {
  score=Math.max(0,Math.min(100,score));
  const cx=120, cy=92, r=76, sw=14, W=240, H=132;
  const colors=['#ff4f6d','#ff8c42','#ffb830','#7bc67e','#00e5a0'];
  const labels=['Extreme Fear','Fear','Neutral','Greed','Extreme Greed'];
  // pt(): standard-math angle → SVG coords (y flipped)
  function pt(deg){ const rad=deg*Math.PI/180; return {x:+(cx+r*Math.cos(rad)).toFixed(2),y:+(cy-r*Math.sin(rad)).toFixed(2)}; }
  const angles=[180,144,108,72,36,0];
  const si=Math.min(4,Math.floor(score/20)), ac=colors[si];
  const s0=pt(180), e0=pt(0);
  // IMPORTANT: sweep=1 draws the TOP semicircle in SVG.
  // sweep=0 draws the bottom half which gets clipped by the viewBox (the v2 bug).
  let svg=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  svg+=`<defs><filter id="sg" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
  svg+=`<path d="M${s0.x},${s0.y} A${r},${r} 0 0,1 ${e0.x},${e0.y}" stroke="rgba(255,255,255,0.07)" stroke-width="${sw+2}" fill="none" stroke-linecap="round"/>`;
  for(let i=0;i<5;i++){
    const sp=pt(angles[i]),ep=pt(angles[i+1]);
    const extra=i===si?` filter="url(#sg)" stroke-width="${sw+4}"`:`stroke-width="${sw}"`;
    svg+=`<path d="M${sp.x},${sp.y} A${r},${r} 0 0,1 ${ep.x},${ep.y}" stroke="${colors[i]}" fill="none" stroke-linecap="butt"${extra}/>`;
  }
  const na=180-(score/100)*180, npt=pt(na);
  const nx=cx+(npt.x-cx)*0.70, ny=cy+(npt.y-cy)*0.70;
  const perp=(na+90)*Math.PI/180;
  const b1={x:+(cx+6*Math.cos(perp)).toFixed(1),y:+(cy-6*Math.sin(perp)).toFixed(1)};
  const b2={x:+(cx-6*Math.cos(perp)).toFixed(1),y:+(cy+6*Math.sin(perp)).toFixed(1)};
  svg+=`<polygon points="${nx.toFixed(1)},${ny.toFixed(1)} ${b1.x},${b1.y} ${b2.x},${b2.y}" fill="${ac}" opacity="0.95"/>`;
  svg+=`<circle cx="${cx}" cy="${cy}" r="6" fill="${ac}"/><circle cx="${cx}" cy="${cy}" r="3" fill="#07090f"/>`;
  svg+=`<text x="${cx}" y="${cy+16}" text-anchor="middle" font-size="20" font-weight="700" fill="${ac}" font-family="'Space Mono',monospace">${score}</text>`;
  svg+=`<text x="${cx}" y="${cy+28}" text-anchor="middle" font-size="8" fill="#6a7a9a" font-family="'DM Sans',sans-serif">${labels[si].toUpperCase()}</text>`;
  svg+=`<text x="${s0.x}" y="${cy+16}" text-anchor="middle" font-size="8" fill="#6a7a9a" font-family="'DM Sans',sans-serif">FEAR</text>`;
  svg+=`<text x="${e0.x}" y="${cy+16}" text-anchor="middle" font-size="8" fill="#6a7a9a" font-family="'DM Sans',sans-serif">GREED</text>`;
  svg+=`</svg>`;
  return svg;
}

function renderSentiment(data) {
  qs('#sentiment-gauge').innerHTML=buildGaugeSVG(data.score||50);
  qs('#sentiment-sub').textContent=`Score: ${data.score||'—'}/100`;
  const cats=data.categories||{};
  const catLabels={tech:'Tech',healthcare:'Healthcare',finance:'Finance',commodities:'Commodities'};
  qs('#sentiment-categories').innerHTML=Object.entries(catLabels).map(([key,label])=>{
    const cat=cats[key]||{score:50}, sc=cat.score||50;
    const bc=sc<40?'var(--down)':sc<60?'var(--amber)':'var(--up)';
    return `<div class="cat-bar-row"><span class="cat-bar-label">${label}</span><div class="cat-bar-track"><div class="cat-bar-fill" style="width:${sc}%;background:${bc}"></div></div><span class="cat-bar-score">${sc}</span></div>`;
  }).join('');
  const ents=(data.entities||[]).slice(0,8);
  qs('#sentiment-entities').innerHTML=ents.map(e=>{
    const cls=e.sentiment==='positive'?'positive':e.sentiment==='negative'?'negative':'neutral';
    return `<span class="ent-chip ent-${cls}">${e.name}${e.count>1?` ×${e.count}`:''}</span>`;
  }).join('');
}

async function loadSentiment() {
  try{
    const data=await fetchJson('/api/sentiment',30000);
    renderSentiment(data);
  } catch(e){
    qs('#sentiment-gauge').innerHTML=`<div class="error-msg">Sentiment unavailable: ${e.message}</div>`;
  }
}

// ── Trends ────────────────────────────────────────────────────────────────
function renderTrends(data) {
  const topics=data.topics||[], grid=qs('#trends-grid');
  if(!topics.length){
    grid.innerHTML='<div class="trends-empty">No recurring topics detected yet — check back after headlines load.</div>';
    return;
  }
  const maxPct=Math.max(...topics.map(t=>t.pct||0),1);
  const catColors={finance:'var(--up)',tech:'var(--teal)',geopolitics:'var(--accent)',singapore:'var(--amber)',commodities:'var(--amber)',other:'var(--t2)'};
  grid.innerHTML=topics.slice(0,8).map(t=>{
    const bc=catColors[t.category]||'var(--t2)', pct=t.pct||0;
    return `<div class="trend-card"><div class="trend-topic">${t.topic}</div>
      <div class="trend-bar-row"><div class="trend-bar-track"><div class="trend-bar-fill" style="width:${(pct/maxPct*100).toFixed(1)}%;background:${bc}"></div></div><span class="trend-pct">${pct}%</span></div>
      <div class="trend-meta"><span class="trend-cat" style="background:${bc}20;color:${bc}">${t.category||'other'}</span><span class="trend-count">${t.count} headline${t.count!==1?'s':''}</span><span class="trend-sent ${t.sentiment||'neutral'}">${t.sentiment||'neutral'}</span></div></div>`;
  }).join('');
}

async function loadTrends() {
  try{
    const data=await fetchJson('/api/trends',30000);
    renderTrends(data);
  } catch(e){
    qs('#trends-grid').innerHTML=`<div class="trends-empty">Could not load trends: ${e.message}</div>`;
  }
}

// ── History chart ─────────────────────────────────────────────────────────
function buildHistoryChart(data) {
  const prices=data.prices||[];
  if(!prices.length) return `<div class="chart-empty">No data — ${data.error||'yfinance unavailable'}</div>`;
  if(prices.length<2) return '<div class="chart-empty">Not enough data points.</div>';
  const W=800,H=190,P={top:22,right:20,bottom:34,left:64};
  const cW=W-P.left-P.right, cH=H-P.top-P.bottom;
  const vals=prices.map(p=>p.price);
  const mn=Math.min(...vals),mx=Math.max(...vals),rng=mx-mn||1;
  const sx=i=>P.left+(i/(prices.length-1))*cW;
  const sy=v=>P.top+cH-((v-mn)/rng)*cH;
  const isUp=vals[vals.length-1]>=vals[0], lc=isUp?'#00e5a0':'#ff4f6d';
  const gId='g'+Math.random().toString(36).slice(2,7);
  const linePts=prices.map((p,i)=>`${sx(i).toFixed(1)},${sy(p.price).toFixed(1)}`).join(' ');
  const fillPts=`${sx(0).toFixed(1)},${(P.top+cH).toFixed(1)} ${linePts} ${sx(prices.length-1).toFixed(1)},${(P.top+cH).toFixed(1)}`;
  let yLines='';
  for(let i=0;i<=4;i++){
    const v=mn+(rng*i/4),y=sy(v);
    const lbl=v>=10000?`${(v/1000).toFixed(1)}k`:v>=1000?`${(v/1000).toFixed(2)}k`:v.toFixed(2);
    yLines+=`<line x1="${P.left}" y1="${y.toFixed(1)}" x2="${P.left+cW}" y2="${y.toFixed(1)}" stroke="rgba(90,120,255,.06)" stroke-width="1"/><text x="${(P.left-6).toFixed(1)}" y="${(y+3.5).toFixed(1)}" text-anchor="end" font-size="9" fill="#3a4460" font-family="'Space Mono',monospace">${lbl}</text>`;
  }
  let xLabels='';
  const step=Math.max(1,Math.floor(prices.length/6));
  for(let i=0;i<prices.length;i+=step){
    xLabels+=`<text x="${sx(i).toFixed(1)}" y="${(H-6).toFixed(1)}" text-anchor="middle" font-size="9" fill="#3a4460" font-family="'Space Mono',monospace">${prices[i].date.slice(5)}</text>`;
  }
  const sents=data.sentiment||[];
  let sentDots='',sentLabel='';
  if(sents.length){
    const dateIdx={}; prices.forEach((p,i)=>{dateIdx[p.date]=i;});
    sentDots=sents.map(s=>{
      const idx=dateIdx[s.date]; if(idx==null)return'';
      const sc=s.score||50, c=sc<40?'#ff4f6d':sc<60?'#ffb830':'#00e5a0';
      return `<circle cx="${sx(idx).toFixed(1)}" cy="${(P.top+9).toFixed(1)}" r="3.5" fill="${c}" opacity="0.85"><title>${s.label||''}: ${sc}/100 · ${s.date}</title></circle>`;
    }).join('');
    sentLabel=`<text x="${(P.left-6).toFixed(1)}" y="${(P.top+13).toFixed(1)}" text-anchor="end" font-size="7" fill="#3a4460" font-family="'DM Sans',sans-serif">SENT</text>`;
  }
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
  <defs><linearGradient id="${gId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${lc}" stop-opacity="0.15"/><stop offset="100%" stop-color="${lc}" stop-opacity="0"/></linearGradient></defs>
  ${yLines}
  <polygon points="${fillPts}" fill="url(#${gId})"/>
  <polyline points="${linePts}" fill="none" stroke="${lc}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  ${sentDots}${sentLabel}${xLabels}
  <line x1="${P.left}" y1="${P.top}" x2="${P.left}" y2="${P.top+cH}" stroke="rgba(90,120,255,.15)" stroke-width="1"/>
  </svg>`;
}

async function loadHistory() {
  qs('#hist-chart').innerHTML='<div class="skel-chart"></div>';
  qs('#hist-stats').style.display='none';
  try{
    const data=await fetchJson(`/api/history?symbol=${encodeURIComponent(histSymbol)}&days=${histDays}`,20000);
    qs('#hist-chart').innerHTML=buildHistoryChart(data);
    const s=data.stats||{};
    if(s.current!=null){
      const isUp=(s.change_pct||0)>=0;
      const sentNote=data.sentiment?.length?`<div class="hstat"><span class="hstat-label">Sentiment Days</span><span class="hstat-val">${data.sentiment.length}</span></div>`:'';
      qs('#hist-stats').innerHTML=`
        <div class="hstat"><span class="hstat-label">Start</span><span class="hstat-val">${fmtPrice(s.start,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Now</span><span class="hstat-val">${fmtPrice(s.current,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Change</span><span class="hstat-val ${isUp?'up':'down'}">${isUp?'▲':'▼'}${Math.abs(s.change_pct||0).toFixed(2)}%</span></div>
        <div class="hstat"><span class="hstat-label">High</span><span class="hstat-val">${fmtPrice(s.high,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Low</span><span class="hstat-val">${fmtPrice(s.low,histSymbol)}</span></div>
        ${sentNote}`;
      qs('#hist-stats').style.display='grid';
    }
  } catch(e){
    qs('#hist-chart').innerHTML=`<div class="error-msg">Chart unavailable: ${e.message}</div>`;
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────
function mdToHtml(t){
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/^[-•]\s+(.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*?<\/li>(\n|$))+/gs,m=>`<ul>${m}</ul>`)
    .replace(/\n/g,'<br>');
}

function appendMessage(role,content,sources=[]){
  const intro=qs('#chat-intro'); if(intro)intro.style.display='none';
  const wrap=document.createElement('div');
  wrap.className=`chat-msg chat-msg-${role}`;
  const src=sources.length&&role==='assistant'?`<div class="chat-sources">Sources: ${sources.join(' · ')}</div>`:'';
  wrap.innerHTML=`<div class="chat-bubble">${mdToHtml(content)}</div>${src}`;
  qs('#chat-messages').appendChild(wrap);
  qs('#chat-messages').scrollTop=99999;
}

function showTyping(){
  const intro=qs('#chat-intro'); if(intro)intro.style.display='none';
  const el=document.createElement('div');
  el.className='chat-msg chat-msg-assistant'; el.id='chat-typing-indicator';
  el.innerHTML='<div class="chat-typing"><span></span><span></span><span></span></div>';
  qs('#chat-messages').appendChild(el);
  qs('#chat-messages').scrollTop=99999;
}
function removeTyping(){ const el=qs('#chat-typing-indicator'); if(el)el.remove(); }

async function sendChatMessage(text){
  text=text.trim(); if(!text)return;
  qs('#chat-input').value=''; qs('#chat-send').disabled=true;
  appendMessage('user',text);
  chatHistory.push({role:'user',content:text});
  showTyping();
  try{
    const res=await fetchJson('/api/chat',35000,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,history:chatHistory.slice(-10)})
    });
    removeTyping();
    appendMessage('assistant',res.response||'No response.',res.sources||[]);
    chatHistory.push({role:'assistant',content:res.response||''});
  } catch(e){
    removeTyping();
    appendMessage('assistant','Connection error — please try again.');
  } finally{
    qs('#chat-send').disabled=false;
    qs('#chat-input').focus();
  }
}

// ── Main load ─────────────────────────────────────────────────────────────
let _spinnerTimer = null;

function stopSpinner(){
  qs('#refresh-btn').classList.remove('loading');
  if(_spinnerTimer){ clearTimeout(_spinnerTimer); _spinnerTimer=null; }
}

async function loadV1() {
  const name=getName();
  qs('#display-name').textContent=name;

  // Reset UI
  qs('#brief-text').innerHTML=`<span class="skel-line" style="width:90%"></span><span class="skel-line" style="width:82%"></span><span class="skel-line" style="width:76%"></span><span class="skel-line" style="width:60%"></span>`;
  qs('#brief-sentiment').style.display='none';
  qs('#brief-theme').style.display='none';
  qs('#brief-ts').style.display='none';
  qs('#news-list').innerHTML=Array(5).fill('<li class="skel-news"></li>').join('');
  qs('#news-bullets').style.display='none';
  qs('#news-entities').style.display='none';
  qs('#weather-main').innerHTML='<div class="skel-weather"></div>';
  qs('#weather-hourly').innerHTML='';
  qs('#weather-stats').style.display='none';
  qs('#weather-tip').style.display='none';
  qs('#refresh-btn').classList.add('loading');

  // Hard stop: always clear the spinner after 62s regardless of what happens
  _spinnerTimer = setTimeout(stopSpinner, 28000);

  // Weather: 15s timeout (Open-Meteo is usually fast)
  const weatherP = fetchJson('/api/weather', 15000);

  // Brief: 55s timeout (Gemini + 8 RSS feeds + yfinance can be slow)
  const briefP = fetchJson(`/api/brief?name=${encodeURIComponent(name)}`, 25000);

  weatherP
    .then(d => renderWeather(d))
    .catch(e => { qs('#weather-main').innerHTML=`<div class="error-msg">Weather unavailable: ${e.message}</div>`; });

  briefP
    .then(d => { renderBrief(d); renderNews(d); renderWeatherTip(d.weather_tip); })
    .catch(e => {
      qs('#brief-text').innerHTML=`<span class="error-msg">Brief unavailable: ${e.message}</span>`;
      qs('#news-list').innerHTML=`<li class="error-msg" style="padding:12px 0">Headlines unavailable: ${e.message}</li>`;
    });

  // Stop spinner once both settle (or the 62s hard stop fires first)
  Promise.allSettled([weatherP, briefP]).then(stopSpinner);
}

async function loadV2() {
  loadWatchlist();
  loadSentiment();
  loadTrends();
  loadHistory();
}

async function loadAll() { await loadV1(); setTimeout(loadV2, 1500); }

// ── Event listeners ───────────────────────────────────────────────────────
qs('#refresh-btn').addEventListener('click', loadAll);
qs('#name-btn').addEventListener('click', openNameModal);
qs('#name-cancel').addEventListener('click', closeNameModal);
qs('#name-save').addEventListener('click', () => { const v=qs('#name-input').value.trim(); if(v){setName(v);closeNameModal();loadAll();} });
qs('#name-input').addEventListener('keydown', e => { if(e.key==='Enter')qs('#name-save').click(); if(e.key==='Escape')closeNameModal(); });
qs('#name-modal').addEventListener('click', e => { if(e.target===qs('#name-modal'))closeNameModal(); });

qs('#news-tabs').addEventListener('click', e => {
  const btn=e.target.closest('.news-tab'); if(!btn)return;
  qs('#news-tabs .active')?.classList.remove('active'); btn.classList.add('active');
  newsTab=btn.dataset.cat;
  renderNewsBullets(newsBullets,newsTab);
  renderNewsArticles(allArticles,newsTab);
});

qs('#wl-tabs').addEventListener('click', e => {
  const btn=e.target.closest('.wl-tab'); if(!btn)return;
  qs('#wl-tabs .active')?.classList.remove('active'); btn.classList.add('active');
  watchlistTab=btn.dataset.group; renderWatchlistCards();
});

qs('#preset-add-row').addEventListener('click', e => {
  const btn=e.target.closest('.preset-add-btn'); if(!btn)return;
  addPresetGroup(btn.dataset.group);
});

qs('#wl-add-btn').addEventListener('click', () => { const v=qs('#wl-input').value; qs('#wl-input').value=''; addTicker(v); });
qs('#wl-input').addEventListener('keydown', e => { if(e.key==='Enter'){const v=qs('#wl-input').value;qs('#wl-input').value='';addTicker(v);} });

qs('#hist-symbol').addEventListener('change', e => { histSymbol=e.target.value; loadHistory(); });
qs('#period-tabs').addEventListener('click', e => {
  const btn=e.target.closest('.period-tab'); if(!btn)return;
  qs('#period-tabs .active')?.classList.remove('active'); btn.classList.add('active');
  histDays=parseInt(btn.dataset.days); loadHistory();
});

qs('#chat-send').addEventListener('click', () => sendChatMessage(qs('#chat-input').value));
qs('#chat-input').addEventListener('keydown', e => { if(e.key==='Enter'&&!e.shiftKey)sendChatMessage(qs('#chat-input').value); });
qs('#chat-chips').addEventListener('click', e => { const c=e.target.closest('.suggest-chip'); if(c)sendChatMessage(c.textContent); });

// ── Init ──────────────────────────────────────────────────────────────────
updateClock();
setInterval(updateClock, 1000);
setInterval(loadAll, 30*60*1000);
loadAll();

// ── Personalisation ───────────────────────────────────────────────────────
(function() {
  const about = qs('.about-section');
  if (!about) return;
  const el = document.createElement('div');
  el.style.cssText = 'text-align:center;padding:20px 0 8px;opacity:0.75';
  el.innerHTML = '<img src="/bro.png" alt="bro handles it himself" style="max-width:300px;width:100%;border-radius:10px;display:inline-block">';
  about.insertAdjacentElement('afterend', el);
})();