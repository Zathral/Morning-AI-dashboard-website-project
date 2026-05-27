/* ── Morning Brief · app.js ─────────────────────────────────────────────── */

// ── WMO weather code map ───────────────────────────────────────────────────
const WMO = {
  0:  { icon: '☀️',  label: 'Clear' },
  1:  { icon: '🌤️', label: 'Mainly Clear' },
  2:  { icon: '⛅',  label: 'Partly Cloudy' },
  3:  { icon: '☁️',  label: 'Overcast' },
  45: { icon: '🌫️', label: 'Foggy' },
  48: { icon: '🌫️', label: 'Icy Fog' },
  51: { icon: '🌦️', label: 'Light Drizzle' },
  53: { icon: '🌦️', label: 'Drizzle' },
  55: { icon: '🌧️', label: 'Heavy Drizzle' },
  61: { icon: '🌧️', label: 'Light Rain' },
  63: { icon: '🌧️', label: 'Rain' },
  65: { icon: '🌧️', label: 'Heavy Rain' },
  80: { icon: '🌦️', label: 'Showers' },
  81: { icon: '🌧️', label: 'Rain Showers' },
  82: { icon: '⛈️',  label: 'Heavy Showers' },
  95: { icon: '⛈️',  label: 'Thunderstorm' },
  99: { icon: '⛈️',  label: 'Heavy Thunderstorm' },
};

function wmo(code) {
  return WMO[code] || WMO[Math.floor(code / 10) * 10] || { icon: '🌡️', label: 'Variable' };
}

// ── Helpers ────────────────────────────────────────────────────────────────

function qs(sel) { return document.querySelector(sel); }

function pad(n) { return String(n).padStart(2, '0'); }

function formatHour(isoStr) {
  const d = new Date(isoStr);
  return `${pad(d.getHours())}:00`;
}

