/* ── Morning Brief v2 · app.js ──────────────────────────────────────────── */

// ── Constants ──────────────────────────────────────────────────────────────
const PRESET_GROUPS = {
  mag7:   ['AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA'],
  sti:    ['D05.SI','O39.SI','U11.SI','Z74.SI','C6L.SI'],
  crypto: ['BTC-USD','ETH-USD','SOL-USD'],
};
const ALL_PRESETS = [...PRESET_GROUPS.mag7,...PRESET_GROUPS.sti,...PRESET_GROUPS.crypto];

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
function wmo(c){return WMO[c]||WMO[Math.floor(c/10)*10]||{icon:'🌡️',label:'Variable'}}

// ── State ──────────────────────────────────────────────────────────────────
let watchlistTickers = ['AAPL','MSFT','NVDA','AMZN','TSLA','BTC-USD'];
let watchlistTab     = 'all';
let watchlistData    = {};
let chatHistory      = [];
let histSymbol       = '^GSPC';
let histDays         = 30;

// ── Utilities ──────────────────────────────────────────────────────────────
const qs   = s => document.querySelector(s);
const pad  = n => String(n).padStart(2,'0');
const fmtTime = s => { if(!s) return '—'; const d=new Date(s); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const tsAgo = s => { const m=Math.round((Date.now()-new Date(s))/60000); return m<1?'just now':m<60?`${m}m ago`:`${Math.floor(m/60)}h ago`; };

function fmtPrice(price, symbol='') {
  if(price==null) return '—';
  if(symbol==='BTC-USD'||symbol==='ETH-USD'||symbol==='SOL-USD')
    return `$${price.toLocaleString('en-US',{maximumFractionDigits:0})}`;
  if(price<10)  return price.toFixed(4);
  if(price<1000)return price.toFixed(2);
  return price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

function sparkline(vals, up) {
  if(!vals||vals.length<2) return '';
  const w=80,h=36,p=2;
  const mn=Math.min(...vals), mx=Math.max(...vals), rng=mx-mn||1;
  const pts=vals.map((v,i)=>`${(p+(i/(vals.length-1))*(w-p*2)).toFixed(1)},${(h-p-((v-mn)/rng)*(h-p*2)).toFixed(1)}`).join(' ');
  const c=up?'#00e5a0':'#ff4f6d';
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${c}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"/></svg>`;
}

// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
  const now=new Date();
  const days=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  qs('#clock').textContent=`${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  qs('#date-str').textContent=`${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`;
}

// ── Name ───────────────────────────────────────────────────────────────────
function getName(){ return localStorage.getItem('mbName')||'Jeremy'; }
function setName(n){ localStorage.setItem('mbName',n.trim()||'Jeremy'); qs('#display-name').textContent=getName(); }
function openNameModal(){ qs('#name-input').value=getName(); qs('#name-modal').classList.remove('hidden'); qs('#name-input').focus(); }
function closeNameModal(){ qs('#name-modal').classList.add('hidden'); }

// ── Session key (for Supabase watchlist persistence) ───────────────────────
function getSession() {
  let s=localStorage.getItem('mbSession');
  if(!s){ s=crypto.randomUUID(); localStorage.setItem('mbSession',s); }
  return s;
}

// ── V1: Render Brief ───────────────────────────────────────────────────────
function renderBrief(data) {
  const el=qs('#brief-text');
  el.textContent=data.brief||'';
  el.style.opacity='0'; el.style.transition='opacity .6s ease';
  requestAnimationFrame(()=>{ el.style.opacity='1'; });
  const ns=data.news_summary||{};
  const sentEl=qs('#brief-sentiment');
  const sent=(ns.sentiment||'neutral').toLowerCase();
  sentEl.textContent=sent.toUpperCase(); sentEl.className=`sentiment-chip ${sent}`; sentEl.style.display='';
  if(ns.top_theme){ const t=qs('#brief-theme'); t.textContent=`"${ns.top_theme}"`; t.style.display=''; }
  if(data.timestamp){ const t=qs('#brief-ts'); t.textContent=tsAgo(data.timestamp); t.style.display=''; }
}

// ── V1: Render News ────────────────────────────────────────────────────────
function renderNews(data) {
  const ns=data.news_summary||{}, articles=data.articles||[], bullets=ns.bullets||[];
  const items=bullets.length
    ? bullets.map((b,i)=>({title:b,link:articles[i]?.link||'#',category:articles[i]?.category||'global'}))
    : articles.slice(0,5).map(a=>({title:a.title,link:a.link,category:a.category}));
  if(ns.top_theme){ const b=qs('#news-theme-badge'); b.textContent=ns.top_theme; b.style.display=''; }
  qs('#news-list').innerHTML=items.map(item=>{
    const cat=item.category||'global', href=item.link||'#';
    return `<li class="news-item"><span class="news-cat cat-${cat}">${cat}</span><span class="news-title">${href!=='#'?`<a href="${href}" target="_blank" rel="noopener">${item.title}</a>`:item.title}</span></li>`;
  }).join('');
  const ents=ns.key_entities||[];
  if(ents.length){ const r=qs('#news-entities'); r.innerHTML=ents.map(e=>`<span class="entity-chip">${e}</span>`).join(''); r.style.display='flex'; }
}

// ── V1: Render Weather ─────────────────────────────────────────────────────
function renderWeather(data) {
  const cur=data.current||{}, daily=data.daily||{}, hourly=data.hourly||[], info=wmo(cur.weather_code);
  qs('#weather-main').innerHTML=`<div class="weather-hero"><span class="weather-icon">${info.icon}</span><div><div class="weather-temp">${Math.round(cur.temperature??0)}<span class="weather-temp-unit">°C</span></div><div class="weather-label">${info.label}</div><div class="weather-feels">Feels like ${Math.round(cur.feels_like??0)}°C</div></div></div>`;
  if(hourly.length){
    qs('#weather-hourly').innerHTML=hourly.slice(0,7).map(h=>{
      const hi=wmo(h.weather_code);
      return `<div class="hourly-slot"><span class="hourly-time">${pad(new Date(h.time).getHours())}:00</span><span class="hourly-icon">${hi.icon}</span><span class="hourly-temp">${Math.round(h.temp)}°</span><span class="hourly-rain ${h.rain_prob>=60?'high':''}">${h.rain_prob}%</span></div>`;
    }).join('');
  }
  qs('#wval-rain').textContent=`${daily.rain_prob??'—'}%`;
  qs('#wval-humidity').textContent=`${cur.humidity??'—'}%`;
  qs('#wval-wind').textContent=`${Math.round(cur.wind_speed??0)} km/h`;
  qs('#wval-sun').textContent=fmtTime(daily.sunrise);
  qs('#weather-stats').style.display='grid';
}

// ── V1: Render Market ──────────────────────────────────────────────────────
function renderMarket(data) {
  qs('#market-grid').innerHTML=Object.entries(data.market||{}).map(([name,md])=>{
    if(!md.price) return `<div class="market-card"><div class="mcard-name">${name}</div><div class="mcard-na">Unavailable</div></div>`;
    const cls=md.up?'up':'down', arr=md.up?'▲':'▼';
    return `<div class="market-card ${cls}"><div class="mcard-symbol">${md.symbol}</div><div class="mcard-name">${name}</div><div class="mcard-price">${fmtPrice(md.price,md.symbol)}</div><div class="mcard-change ${cls}">${arr} ${Math.abs(md.change_pct).toFixed(2)}%</div><div class="mcard-sparkline">${sparkline(md.sparkline,md.up)}</div></div>`;
  }).join('');
}

// ── V2: Watchlist ──────────────────────────────────────────────────────────
function filterWatchlistTickers(tickers, group) {
  if(group==='all') return tickers;
  if(group==='custom') return tickers.filter(t=>!ALL_PRESETS.includes(t));
  return tickers.filter(t=>(PRESET_GROUPS[group]||[]).includes(t));
}

function renderWatchlistCards(data, tickers, group) {
  const filtered = filterWatchlistTickers(tickers, group);
  const grid = qs('#watchlist-grid');
  if(!filtered.length){
    grid.innerHTML=`<div class="wl-empty">No tickers in this group. Use "+ Add" or the preset buttons above.</div>`;
    return;
  }
  // Get today's news entities for "in news" badges
  const newsEl = qs('#news-entities');
  const newsText = newsEl ? newsEl.textContent.toUpperCase() : '';

  grid.innerHTML = filtered.map(sym=>{
    const d = data[sym];
    if(!d) return `<div class="wl-card"><div class="wl-symbol">${sym}</div><div class="wl-na">Loading…</div></div>`;
    const cls=d.up?'up':'down', arr=d.up?'▲':'▼';
    const inNews = newsText.includes(sym.replace('-USD','').replace('.SI',''));
    return `<div class="wl-card ${cls}">
      <button class="wl-remove" data-sym="${sym}" title="Remove">✕</button>
      <div class="wl-symbol">${sym}</div>
      <div class="wl-name">${d.name}</div>
      ${d.price!=null
        ? `<div class="wl-price">${fmtPrice(d.price,sym)}</div>
           <div class="wl-change ${cls}">${arr} ${Math.abs(d.change_pct).toFixed(2)}%</div>
           ${inNews?'<span class="wl-in-news">📰 In today\'s news</span>':''}
           <div class="wl-sparkline">${sparkline(d.sparkline,d.up)}</div>`
        : `<div class="wl-na">Unavailable</div>`}
    </div>`;
  }).join('');

  // Remove button handlers
  grid.querySelectorAll('.wl-remove').forEach(btn=>{
    btn.addEventListener('click', e=>{ e.stopPropagation(); removeTicker(btn.dataset.sym); });
  });
}

async function loadWatchlist() {
  // 1. Load saved tickers from Supabase
  try {
    const r = await fetch(`/api/watchlist/${getSession()}`).then(r=>r.json());
    if(r.tickers && r.tickers.length) watchlistTickers = r.tickers;
  } catch(e){}

  // 2. Fetch price data
  await refreshWatchlistData();
}

async function refreshWatchlistData() {
  if(!watchlistTickers.length) return;
  try {
    const r = await fetch(`/api/watchlist-data?tickers=${watchlistTickers.join(',')}`).then(r=>r.json());
    watchlistData = r.data || {};
    renderWatchlistCards(watchlistData, watchlistTickers, watchlistTab);
  } catch(e){
    qs('#watchlist-grid').innerHTML='<div class="error-msg" style="grid-column:1/-1">Could not load watchlist data.</div>';
  }
}

async function saveWatchlist() {
  try {
    await fetch(`/api/watchlist/${getSession()}`, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({tickers: watchlistTickers})
    });
  } catch(e){}
}

async function addTicker(sym) {
  sym = sym.trim().toUpperCase();
  if(!sym || watchlistTickers.includes(sym)) return;
  watchlistTickers.push(sym);
  await saveWatchlist();
  await refreshWatchlistData();
}

async function removeTicker(sym) {
  watchlistTickers = watchlistTickers.filter(t=>t!==sym);
  delete watchlistData[sym];
  renderWatchlistCards(watchlistData, watchlistTickers, watchlistTab);
  await saveWatchlist();
}

async function addPresetGroup(group) {
  const syms = (PRESET_GROUPS[group]||[]).filter(s=>!watchlistTickers.includes(s));
  if(!syms.length) return;
  watchlistTickers = [...watchlistTickers, ...syms];
  await saveWatchlist();
  await refreshWatchlistData();
}

// ── V2: Sentiment gauge ────────────────────────────────────────────────────
function buildGaugeSVG(score) {
  score = Math.max(0, Math.min(100, score));
  const cx=110, cy=105, r=82, W=220, H=130;
  const colors=['#ff4f6d','#ff8c42','#ffb830','#7bc67e','#00e5a0'];

  function polar(deg){ const rad=deg*Math.PI/180; return {x:cx+r*Math.cos(rad), y:cy-r*Math.sin(rad)}; }
  function arcPath(a1,a2){
    const s=polar(a1), e=polar(a2);
    return `M${s.x.toFixed(2)},${s.y.toFixed(2)} A${r},${r} 0 0,0 ${e.x.toFixed(2)},${e.y.toFixed(2)}`;
  }

  let arcs='';
  for(let i=0;i<5;i++){
    const a1=180-i*36, a2=180-(i+1)*36;
    arcs+=`<path d="${arcPath(a1,a2)}" stroke="${colors[i]}" stroke-width="14" fill="none" stroke-linecap="butt"/>`;
  }

  // Highlight current segment with glow
  const si=Math.min(4,Math.floor(score/20));
  arcs+=`<path d="${arcPath(180-si*36,180-(si+1)*36)}" stroke="${colors[si]}" stroke-width="18" fill="none" stroke-linecap="butt" opacity="0.9" filter="url(#sg)"/>`;

  // Needle
  const na=180-(score/100)*180;
  const ne=polar(na); const np={x:cx+(ne.x-cx)*0.66, y:cy+(ne.y-cy)*0.66};
  const bl=polar(na+90); const br=polar(na-90);
  const bls={x:cx+(bl.x-cx)*0.06,y:cy+(bl.y-cy)*0.06};
  const brs={x:cx+(br.x-cx)*0.06,y:cy+(br.y-cy)*0.06};
  const ac=colors[si];

  const labels=['Extreme Fear','Fear','Neutral','Greed','Extreme Greed'];
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
  <defs><filter id="sg"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
  ${arcs}
  <polygon points="${np.x.toFixed(1)},${np.y.toFixed(1)} ${bls.x.toFixed(1)},${bls.y.toFixed(1)} ${brs.x.toFixed(1)},${brs.y.toFixed(1)}" fill="${ac}" opacity="0.95"/>
  <circle cx="${cx}" cy="${cy}" r="6" fill="${ac}"/><circle cx="${cx}" cy="${cy}" r="3" fill="#07090f"/>
  <text x="${cx}" y="${cy+20}" text-anchor="middle" font-size="20" font-weight="700" fill="${ac}" font-family="'Space Mono',monospace">${score}</text>
  <text x="${cx}" y="${cy+32}" text-anchor="middle" font-size="7.5" fill="#6a7a9a" font-family="'DM Sans',sans-serif" letter-spacing="1">${labels[si].toUpperCase()}</text>
</svg>`;
}

function renderSentiment(data) {
  // Gauge
  qs('#sentiment-gauge').innerHTML = buildGaugeSVG(data.score||50);
  qs('#sentiment-sub').textContent = `Score: ${data.score||'—'}/100`;

  // Category bars
  const cats = data.categories||{};
  const catLabels = {finance:'Finance',tech:'Tech',global:'Global',singapore:'Singapore'};
  qs('#sentiment-categories').innerHTML = Object.entries(catLabels).map(([key,label])=>{
    const cat = cats[key]||{score:50};
    const sc  = cat.score||50;
    const barColor = sc<40?'var(--down)':sc<60?'var(--amber)':'var(--up)';
    return `<div class="cat-bar-row">
      <span class="cat-bar-label">${label}</span>
      <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${sc}%;background:${barColor}"></div></div>
      <span class="cat-bar-score">${sc}</span>
    </div>`;
  }).join('');

  // Entity heatmap
  const ents = (data.entities||[]).slice(0,8);
  qs('#sentiment-entities').innerHTML = ents.map(e=>{
    const cls = e.sentiment==='positive'?'positive':e.sentiment==='negative'?'negative':'neutral';
    const cnt = e.count>1?` ×${e.count}`:'';
    return `<span class="ent-chip ent-${cls}" title="${e.sentiment}">${e.name}${cnt}</span>`;
  }).join('');
}

async function loadSentiment() {
  try {
    const data = await fetch('/api/sentiment').then(r=>r.json());
    renderSentiment(data);
  } catch(e){
    qs('#sentiment-gauge').innerHTML='<div class="error-msg">Could not load sentiment data.</div>';
  }
}

// ── V2: History chart ──────────────────────────────────────────────────────
function buildHistoryChart(data) {
  const prices = data.prices||[];
  if(prices.length<2) return '<div class="chart-empty">No price data available for this period.</div>';

  const W=800, H=200, P={top:24,right:20,bottom:36,left:62};
  const cW=W-P.left-P.right, cH=H-P.top-P.bottom;
  const vals=prices.map(p=>p.price);
  const mn=Math.min(...vals), mx=Math.max(...vals), rng=mx-mn||1;
  const sx=i=>P.left+(i/(prices.length-1))*cW;
  const sy=v=>P.top+cH-((v-mn)/rng)*cH;
  const isUp=vals[vals.length-1]>=vals[0];
  const lc=isUp?'#00e5a0':'#ff4f6d';
  const gId=`g${Math.random().toString(36).slice(2,7)}`;

  const linePts=prices.map((p,i)=>`${sx(i).toFixed(1)},${sy(p.price).toFixed(1)}`).join(' ');
  const fillPts=`${sx(0).toFixed(1)},${(P.top+cH).toFixed(1)} ${linePts} ${sx(prices.length-1).toFixed(1)},${(P.top+cH).toFixed(1)}`;

  // Y gridlines + labels (4 levels)
  let yLines='';
  for(let i=0;i<=4;i++){
    const v=mn+(rng*i/4), y=sy(v);
    const lbl=v>=10000?`${(v/1000).toFixed(1)}k`:v>=1000?`${(v/1000).toFixed(2)}k`:v.toFixed(2);
    yLines+=`<line x1="${P.left}" y1="${y.toFixed(1)}" x2="${P.left+cW}" y2="${y.toFixed(1)}" stroke="rgba(90,120,255,.06)" stroke-width="1"/>
    <text x="${(P.left-6).toFixed(1)}" y="${(y+3.5).toFixed(1)}" text-anchor="end" font-size="9" fill="#3a4460" font-family="'Space Mono',monospace">${lbl}</text>`;
  }

  // X labels (~6 evenly spaced)
  let xLabels='';
  const step=Math.max(1,Math.floor(prices.length/6));
  for(let i=0;i<prices.length;i+=step){
    xLabels+=`<text x="${sx(i).toFixed(1)}" y="${(H-6).toFixed(1)}" text-anchor="middle" font-size="9" fill="#3a4460" font-family="'Space Mono',monospace">${prices[i].date.slice(5)}</text>`;
  }

  // Sentiment dots
  const sentiments=data.sentiment||[];
  let sentDots='', sentLabel='';
  if(sentiments.length){
    const dateIdx={};
    prices.forEach((p,i)=>{ dateIdx[p.date]=i; });
    sentDots=sentiments.map(s=>{
      const idx=dateIdx[s.date];
      if(idx==null) return '';
      const sc=s.score||50;
      const c=sc<40?'#ff4f6d':sc<60?'#ffb830':'#00e5a0';
      return `<circle cx="${sx(idx).toFixed(1)}" cy="${(P.top+10).toFixed(1)}" r="3.5" fill="${c}" opacity="0.85"><title>${s.label||'Score'}: ${sc}/100 · ${s.date}</title></circle>`;
    }).join('');
    sentLabel=`<text x="${(P.left-6).toFixed(1)}" y="${(P.top+13).toFixed(1)}" text-anchor="end" font-size="7" fill="#3a4460" font-family="'DM Sans',sans-serif">SENT</text>`;
  }

  return `<svg width="100%" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
  <defs><linearGradient id="${gId}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${lc}" stop-opacity="0.12"/>
    <stop offset="100%" stop-color="${lc}" stop-opacity="0"/>
  </linearGradient></defs>
  ${yLines}
  <polygon points="${fillPts}" fill="url(#${gId})"/>
  <polyline points="${linePts}" fill="none" stroke="${lc}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  ${sentDots}${sentLabel}
  ${xLabels}
  <line x1="${P.left}" y1="${P.top}" x2="${P.left}" y2="${P.top+cH}" stroke="rgba(90,120,255,.15)" stroke-width="1"/>
</svg>`;
}

async function loadHistory() {
  qs('#hist-chart').innerHTML='<div class="skel-chart"></div>';
  qs('#hist-stats').style.display='none';
  try {
    const data=await fetch(`/api/history?symbol=${encodeURIComponent(histSymbol)}&days=${histDays}`).then(r=>r.json());
    qs('#hist-chart').innerHTML=buildHistoryChart(data);
    if(data.stats && data.prices?.length>=2){
      const s=data.stats, isUp=s.change_pct>=0;
      const sentNote = data.sentiment?.length
        ? `<div class="hstat"><span class="hstat-label">Sentiment Days</span><span class="hstat-val">${data.sentiment.length} recorded</span></div>` : '';
      qs('#hist-stats').innerHTML=`
        <div class="hstat"><span class="hstat-label">Start</span><span class="hstat-val">${fmtPrice(s.start,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Current</span><span class="hstat-val">${fmtPrice(s.current,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Change</span><span class="hstat-val ${isUp?'up':'down'}">${isUp?'▲':'▼'}${Math.abs(s.change_pct).toFixed(2)}%</span></div>
        <div class="hstat"><span class="hstat-label">High</span><span class="hstat-val">${fmtPrice(s.high,histSymbol)}</span></div>
        <div class="hstat"><span class="hstat-label">Low</span><span class="hstat-val">${fmtPrice(s.low,histSymbol)}</span></div>
        ${sentNote}`;
      qs('#hist-stats').style.display='grid';
    }
  } catch(e){
    qs('#hist-chart').innerHTML='<div class="error-msg">Could not load history data.</div>';
  }
}

// ── V2: Chat ───────────────────────────────────────────────────────────────
function mdToHtml(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/^[-•]\s+(.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*?<\/li>(\n|$))+/gs, m=>`<ul>${m}</ul>`)
    .replace(/\n/g,'<br>');
}

function appendMessage(role, content, sources=[]) {
  const intro=qs('#chat-intro');
  if(intro) intro.style.display='none';

  const wrap=document.createElement('div');
  wrap.className=`chat-msg chat-msg-${role}`;
  const srcHtml = sources.length&&role==='assistant'
    ? `<div class="chat-sources">Sources: ${sources.join(' · ')}</div>` : '';
  wrap.innerHTML=`<div class="chat-bubble">${mdToHtml(content)}</div>${srcHtml}`;

  qs('#chat-messages').appendChild(wrap);
  qs('#chat-messages').scrollTop=qs('#chat-messages').scrollHeight;
  return wrap;
}

function showTyping() {
  const intro=qs('#chat-intro');
  if(intro) intro.style.display='none';
  const el=document.createElement('div');
  el.className='chat-msg chat-msg-assistant'; el.id='chat-typing-indicator';
  el.innerHTML='<div class="chat-typing"><span></span><span></span><span></span></div>';
  qs('#chat-messages').appendChild(el);
  qs('#chat-messages').scrollTop=qs('#chat-messages').scrollHeight;
}

function removeTyping() {
  const el=qs('#chat-typing-indicator');
  if(el) el.remove();
}

async function sendChatMessage(text) {
  text=text.trim();
  if(!text) return;
  const input=qs('#chat-input'), sendBtn=qs('#chat-send');
  input.value='';
  sendBtn.disabled=true;

  appendMessage('user', text);
  chatHistory.push({role:'user', content:text});
  showTyping();

  try {
    const res=await fetch('/api/chat',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text, history:chatHistory.slice(-10)})
    }).then(r=>r.json());

    removeTyping();
    const answer=res.response||'No response received.';
    appendMessage('assistant', answer, res.sources||[]);
    chatHistory.push({role:'assistant', content:answer});
  } catch(e){
    removeTyping();
    appendMessage('assistant','Sorry, I couldn\'t reach the server. Please try again.');
  } finally {
    sendBtn.disabled=false;
    input.focus();
  }
}