function fmtTime(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtPrice(price, symbol) {
  if (price === null || price === undefined) return '—';
  if (symbol === 'BTC-USD') return `$${price.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  if (price < 10)  return price.toFixed(2);
  if (price < 100) return price.toFixed(2);
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function tsAgo(isoStr) {
  const diff = Math.round((Date.now() - new Date(isoStr)) / 60000);
  if (diff < 1)  return 'just now';
  if (diff < 60) return `${diff}m ago`;
  return `${Math.floor(diff / 60)}h ago`;
}

// ── Sparkline SVG ──────────────────────────────────────────────────────────

function sparkline(values, up) {
  if (!values || values.length < 2) return '';
  const w = 80, h = 36, pad = 2;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = up ? '#00e5a0' : '#ff4f6d';
  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
      <polyline
        points="${pts.join(' ')}"
        fill="none"
        stroke="${color}"
        stroke-width="1.5"
        stroke-linejoin="round"
        stroke-linecap="round"
        opacity="0.9"
      />
    </svg>`;
}

// ── Clock ──────────────────────────────────────────────────────────────────

function updateClock() {
  const now = new Date();
  const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  qs('#clock').textContent =
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  qs('#date-str').textContent =
    `${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`;
}

// ── Name Management ────────────────────────────────────────────────────────

function getName() {
  return localStorage.getItem('mbName') || 'Jeremy';
}

function setName(n) {
  localStorage.setItem('mbName', n.trim() || 'Jeremy');
  qs('#display-name').textContent = getName();
}

function openNameModal() {
  qs('#name-input').value = getName();
  qs('#name-modal').classList.remove('hidden');
  qs('#name-input').focus();
}

function closeNameModal() {
  qs('#name-modal').classList.add('hidden');
}

// ── Render: Brief ──────────────────────────────────────────────────────────

function renderBrief(data) {
  const el = qs('#brief-text');
  el.innerHTML = '';

  // Typewriter-style fade in
  const text = data.brief || '';
  el.textContent = text;
  el.style.opacity = '0';
  el.style.transition = 'opacity .6s ease';
  requestAnimationFrame(() => { el.style.opacity = '1'; });

  const ns = data.news_summary || {};

  // Sentiment chip
  const sentEl = qs('#brief-sentiment');
  const sent = (ns.sentiment || 'neutral').toLowerCase();
  sentEl.textContent  = sent.toUpperCase();
  sentEl.className    = `sentiment-chip ${sent}`;
  sentEl.style.display = '';

  // Top theme
  if (ns.top_theme) {
    const themeEl = qs('#brief-theme');
    themeEl.textContent  = `"${ns.top_theme}"`;
    themeEl.style.display = '';
  }

  // Timestamp
  if (data.timestamp) {
    const tsEl = qs('#brief-ts');
    tsEl.textContent  = tsAgo(data.timestamp);
    tsEl.style.display = '';
  }
}

// ── Render: News ───────────────────────────────────────────────────────────

function renderNews(data) {
  const ns       = data.news_summary || {};
  const articles = data.articles || [];
  const bullets  = ns.bullets || [];

  // Decide what to show: prefer AI bullets, fall back to raw titles
  const items = bullets.length
    ? bullets.map((b, i) => ({
        title:    b,
        link:     articles[i]?.link || '#',
        category: articles[i]?.category || 'global',
      }))
    : articles.slice(0, 5).map(a => ({
        title:    a.title,
        link:     a.link,
        category: a.category,
      }));

  // Theme badge
  if (ns.top_theme) {
    const badge = qs('#news-theme-badge');
    badge.textContent  = ns.top_theme;
    badge.style.display = '';
  }

  // News list
  const list = qs('#news-list');
  list.innerHTML = items.map(item => {
    const cat = item.category || 'global';
    const href = item.link || '#';
    return `
      <li class="news-item">
        <span class="news-cat cat-${cat}">${cat}</span>
        <span class="news-title">
          ${href !== '#'
            ? `<a href="${href}" target="_blank" rel="noopener">${item.title}</a>`
            : item.title}
        </span>
      </li>`;
  }).join('');

  // Entity chips
  const entities = ns.key_entities || [];
  if (entities.length) {
    const row = qs('#news-entities');
    row.innerHTML = entities.map(e =>
      `<span class="entity-chip">${e}</span>`
    ).join('');
    row.style.display = 'flex';
  }
}

// ── Render: Weather ────────────────────────────────────────────────────────

function renderWeather(data) {
  const cur    = data.current || {};
  const daily  = data.daily   || {};
  const hourly = data.hourly  || [];
  const info   = wmo(cur.weather_code);

  // Hero
  qs('#weather-main').innerHTML = `
    <div class="weather-hero">
      <span class="weather-icon">${info.icon}</span>
      <div>
        <div class="weather-temp">
          ${Math.round(cur.temperature ?? 0)}
          <span class="weather-temp-unit">°C</span>
        </div>
        <div class="weather-label">${info.label}</div>
        <div class="weather-feels">Feels like ${Math.round(cur.feels_like ?? 0)}°C</div>
      </div>
    </div>`;

  // Hourly forecast
  const hourlyEl = qs('#weather-hourly');
  if (hourly.length) {
    hourlyEl.innerHTML = hourly.slice(0, 7).map(h => {
      const hi = wmo(h.weather_code);
      const rainClass = h.rain_prob >= 60 ? 'high' : '';
      return `
        <div class="hourly-slot">
          <span class="hourly-time">${formatHour(h.time)}</span>
          <span class="hourly-icon">${hi.icon}</span>
          <span class="hourly-temp">${Math.round(h.temp)}°</span>
          <span class="hourly-rain ${rainClass}">${h.rain_prob}%</span>
        </div>`;
    }).join('');
  }

  // Stats
  qs('#wval-rain').textContent     = `${daily.rain_prob ?? '—'}%`;
  qs('#wval-humidity').textContent = `${cur.humidity ?? '—'}%`;
  qs('#wval-wind').textContent     = `${Math.round(cur.wind_speed ?? 0)} km/h`;
  qs('#wval-sun').textContent      = fmtTime(daily.sunrise);
  qs('#weather-stats').style.display = 'grid';
}

// ── Render: Market ─────────────────────────────────────────────────────────

function renderMarket(data) {
  const market = data.market || {};
  const grid   = qs('#market-grid');

  grid.innerHTML = Object.entries(market).map(([name, md]) => {
    if (md.price === null || md.error) {
      return `
        <div class="market-card">
          <div class="mcard-name">${name}</div>
          <div class="mcard-na">Unavailable</div>
        </div>`;
    }
    const upClass  = md.up ? 'up' : 'down';
    const arrow    = md.up ? '▲' : '▼';
    const priceStr = fmtPrice(md.price, md.symbol);
    const chgStr   = `${arrow} ${Math.abs(md.change_pct).toFixed(2)}%`;

    return `
      <div class="market-card ${upClass}">
        <div class="mcard-symbol">${md.symbol}</div>
        <div class="mcard-name">${name}</div>
        <div class="mcard-price">${priceStr}</div>
        <div class="mcard-change ${upClass}">${chgStr}</div>
        <div class="mcard-sparkline">${sparkline(md.sparkline, md.up)}</div>
      </div>`;
  }).join('');
}

// ── Error helpers ──────────────────────────────────────────────────────────

function briefError() {
  qs('#brief-text').innerHTML =
    '<span class="error-msg">Could not load brief. Check your API key or try refreshing.</span>';
}

function newsError() {
  qs('#news-list').innerHTML =
    '<li class="error-msg" style="padding:12px 0">Could not load headlines.</li>';
}

function weatherError() {
  qs('#weather-main').innerHTML =
    '<div class="error-msg">Could not load weather data.</div>';
}

function marketError() {
  qs('#market-grid').innerHTML =
    '<div class="error-msg" style="grid-column:1/-1;padding:12px 0">Could not load market data.</div>';
}

// ── Main Load ──────────────────────────────────────────────────────────────

async function loadAll() {
  const name = getName();
  qs('#display-name').textContent = name;

  // Reset skeletons
  qs('#brief-text').innerHTML = `
    <span class="skel-line" style="width:88%"></span>
    <span class="skel-line" style="width:76%"></span>
    <span class="skel-line" style="width:55%"></span>`;
  qs('#brief-sentiment').style.display = 'none';
  qs('#brief-theme').style.display     = 'none';
  qs('#brief-ts').style.display        = 'none';

  qs('#news-list').innerHTML = Array(5).fill('<li class="skel-news"></li>').join('');
  qs('#news-theme-badge').style.display = 'none';
  qs('#news-entities').style.display    = 'none';

  qs('#weather-main').innerHTML   = '<div class="skel-weather"></div>';
  qs('#weather-hourly').innerHTML = '';
  qs('#weather-stats').style.display = 'none';

  qs('#market-grid').innerHTML =
    Array(6).fill('<div class="market-card skel-card"></div>').join('');

  // Spinner on refresh button
  qs('#refresh-btn').classList.add('loading');

  // Fire 3 requests in parallel
  const briefReq   = fetch(`/api/brief?name=${encodeURIComponent(name)}`).then(r => r.json());
  const weatherReq = fetch('/api/weather').then(r => r.json());
  const marketReq  = fetch('/api/market').then(r => r.json());

  // Weather — fast
  weatherReq
    .then(renderWeather)
    .catch(weatherError);

  // Market — medium
  marketReq
    .then(renderMarket)
    .catch(marketError);

  // Brief + news — waits for Gemini
  briefReq
    .then(data => {
      renderBrief(data);
      renderNews(data);
    })
    .catch(() => {
      briefError();
      newsError();
    })
    .finally(() => {
      qs('#refresh-btn').classList.remove('loading');
    });

  // Remove spinner when all done
  Promise.allSettled([briefReq, weatherReq, marketReq]).then(() => {
    qs('#refresh-btn').classList.remove('loading');
  });
}

// ── Auto-refresh ───────────────────────────────────────────────────────────

let autoRefreshTimer = null;

function scheduleAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  // Refresh every 30 minutes
  autoRefreshTimer = setInterval(loadAll, 30 * 60 * 1000);
}

// ── Event Listeners ────────────────────────────────────────────────────────

qs('#refresh-btn').addEventListener('click', loadAll);

qs('#name-btn').addEventListener('click', openNameModal);

qs('#name-cancel').addEventListener('click', closeNameModal);

qs('#name-save').addEventListener('click', () => {
  const val = qs('#name-input').value.trim();
  if (val) {
    setName(val);
    closeNameModal();
    loadAll();
  }
});

qs('#name-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') qs('#name-save').click();
  if (e.key === 'Escape') closeNameModal();
});

qs('#name-modal').addEventListener('click', e => {
  if (e.target === qs('#name-modal')) closeNameModal();
});

// ── Init ───────────────────────────────────────────────────────────────────

updateClock();
setInterval(updateClock, 1000);
scheduleAutoRefresh();
loadAll();