// ── Main load ──────────────────────────────────────────────────────────────
async function loadV1() {
  qs('#display-name').textContent=getName();
  const name=getName();

  // Reset skeletons
  qs('#brief-text').innerHTML=`<span class="skel-line" style="width:88%"></span><span class="skel-line" style="width:76%"></span><span class="skel-line" style="width:55%"></span>`;
  qs('#brief-sentiment').style.display='none'; qs('#brief-theme').style.display='none'; qs('#brief-ts').style.display='none';
  qs('#news-list').innerHTML=Array(5).fill('<li class="skel-news"></li>').join('');
  qs('#news-theme-badge').style.display='none'; qs('#news-entities').style.display='none';
  qs('#weather-main').innerHTML='<div class="skel-weather"></div>';
  qs('#weather-hourly').innerHTML=''; qs('#weather-stats').style.display='none';
  qs('#market-grid').innerHTML=Array(6).fill('<div class="market-card skel-card"></div>').join('');
  qs('#refresh-btn').classList.add('loading');

  const [weatherP, marketP, briefP] = [
    fetch('/api/weather').then(r=>r.json()),
    fetch('/api/market').then(r=>r.json()),
    fetch(`/api/brief?name=${encodeURIComponent(name)}`).then(r=>r.json()),
  ];

  weatherP.then(renderWeather).catch(()=>{ qs('#weather-main').innerHTML='<div class="error-msg">Weather unavailable.</div>'; });
  marketP.then(renderMarket).catch(()=>{ qs('#market-grid').innerHTML='<div class="error-msg" style="grid-column:1/-1">Market data unavailable.</div>'; });
  briefP.then(d=>{ renderBrief(d); renderNews(d); }).catch(()=>{
    qs('#brief-text').innerHTML='<span class="error-msg">Brief unavailable. Check your API key.</span>';
    qs('#news-list').innerHTML='<li class="error-msg" style="padding:12px 0">Headlines unavailable.</li>';
  });

  Promise.allSettled([weatherP,marketP,briefP]).then(()=>{ qs('#refresh-btn').classList.remove('loading'); });
}

async function loadV2() {
  // Fire V2 sections in parallel (non-blocking relative to V1)
  loadWatchlist();
  loadSentiment();
  loadHistory();
}

async function loadAll() {
  await loadV1();
  loadV2(); // Don't await — let V2 load independently
}

// ── Event listeners ────────────────────────────────────────────────────────
qs('#refresh-btn').addEventListener('click', loadAll);
qs('#name-btn').addEventListener('click', openNameModal);
qs('#name-cancel').addEventListener('click', closeNameModal);
qs('#name-save').addEventListener('click', ()=>{
  const v=qs('#name-input').value.trim();
  if(v){ setName(v); closeNameModal(); loadAll(); }
});
qs('#name-input').addEventListener('keydown', e=>{ if(e.key==='Enter') qs('#name-save').click(); if(e.key==='Escape') closeNameModal(); });
qs('#name-modal').addEventListener('click', e=>{ if(e.target===qs('#name-modal')) closeNameModal(); });

// Watchlist tabs
qs('#wl-tabs').addEventListener('click', e=>{
  const btn=e.target.closest('.wl-tab'); if(!btn) return;
  qs('#wl-tabs .active')?.classList.remove('active'); btn.classList.add('active');
  watchlistTab=btn.dataset.group;
  renderWatchlistCards(watchlistData, watchlistTickers, watchlistTab);
});

// Preset add buttons
qs('#preset-add-row').addEventListener('click', e=>{
  const btn=e.target.closest('.preset-add-btn'); if(!btn) return;
  addPresetGroup(btn.dataset.group);
});

// Add custom ticker
qs('#wl-add-btn').addEventListener('click', ()=>{
  const v=qs('#wl-input').value; qs('#wl-input').value=''; addTicker(v);
});
qs('#wl-input').addEventListener('keydown', e=>{ if(e.key==='Enter'){ const v=qs('#wl-input').value; qs('#wl-input').value=''; addTicker(v); } });

// History controls
qs('#hist-symbol').addEventListener('change', e=>{ histSymbol=e.target.value; loadHistory(); });
qs('#period-tabs').addEventListener('click', e=>{
  const btn=e.target.closest('.period-tab'); if(!btn) return;
  qs('#period-tabs .active')?.classList.remove('active'); btn.classList.add('active');
  histDays=parseInt(btn.dataset.days); loadHistory();
});

// Chat send
qs('#chat-send').addEventListener('click', ()=>sendChatMessage(qs('#chat-input').value));
qs('#chat-input').addEventListener('keydown', e=>{ if(e.key==='Enter'&&!e.shiftKey) sendChatMessage(qs('#chat-input').value); });

// Suggestion chips
qs('#chat-chips').addEventListener('click', e=>{
  const c=e.target.closest('.suggest-chip'); if(!c) return;
  sendChatMessage(c.textContent);
});

// ── Init ───────────────────────────────────────────────────────────────────
updateClock();
setInterval(updateClock, 1000);
setInterval(loadAll, 30*60*1000); // auto-refresh every 30 min
loadAll();
