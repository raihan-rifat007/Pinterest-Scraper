'use strict';

const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => Array.from((root || document).querySelectorAll(sel));

const DEFAULTS = {
  mode: 'search',
  download: false,
  details: false,
  show_insights: false,
  limit: 25,
  min_width: 0,
  min_height: 0,
  workers: 4,
  delay: 1.0,
  jitter: 0.5,
  batch_size: 10,
};

let settings = loadSettings();
let currentJob = null;
let lastPins = [];
let currentView = 'search';
let allPins = [];
let filteredPins = [];
let renderedCount = 0;
let loadingMore = false;
const PAGE_SIZE = 25;

let selectionMode = false;
const selectedFiles = new Set();
let pressTimer = null;
let suppressClickUntil = 0;
let pmIndex = -1;

let activeFilter = 'all';
let activeSort = 'newest';
let viewMode = 'masonry';
let detailPinId = null;

const phaseOrder = ['collect', 'details', 'download'];
const phaseState = {};
let currentPhase = null;
let progressStartTime = 0;
let lastProgressUpdate = 0;
let lastProgressCount = 0;

const STORAGE_KEYS = {
  settings: 'ps_settings',
  density: 'ps_density',
  viewMode: 'ps_view_mode',
  sort: 'ps_sort',
  theme: 'theme',
  recent: 'recentSearches',
  history: 'ps_history',
  collections: 'ps_collections',
  sidebar: 'ps_sidebar',
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.settings);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { return { ...DEFAULTS }; }
}
function saveSettings() {
  try { localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(settings)); } catch {}
}
function syncDrawerFromSettings() {
  $('opt-download').checked = settings.download;
  $('opt-details').checked = settings.details;
  $('opt-insights').checked = settings.show_insights;
  $('opt-limit').value = settings.limit;
  $('opt-min-width').value = settings.min_width;
  $('opt-min-height').value = settings.min_height;
  $('opt-workers').value = settings.workers;
  $('opt-delay').value = settings.delay;
  $('opt-jitter').value = settings.jitter;
  $('opt-batch').value = settings.batch_size;
}
function readDrawerToSettings() {
  settings.download = $('opt-download').checked;
  settings.details = $('opt-details').checked;
  settings.show_insights = $('opt-insights').checked;
  settings.limit = +$('opt-limit').value || DEFAULTS.limit;
  settings.min_width = +$('opt-min-width').value || 0;
  settings.min_height = +$('opt-min-height').value || 0;
  settings.workers = +$('opt-workers').value || DEFAULTS.workers;
  settings.delay = parseFloat($('opt-delay').value) || 0;
  settings.jitter = parseFloat($('opt-jitter').value) || 0;
  settings.batch_size = +$('opt-batch').value || DEFAULTS.batch_size;
  saveSettings();
}
function openDrawer(open) {
  $('settings-drawer').classList.toggle('open', open);
  $('settings-drawer').setAttribute('aria-hidden', String(!open));
  $('overlay').classList.toggle('open', open);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
function fmtNum(n) {
  if (n == null) return '0';
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
}
function fmtDuration(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '';
  if (seconds < 60) return Math.round(seconds) + 's';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m + 'm ' + s + 's';
}

window.showToast = function (msg, type = 'info', duration = 3500, action = null) {
  const icons = {
    success: 'bi-check-circle-fill',
    error: 'bi-exclamation-octagon-fill',
    info: 'bi-info-circle-fill',
  };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<i class="bi ${icons[type] || icons.info}"></i><div class="toast-msg"></div>`;
  el.querySelector('.toast-msg').textContent = msg;
  if (action && action.label) {
    const btn = document.createElement('button');
    btn.className = 'toast-action';
    btn.textContent = action.label;
    btn.onclick = () => {
      try { action.onClick && action.onClick(); } finally {
        el.classList.add('out');
        setTimeout(() => el.remove(), 320);
      }
    };
    el.appendChild(btn);
  }
  $('toast-container').appendChild(el);
  if (duration > 0) {
    setTimeout(() => {
      el.classList.add('out');
      setTimeout(() => el.remove(), 320);
    }, duration);
  }
  return el;
};

window.showError = function (msg) {
  if (!msg) return;
  window.showToast(msg, 'error', 4000);
};

async function checkHealth() {
  const dot = $('status-dot');
  const eyebrow = $('hero-eyebrow');
  const statusText = $('hero-status');
  try {
    const res = await fetch('/api/health', { method: 'GET' });
    if (res.ok) {
      if (dot) { dot.classList.remove('offline'); dot.classList.add('online'); }
      if (eyebrow) { eyebrow.classList.remove('offline'); eyebrow.classList.add('online'); }
      if (statusText) statusText.textContent = 'Connected · Pinterest Scraper';
    } else {
      throw new Error('bad status');
    }
  } catch {
    if (dot) { dot.classList.remove('online'); dot.classList.add('offline'); }
    if (eyebrow) { eyebrow.classList.remove('online'); eyebrow.classList.add('offline'); }
    if (statusText) statusText.textContent = 'Server offline';
  }
}

// ====== History ======
function getHistory() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEYS.history) || '[]'); }
  catch { return []; }
}
function addHistory(entry) {
  const list = getHistory();
  list.unshift({ ...entry, ts: Date.now() });
  try { localStorage.setItem(STORAGE_KEYS.history, JSON.stringify(list.slice(0, 100))); } catch {}
  renderSidebarRecent();
  renderHistory();
}
function clearHistory() {
  try { localStorage.removeItem(STORAGE_KEYS.history); } catch {}
  renderSidebarRecent();
  renderHistory();
  window.showToast('History cleared', 'success');
}

// ====== Recent searches ======
function getRecent() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEYS.recent) || '[]'); }
  catch { return []; }
}
function addRecent(q) {
  if (!q) return;
  const list = getRecent().filter(x => x !== q);
  list.unshift(q);
  try { localStorage.setItem(STORAGE_KEYS.recent, JSON.stringify(list.slice(0, 8))); } catch {}
  renderRecent();
  renderSidebarRecent();
}
function renderRecent() {
  const row = $('recent-row');
  if (!row) return;
  const list = getRecent();
  if (!list.length) { row.classList.add('hidden'); row.innerHTML = ''; return; }
  row.classList.remove('hidden');
  row.innerHTML = list.slice(0, 6).map(q =>
    `<button class="suggestion-pill" data-q="${escapeHtml(q)}">
      <i class="bi bi-clock-history"></i> ${escapeHtml(q)}
    </button>`
  ).join('');
  row.querySelectorAll('.suggestion-pill').forEach(b => {
    b.onclick = () => {
      $('search-input').value = b.dataset.q;
      startScrape();
    };
  });
}
function renderSidebarRecent() {
  const list = $('sidebar-recent-list');
  if (!list) return;
  const recents = getRecent();
  if (!recents.length) {
    list.innerHTML = '<div class="sidebar-empty">No recent searches</div>';
    return;
  }
  list.innerHTML = recents.slice(0, 8).map(q => `
    <button class="recent-item" data-q="${escapeHtml(q)}">
      <i class="bi bi-clock-history"></i>
      <span>${escapeHtml(q)}</span>
    </button>
  `).join('');
  list.querySelectorAll('.recent-item').forEach(b => {
    b.onclick = () => {
      $('search-input').value = b.dataset.q;
      startScrape();
      if (window.innerWidth <= 860) closeMobileSidebar();
    };
  });
}

// ====== Scrape ======
async function startScrape() {
  const query = $('search-input').value.trim();
  if (!query) {
    window.showError('Please enter a search term.');
    $('search-input').focus();
    return;
  }
  readDrawerToSettings();

  if (currentView !== 'search') {
    currentView = 'search';
    setActiveNav('search');
  }

  const hero = $('hero');
  if (hero) hero.classList.add('hidden');

  $('empty').classList.add('hidden');
  $('stats-card').classList.add('hidden');
  showSkeletons();
  addRecent(query);
  addHistory({ type: 'search', query });
  initProgress('Collecting pins');
  pushURLState({ q: query });

  const body = { mode: 'search', query, ...settings };
  delete body.show_insights;
  delete body.dedup;

  try {
    const res = await fetch('/api/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      window.showError(`Scraping failed: ${res.status}`);
      $('progress-card').classList.add('hidden');
      return;
    }
    const { job_id } = await res.json();
    currentJob = job_id;
    listenEvents(job_id);
  } catch (e) {
    window.showError('Network error: ' + e.message);
    $('progress-card').classList.add('hidden');
  }
}

function listenEvents(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      handleEvent(ev, es);
    } catch {}
  };
  es.onerror = () => es.close();
}

function handleEvent(ev, es) {
  if (ev.event === 'query_start') {
    const el = $('progress-title');
    if (el) el.textContent = `Query ${ev.index} of ${ev.total}: ${ev.query}`;
  } else if (ev.event === 'queries_done') {
    const el = $('progress-title');
    if (el) el.textContent = `All queries done — ${ev.total} pins`;
  } else if (ev.event === 'phase') {
    const labels = { collect: 'Collecting pins', details: 'Fetching details', download: 'Downloading images' };
    $('progress-title').textContent = labels[ev.phase] || ev.phase;
    $('progress-bar').classList.toggle('indeterminate', ev.phase === 'collect' && !ev.total);
    const prevIdx = phaseOrder.indexOf(ev.phase);
    for (let i = 0; i < prevIdx; i++) {
      if (phaseState[phaseOrder[i]]) phaseState[phaseOrder[i]].done = true;
    }
    currentPhase = ev.phase;
    if (!phaseState[ev.phase]) phaseState[ev.phase] = { count: 0, total: ev.total || 0, done: false };
    if (ev.total) phaseState[ev.phase].total = ev.total;
    progressStartTime = performance.now();
    lastProgressCount = 0;
    lastProgressUpdate = progressStartTime;
    updatePhaseUI();
  } else if (ev.event === 'progress') {
    if (ev.phase) currentPhase = ev.phase;
    if (currentPhase && phaseState[currentPhase]) {
      phaseState[currentPhase].count = ev.count;
      if (ev.total) phaseState[currentPhase].total = ev.total;
      if (phaseState[currentPhase].total > 0 && phaseState[currentPhase].count >= phaseState[currentPhase].total) {
        phaseState[currentPhase].done = true;
      }
    }
    updatePhaseUI();
    updateRate(ev.count);
  } else if (ev.event === 'nothing_new') {
    const meta = $('progress-meta');
    if (meta) meta.textContent = `${meta.textContent} Pins are already up to date.`.trim();
  } else if (ev.event === 'done') {
    es.close();
    finishJob(ev);
  }
}

function updateRate(count) {
  const now = performance.now();
  const rateEl = $('progress-rate');
  if (!rateEl) return;
  const dt = (now - lastProgressUpdate) / 1000;
  if (dt >= 1) {
    const dc = count - lastProgressCount;
    const rate = dc / dt;
    if (rate > 0) rateEl.textContent = `${rate.toFixed(1)}/s`;
    lastProgressUpdate = now;
    lastProgressCount = count;
  }
  const etaEl = $('progress-eta');
  if (etaEl && currentPhase && phaseState[currentPhase]) {
    const st = phaseState[currentPhase];
    if (st.total > 0 && st.count > 0 && st.count < st.total) {
      const elapsed = (now - progressStartTime) / 1000;
      const perItem = elapsed / st.count;
      const remaining = (st.total - st.count) * perItem;
      etaEl.textContent = '~' + fmtDuration(remaining);
    } else {
      etaEl.textContent = '';
    }
  }
}

async function finishJob(ev) {
  const cancelBtn = $('cancel-btn');
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = '<i class="bi bi-x-circle"></i> Cancel';
  }
  if (ev.status === 'cancelled') {
    window.showError('Cancelled');
    $('progress-card').classList.add('hidden');
    currentJob = null;
    return;
  }
  if (ev.status === 'error') {
    window.showError(`Scraping failed: ${ev.error}`);
    $('progress-card').classList.add('hidden');
    currentJob = null;
    return;
  }
  try {
    const res = await fetch(`/api/jobs/${currentJob}/result`);
    const data = await res.json();
    lastPins = data.pins || [];
    window._lastPins = lastPins;
    allPins = lastPins;
    renderStats(ev);
    const hasImages = lastPins.some(p => p.local_file);
    if (!lastPins.length) {
      window.showError(hasImages || ev.stats?.downloaded > 0 ? 'Pins are already up to date.' : 'No results found for this query.');
    } else {
      addHistory({ type: 'result', query: $('search-input').value.trim(), count: lastPins.length });
    }
    applyFilterAndSort();
    renderChart();
    updateGalleryBadge();
    if (currentJob && lastPins.length > 0) {
      $('exp-xlsx').href = `/api/jobs/${currentJob}/export/xlsx`;
      $('exp-xlsx').classList.remove('hidden');
      if (hasImages) {
        $('exp-zip').href = `/api/jobs/${currentJob}/export/zip`;
        $('exp-zip').classList.remove('hidden');
      } else {
        $('exp-zip').classList.add('hidden');
      }
      $('export-bar').classList.remove('hidden');
    } else {
      $('export-bar').classList.add('hidden');
    }
  } catch (e) {
    window.showError('Failed to load results');
  }
  $('progress-card').classList.add('hidden');
  currentJob = null;
}

function initProgress(title) {
  const card = $('progress-card');
  card.classList.remove('hidden');
  $('progress-title').textContent = title;
  $('progress-bar').classList.add('indeterminate');
  $('progress-bar').style.width = '0%';
  $('progress-pct').textContent = '0%';
  $('progress-meta').textContent = '';
  $('progress-eta').textContent = '';
  $('progress-rate').textContent = '';
  const cancelBtn = $('cancel-btn');
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = '<i class="bi bi-x-circle"></i> Cancel';
  }
  phaseOrder.forEach(p => { phaseState[p] = { count: 0, total: 0, done: false }; });
  currentPhase = 'collect';
  progressStartTime = performance.now();
  lastProgressUpdate = progressStartTime;
  lastProgressCount = 0;
  updatePhaseUI();
}

function updatePhaseUI() {
  $$('.phase-chip').forEach(ch => {
    const p = ch.dataset.phase;
    const st = phaseState[p];
    ch.classList.toggle('active', p === currentPhase);
    ch.classList.toggle('done', !!(st && st.done));
  });
  const st = phaseState[currentPhase];
  let pct = 0;
  if (st && st.total > 0) {
    pct = Math.min(100, Math.round((st.count / st.total) * 100));
    $('progress-bar').classList.remove('indeterminate');
  }
  $('progress-bar').style.width = pct + '%';
  $('progress-pct').textContent = pct + '%';
  const bits = [];
  phaseOrder.forEach(p => {
    const s = phaseState[p];
    if (s && s.total > 0) bits.push(`${p}: ${s.count}/${s.total}`);
  });
  if (bits.length) $('progress-meta').textContent = bits.join('  ·  ');
}

function renderStats(ev) {
  const s = ev.stats || {};
  const totalPins = ev.total ?? lastPins.length;
  const downloaded = s.downloaded ?? 0;
  const onDisk = lastPins.filter(p => p.local_file).length;
  const failed = s.failed ?? 0;
  const currentQuery = $('search-input').value.trim();
  let html = `
    <div class="stats-header">
      <span class="stats-title"><i class="bi bi-graph-up-arrow"></i> Results Summary</span>
      ${currentQuery ? `<span class="stats-query">"${escapeHtml(currentQuery)}"</span>` : ''}
    </div>
    <div class="stats-grid">
      <div class="stat-card stat-total">
        <span class="stat-icon"><i class="bi bi-collection"></i></span>
        <div class="stat-data"><span class="stat-num">${totalPins}</span><span class="stat-lbl">Total Pins</span></div>
      </div>
      <div class="stat-card stat-downloaded">
        <span class="stat-icon"><i class="bi bi-cloud-arrow-down"></i></span>
        <div class="stat-data"><span class="stat-num">${downloaded}</span><span class="stat-lbl">Downloaded</span></div>
      </div>
      <div class="stat-card stat-existing">
        <span class="stat-icon"><i class="bi bi-hdd"></i></span>
        <div class="stat-data"><span class="stat-num">${onDisk}</span><span class="stat-lbl">Saved on disk</span></div>
      </div>`;
  if (failed > 0) {
    html += `<div class="stat-card stat-failed">
      <span class="stat-icon"><i class="bi bi-exclamation-triangle"></i></span>
      <div class="stat-data"><span class="stat-num">${failed}</span><span class="stat-lbl">Failed</span></div>
    </div>`;
  }
  if (s.skipped_small) {
    html += `<div class="stat-card">
      <span class="stat-icon"><i class="bi bi-aspect-ratio"></i></span>
      <div class="stat-data"><span class="stat-num">${s.skipped_small}</span><span class="stat-lbl">Too small</span></div>
    </div>`;
  }
  html += '</div>';
  $('stats-card').innerHTML = html;
  $('stats-card').classList.remove('hidden');
}

// ====== Filter + Sort ======
function pinMatchesFilter(pin, filter) {
  if (filter === 'all') return true;
  const isVideo = !!(pin.is_video && pin.video_url);
  if (filter === 'video') return isVideo;
  if (filter === 'downloaded') return !!pin.local_file;
  if (filter === 'hd') {
    const w = pin.width || 0;
    const h = pin.height || 0;
    return (w >= 1000 || h >= 1000);
  }
  if (filter === 'portrait') {
    return pin.width && pin.height && pin.height > pin.width;
  }
  if (filter === 'landscape') {
    return pin.width && pin.height && pin.width > pin.height;
  }
  return true;
}

function sortPins(pins, sort) {
  const arr = [...pins];
  if (sort === 'saves') return arr.sort((a, b) => (b.saves || 0) - (a.saves || 0));
  if (sort === 'comments') return arr.sort((a, b) => (b.comments || 0) - (a.comments || 0));
  if (sort === 'resolution') return arr.sort((a, b) => ((b.width || 0) * (b.height || 0)) - ((a.width || 0) * (a.height || 0)));
  if (sort === 'title') return arr.sort((a, b) => (a.title || a.pin_id).localeCompare(b.title || b.pin_id));
  if (sort === 'oldest') return arr.reverse();
  return arr;
}

function applyFilterAndSort() {
  let pins = allPins.slice();
  if (activeFilter !== 'all') {
    pins = pins.filter(p => pinMatchesFilter(p, activeFilter));
  }
  pins = sortPins(pins, activeSort);
  filteredPins = pins;
  updateFilterStatus();
  resetFeed(pins);
}

function updateFilterStatus() {
  const statusEl = $('filter-status');
  if (!statusEl) return;
  const parts = [];
  if (activeFilter !== 'all') parts.push(`<i class="bi bi-funnel-fill"></i> Filter: <b>${escapeHtml(activeFilter)}</b>`);
  if (activeSort !== 'newest') parts.push(`Sort: <b>${escapeHtml(activeSort)}</b>`);
  if (parts.length) {
    statusEl.classList.remove('hidden');
    statusEl.innerHTML = parts.join(' · ') + ` · <span style="color:var(--text-dim);">${filteredPins.length} of ${allPins.length}</span>
      <button class="clear-filters" id="clear-filters-btn">Clear all</button>`;
    const btn = $('clear-filters-btn');
    if (btn) btn.onclick = () => {
      activeFilter = 'all';
      activeSort = 'newest';
      updateFilterChips();
      updateSortLabel();
      applyFilterAndSort();
    };
  } else {
    statusEl.classList.add('hidden');
  }
}

function updateFilterChips() {
  $$('.filter-chip').forEach(ch => {
    ch.classList.toggle('active', ch.dataset.filter === activeFilter);
  });
}

function updateSortLabel() {
  const labels = {
    newest: 'Newest',
    oldest: 'Oldest',
    saves: 'Most saved',
    comments: 'Most commented',
    resolution: 'Highest res',
    title: 'Title A–Z',
  };
  $('sort-label').textContent = labels[activeSort] || 'Newest';
  $$('#sort-menu button').forEach(b => {
    b.classList.toggle('active', b.dataset.sort === activeSort);
  });
}

// ====== Grid rendering (FIXED) ======
function pinResolutionBadge(pin) {
  if (!pin.width || !pin.height) return '';
  const min = Math.min(pin.width, pin.height);
  let cls = 'res';
  let icon = '';
  if (min >= 1000) { cls = 'hd'; icon = 'HD'; }
  const label = icon || `${pin.width}×${pin.height}`;
  return `<div class="pin-badge ${cls}"><i class="bi bi-badge-hd"></i>${escapeHtml(label)}</div>`;
}
function pinDownloadedBadge(pin) {
  if (!pin.local_file) return '';
  return `<div class="pin-badge dl"><i class="bi bi-check-circle-fill"></i>Saved</div>`;
}
function pinVideoBadge(pin) {
  if (!(pin.is_video && pin.video_url)) return '';
  return `<div class="pin-badge video"><i class="bi bi-play-fill"></i>Video</div>`;
}

function renderGrid(pins, incremental) {
  const grid = $('grid');
  if (!incremental) grid.innerHTML = '';
  const start = incremental ? grid.querySelectorAll('.pin-card').length : 0;
  $('empty').classList.toggle('hidden', pins.length > 0);

  pins.slice(start).forEach((pin, k) => {
    const i = start + k;
    const isVideo = !!(pin.is_video && pin.video_url);
    const local = pin.local_file ? `/api/images/${encodeURIComponent(pin.local_file)}` : '';
    const src = local || pin.image_url || '';

    const card = document.createElement('article');
    card.className = 'pin-card';
    card._pin = pin;
    card.dataset.pinId = pin.pin_id;
    if (selectionMode) card.classList.add('selectable');
    if (selectedFiles.has(pin.local_file)) card.classList.add('selected');
    card.style.animationDelay = `${Math.min(i * 0.03, 0.6)}s`;

    const aspect = pin.width && pin.height ? (pin.width + '/' + pin.height) : null;
    const imgBlock = src
      ? `<img class="pin-img" loading="lazy" src="${src}"
            alt="${escapeHtml(pin.title || pin.pin_id)}"
            referrerpolicy="no-referrer"
            decoding="async"
            ${pin.width ? `width="${pin.width}"` : ''}
            ${pin.height ? `height="${pin.height}"` : ''}
            ${aspect ? `style="aspect-ratio:${aspect}"` : ''}>`
      : `<div class="pin-no-img"><i class="bi bi-image"></i></div>`;

    const badges = [
      pinDownloadedBadge(pin),
      pinVideoBadge(pin),
      pinResolutionBadge(pin),
    ].filter(Boolean).join('');

    const videoBadge = isVideo ? `<div class="video-badge"><i class="bi bi-play-fill"></i></div>` : '';

    const statsLine = (pin.saves || pin.comments)
      ? `<div class="stats">
          ${pin.saves ? `<span><i class="bi bi-bookmark-heart"></i> ${fmtNum(pin.saves)}</span>` : ''}
          ${pin.comments ? `<span><i class="bi bi-chat-dots"></i> ${fmtNum(pin.comments)}</span>` : ''}
        </div>` : '';

    const sizeLine = pin.width
      ? `<div class="stats"><span><i class="bi bi-aspect-ratio"></i> ${pin.width} × ${pin.height}</span></div>`
      : '';

    card.innerHTML = `
      ${imgBlock}
      ${badges ? `<div class="pin-badges">${badges}</div>` : ''}
      ${videoBadge}
      <div class="pin-overlay">
        <div class="pin-card-overlay-actions">
          <button class="pin-action-btn" data-card-action="quick-save" title="Save to collection"><i class="bi bi-bookmark-plus"></i></button>
          <button class="pin-action-btn" data-card-action="quick-delete" title="Remove"><i class="bi bi-trash3"></i></button>
        </div>
        <button class="pin-save" type="button"><i class="bi bi-download"></i> Save</button>
        <div class="pin-meta">
          ${pin.title ? `<div class="title">${escapeHtml(pin.title.slice(0, 80))}</div>` : ''}
          ${statsLine}
          ${sizeLine}
          <div class="links">
            ${pin.pin_url ? `<a href="${pin.pin_url}" target="_blank" rel="noopener"><i class="bi bi-pinterest"></i> Pinterest</a>` : ''}
            ${src ? `<a href="${src}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right"></i> Original</a>` : ''}
          </div>
        </div>
      </div>`;

    // FIXED: robust image load/error handling with timeout fallback
    const imgEl = card.querySelector('.pin-img');
    if (imgEl) {
      let settled = false;
      const settle = (ok) => {
        if (settled) return;
        settled = true;
        imgEl.classList.add(ok ? 'img-loaded' : 'img-failed');
      };

      if (imgEl.complete) {
        settle(imgEl.naturalWidth > 0);
      } else {
        imgEl.addEventListener('load', () => settle(true), { once: true });
        imgEl.addEventListener('error', () => {
          const fallback = pin.image_url || '';
          if (fallback && imgEl.src !== fallback && !imgEl.dataset.triedFallback) {
            imgEl.dataset.triedFallback = '1';
            imgEl.src = fallback;
          } else {
            settle(false);
          }
        });
        // safety: after 8s force-visible so it never stays blank
        setTimeout(() => settle(imgEl.naturalWidth > 0), 8000);
      }
    }

    card.addEventListener('click', (e) => {
      if (selectionMode) return;
      if (e.target.closest('a, button')) return;
      openPinDetail(pin);
    });

    card.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, pin);
    });

    const saveBtn = card.querySelector('.pin-save');
    if (saveBtn) {
      saveBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const target = isVideo ? (pin.video_url || src) : src;
        if (target) window.open(target, '_blank');
      });
    }

    card.querySelectorAll('[data-card-action]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = btn.dataset.cardAction;
        if (action === 'quick-save') quickSaveToCollection(pin);
        else if (action === 'quick-delete') quickRemovePin(pin);
      });
    });

    grid.appendChild(card);
  });
}

function quickSaveToCollection(pin) {
  const cols = getCollections();
  if (!cols.length) {
    window.showToast('No collections yet — create one first', 'info');
    openCollectionsPanel();
    return;
  }
  const target = cols[0];
  if (!target.pins) target.pins = [];
  if (!target.pins.includes(pin.pin_id)) {
    target.pins.push(pin.pin_id);
    saveCollections(cols);
    window.showToast(`Saved to "${target.name}"`, 'success');
    updateNavBadges();
  } else {
    window.showToast(`Already in "${target.name}"`, 'info');
  }
}

function quickRemovePin(pin) {
  if (!pin.local_file) {
    window.showToast('No local file to remove', 'info');
    return;
  }
  const card = document.querySelector(`.pin-card[data-pin-id="${pin.pin_id}"]`);
  if (card) card.classList.add('quick-remove');
  fetch('/api/images/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names: [pin.local_file] }),
  }).then(() => {
    lastPins = lastPins.filter(p => p.pin_id !== pin.pin_id);
    allPins = allPins.filter(p => p.pin_id !== pin.pin_id);
    window._lastPins = lastPins;
    setTimeout(() => {
      card?.remove();
      updateGalleryBadge();
    }, 300);
    window.showToast('Removed', 'success');
  }).catch(() => {
    card?.classList.remove('quick-remove');
    window.showError('Remove failed');
  });
}

function setActiveNav(view) {
  $$('.nav-btn-main').forEach(b => {
    b.classList.toggle('active', b.dataset.nav === view);
  });
}

async function updateGalleryBadge() {
  try {
    const res = await fetch('/api/gallery');
    if (res.ok) {
      const data = await res.json();
      const total = data.total ?? 0;
      const badge = $('gallery-badge');
      if (badge) badge.textContent = total;
      const navBadge = $('nav-gallery-count');
      if (navBadge) navBadge.textContent = total;
    }
  } catch {}
}

async function showGallery() {
  currentView = 'gallery';
  setActiveNav('gallery');
  closeAllPanels();
  $('progress-card').classList.add('hidden');
  $('stats-card').classList.add('hidden');
  $('chart-card').classList.add('hidden');
  const hero = $('hero');
  if (hero) hero.classList.add('hidden');
  const recentRow = $('recent-row');
  if (recentRow) recentRow.classList.add('hidden');
  showSkeletons(12);
  try {
    const res = await fetch('/api/gallery');
    const data = await res.json();
    const pins = data.pins || [];
    $('gallery-badge').textContent = data.total ?? pins.length;
    $('nav-gallery-count').textContent = data.total ?? pins.length;
    if (!pins.length) {
      $('grid').innerHTML = '';
      $('empty-icon').innerHTML = '<i class="bi bi-images"></i>';
      $('empty-title').textContent = 'No downloaded images yet';
      $('empty-text').textContent = "Search and scrape pins with 'Download images' enabled to build your gallery.";
      $('empty').classList.remove('hidden');
      $('export-bar').classList.add('hidden');
    } else {
      $('empty').classList.add('hidden');
      allPins = pins;
      lastPins = pins;
      window._lastPins = pins;
      applyFilterAndSort();
      $('exp-zip').href = '/api/gallery/export/zip';
      $('exp-zip').classList.remove('hidden');
      $('exp-xlsx').classList.add('hidden');
      $('export-bar').classList.remove('hidden');
      $('stats-card').innerHTML = `
        <div class="stats-header">
          <span class="stats-title"><i class="bi bi-images"></i> Gallery</span>
          <span class="stats-query">${pins.length} pins</span>
        </div>
        <div class="stats-grid">
          <div class="stat-card stat-downloaded">
            <span class="stat-icon"><i class="bi bi-hdd"></i></span>
            <div class="stat-data"><span class="stat-num">${pins.length}</span><span class="stat-lbl">Saved on disk</span></div>
          </div>
        </div>`;
      $('stats-card').classList.remove('hidden');
    }
  } catch {
    window.showError('Failed to load gallery');
  }
}

function showSearch() {
  currentView = 'search';
  setActiveNav('search');
  closeAllPanels();
  $('empty-icon').innerHTML = '<i class="bi bi-stars"></i>';
  $('empty-title').textContent = 'Find your inspiration';
  $('empty-text').textContent = 'Search for anything and scrape high-quality images with full metadata.';
  if (lastPins && lastPins.length > 0) {
    $('empty').classList.add('hidden');
    allPins = lastPins;
    applyFilterAndSort();
    const hasImages = lastPins.some(p => p.local_file);
    if (currentJob) {
      $('exp-xlsx').href = `/api/jobs/${currentJob}/export/xlsx`;
      $('exp-xlsx').classList.remove('hidden');
      if (hasImages) {
        $('exp-zip').href = `/api/jobs/${currentJob}/export/zip`;
        $('exp-zip').classList.remove('hidden');
      } else {
        $('exp-zip').classList.add('hidden');
      }
      $('export-bar').classList.remove('hidden');
    }
  } else {
    $('grid').innerHTML = '';
    $('empty').classList.remove('hidden');
    $('stats-card').classList.add('hidden');
    $('export-bar').classList.add('hidden');
    const hero = $('hero');
    if (hero) hero.classList.remove('hidden');
  }
  renderRecent();
}

// FIXED: resetFeed no longer overwrites allPins
function resetFeed(pins) {
  lastPins = pins || lastPins;
  window._lastPins = lastPins;
  renderedCount = 0;
  renderGrid(lastPins.slice(0, PAGE_SIZE));
  renderedCount = Math.min(PAGE_SIZE, lastPins.length);
}

function loadMore() {
  if (loadingMore || renderedCount >= filteredPins.length) return;
  loadingMore = true;
  renderGrid(filteredPins, true);
  renderedCount = filteredPins.length;
  loadingMore = false;
}

function showSkeletons(n = 12) {
  const grid = $('grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const d = document.createElement('div');
    d.className = 'skeleton';
    d.style.height = (140 + Math.random() * 180) + 'px';
    grid.appendChild(d);
  }
}

// ====== Pin Detail Side Panel ======
function openPinDetail(pin) {
  const pins = filteredPins.length ? filteredPins : (window._lastPins || lastPins || []);
  const idx = pins.findIndex(p => p.pin_id === pin.pin_id);
  if (idx < 0) return;
  if (window.innerWidth < 1024) {
    openPinModal(pin);
    return;
  }
  detailPinId = pin.pin_id;
  pmIndex = idx;
  renderPinDetail(pins, idx);
  const panel = $('pin-detail');
  panel.classList.add('open');
  panel.setAttribute('aria-hidden', 'false');
  document.querySelectorAll('.pin-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.pinId === pin.pin_id);
  });
}

function closePinDetail() {
  const panel = $('pin-detail');
  panel.classList.remove('open');
  panel.setAttribute('aria-hidden', 'true');
  detailPinId = null;
  document.querySelectorAll('.pin-card').forEach(c => c.classList.remove('selected'));
}

function renderPinDetail(pins, idx) {
  if (idx < 0 || idx >= pins.length) return;
  const pin = pins[idx];
  const isVideo = !!(pin.is_video && pin.video_url);
  const local = pin.local_file ? `/api/images/${encodeURIComponent(pin.local_file)}` : '';
  const src = local || pin.image_url || '';
  const creatorName = pin.creator_name || pin.creator_username || 'Unknown creator';
  const creatorUser = pin.creator_username ? `@${pin.creator_username}` : '';
  const initial = creatorName ? creatorName.trim()[0].toUpperCase() : '?';

  $('detail-counter').textContent = `${idx + 1} / ${pins.length}`;

  let imageHTML;
  if (isVideo) {
    imageHTML = `<video src="${escapeHtml(pin.video_url)}" muted loop playsinline controls autoplay></video>`;
  } else {
    imageHTML = `<img src="${escapeHtml(src)}" alt="${escapeHtml(pin.title || '')}" referrerpolicy="no-referrer"
      onerror="this.onerror=null;this.src='${escapeHtml(pin.image_url || '')}'">`;
  }

  const badgesHTML = `
    <div class="pd-stats">
      ${pin.saves != null ? `<span class="pd-stat"><i class="bi bi-bookmark-heart"></i> <b>${fmtNum(pin.saves)}</b> saves</span>` : ''}
      ${pin.comments != null ? `<span class="pd-stat"><i class="bi bi-chat-dots"></i> <b>${fmtNum(pin.comments)}</b> comments</span>` : ''}
      ${pin.width ? `<span class="pd-stat"><i class="bi bi-aspect-ratio"></i> <b>${pin.width}×${pin.height}</b></span>` : ''}
      ${pin.local_file ? `<span class="pd-stat"><i class="bi bi-hdd"></i> On disk</span>` : ''}
    </div>`;

  const colorsHTML = (pin.dominant_color || (pin.colors && pin.colors.length))
    ? `<div class="pm-colors-wrap">
        <span class="pm-section-label"><i class="bi bi-palette-fill"></i> Palette</span>
        <div class="pm-colors">
          ${[pin.dominant_color, ...(pin.colors || [])].filter(Boolean).filter((c, i, a) => a.indexOf(c) === i).map(c =>
            `<div class="color-chip" style="background:${escapeHtml(c)}" title="${escapeHtml(c)}" data-color="${escapeHtml(c)}"></div>`
          ).join('')}
        </div>
      </div>` : '';

  $('detail-body').innerHTML = `
    <div class="pd-image">${imageHTML}</div>
    <div class="pd-info">
      <div class="pd-creator">
        <div class="pd-avatar">${escapeHtml(initial)}</div>
        <div class="pd-creator-meta">
          <div class="pd-creator-name">${escapeHtml(creatorName)}</div>
          ${creatorUser ? `<div class="pd-creator-user">${escapeHtml(creatorUser)}</div>` : ''}
        </div>
      </div>
      ${pin.title ? `<div class="pd-title">${escapeHtml(pin.title)}</div>` : ''}
      ${pin.description ? `<div class="pd-desc">${escapeHtml(pin.description.slice(0, 400))}</div>` : ''}
      ${badgesHTML}
      ${colorsHTML}
      <div class="pd-actions">
        ${src ? `<a class="btn primary small" href="${escapeHtml(src)}" target="_blank" download><i class="bi bi-download"></i> Download</a>` : ''}
        <button class="btn ghost small" id="pd-collection"><i class="bi bi-bookmark-plus"></i> Save</button>
        <button class="btn ghost small" id="pd-visual"><i class="bi bi-stars"></i> Similar</button>
        ${pin.pin_url ? `<a class="btn ghost small" href="${escapeHtml(pin.pin_url)}" target="_blank" rel="noopener"><i class="bi bi-pinterest"></i> Pinterest</a>` : ''}
      </div>
    </div>`;

  $('detail-body').querySelectorAll('.color-chip').forEach(c => {
    c.onclick = () => {
      navigator.clipboard?.writeText(c.dataset.color);
      window.showToast(`Copied ${c.dataset.color}`, 'success', 1500);
    };
  });

  const colBtn = $('pd-collection');
  if (colBtn) colBtn.onclick = () => quickSaveToCollection(pin);
  const visBtn = $('pd-visual');
  if (visBtn) visBtn.onclick = () => runVisualSearch(pin.pin_id);

  const openModalBtn = $('detail-open-modal');
  openModalBtn.onclick = () => {
    closePinDetail();
    openPinModal(pin);
  };
}

// ====== Pin Modal ======
function showPinAt(index) {
  const pins = window._lastPins || lastPins || [];
  if (!pins.length) return;
  pmIndex = ((index % pins.length) + pins.length) % pins.length;
  const pin = pins[pmIndex];
  const local = pin.local_file ? `/api/images/${encodeURIComponent(pin.local_file)}` : '';
  const src = local || pin.image_url || '';
  const isVideo = !!(pin.is_video && pin.video_url);
  const pmImg = $('pm-img');
  const pmVideo = $('pm-video');
  if (isVideo && pmVideo) {
    if (pmImg) pmImg.classList.add('hidden');
    pmVideo.classList.remove('hidden');
    pmVideo.src = pin.video_url;
    pmVideo.load();
    pmVideo.play().catch(() => {});
  } else {
    if (pmVideo) { pmVideo.pause(); pmVideo.src = ''; pmVideo.classList.add('hidden'); }
    if (pmImg) {
      pmImg.classList.remove('hidden', 'zoomed', 'pm-img-fade');
      void pmImg.offsetWidth;
      pmImg.src = src;
      pmImg.classList.add('pm-img-fade');
      pmImg.alt = pin.title || pin.pin_id || '';
      pmImg.onerror = () => { pmImg.onerror = null; if (pin.image_url && pmImg.src !== pin.image_url) pmImg.src = pin.image_url; };
    }
  }
  const creatorName = pin.creator_name || pin.creator_username || '';
  const creatorUser = pin.creator_username ? `@${pin.creator_username}` : '';
  const avatarEl = $('pm-creator-avatar');
  if (avatarEl) {
    if (creatorName) avatarEl.textContent = (creatorName.trim()[0] || 'P').toUpperCase();
    else if (pin.creator_username) avatarEl.textContent = (pin.creator_username[0] || 'P').toUpperCase();
    else avatarEl.textContent = '?';
  }
  $('pm-creator-name').textContent = creatorName || 'Unknown creator';
  $('pm-creator-user').textContent = creatorUser;
  const linkEl = $('pm-creator-link');
  if (creatorUser) {
    linkEl.href = `https://www.pinterest.com/${pin.creator_username}/`;
    linkEl.classList.remove('hidden');
  } else linkEl.classList.add('hidden');

  $('pm-title').textContent = pin.title || `Pin ${pin.pin_id}`;
  const descEl = $('pm-desc');
  descEl.textContent = pin.description || '';
  descEl.classList.toggle('hidden', !pin.description);

  $('pm-val-saves').textContent = fmtNum(pin.saves ?? 0);
  $('pm-val-comments').textContent = fmtNum(pin.comments ?? 0);
  $('pm-val-size').textContent = (pin.width && pin.height) ? `${pin.width} × ${pin.height}` : '—';

  const boardRow = $('pm-board-row');
  const boardLink = $('pm-board-name');
  if (pin.board_name) {
    boardRow.classList.remove('hidden');
    boardLink.textContent = pin.board_name;
    boardLink.href = pin.board_url || '#';
  } else boardRow.classList.add('hidden');

  const colorsWrap = $('pm-colors');
  const colorsParent = colorsWrap ? colorsWrap.closest('.pm-colors-wrap') : null;
  if (colorsWrap) {
    colorsWrap.innerHTML = '';
    const palette = [];
    if (pin.dominant_color) palette.push(pin.dominant_color);
    if (Array.isArray(pin.colors)) pin.colors.forEach(c => { if (!palette.includes(c)) palette.push(c); });
    if (palette.length > 0) {
      palette.forEach(color => {
        const c = document.createElement('div');
        c.className = 'color-chip';
        c.style.background = color;
        c.title = `${color} — click to copy`;
        c.onclick = () => {
          navigator.clipboard?.writeText(color);
          c.style.transform = 'scale(1.35)';
          setTimeout(() => c.style.transform = '', 320);
          window.showToast(`Copied ${color}`, 'success', 1500);
        };
        colorsWrap.appendChild(c);
      });
      colorsParent.classList.remove('hidden');
    } else colorsParent.classList.add('hidden');
  }
  const dlBtn = $('pm-download');
  dlBtn.href = isVideo ? (pin.video_url || src) : src;
  dlBtn.download = isVideo ? `pin_${pin.pin_id}.mp4` : `pin_${pin.pin_id}.jpg`;
  $('pm-pin-link').href = pin.pin_url || `https://www.pinterest.com/pin/${pin.pin_id}/`;
  const copyBtn = $('pm-copy-link');
  copyBtn.onclick = async () => {
    const urlToCopy = pin.pin_url || pin.image_url || window.location.href;
    try {
      await navigator.clipboard.writeText(urlToCopy);
      const origHtml = copyBtn.innerHTML;
      copyBtn.innerHTML = '<i class="bi bi-check-lg" style="color:var(--green)"></i>';
      window.showToast('Link copied', 'success', 2000);
      setTimeout(() => { copyBtn.innerHTML = origHtml; }, 1400);
    } catch {}
  };
  const visualBtn = $('pm-visual');
  if (visualBtn) visualBtn.onclick = () => runVisualSearch(pin.pin_id);
}

function openPinModal(pin) {
  const pins = window._lastPins || lastPins || [];
  pmIndex = Math.max(0, pins.findIndex(p => p.pin_id === pin.pin_id));
  showPinAt(pmIndex);
  document.body.style.overflow = 'hidden';
  const m = $('pin-modal');
  m.classList.remove('closing');
  m.classList.add('open');
  m.setAttribute('aria-hidden', 'false');
}
function closePinModal() {
  const pmVideo = $('pm-video');
  if (pmVideo) { pmVideo.pause(); pmVideo.src = ''; pmVideo.classList.add('hidden'); }
  const pmImg = $('pm-img');
  if (pmImg) pmImg.classList.remove('hidden', 'zoomed');
  document.body.style.overflow = '';
  const m = $('pin-modal');
  m.classList.add('closing');
  m.classList.remove('open');
  setTimeout(() => { m.classList.remove('closing'); m.setAttribute('aria-hidden', 'true'); }, 280);
}
function pmNav(dir) { showPinAt(pmIndex + dir); }

async function runVisualSearch(pinId) {
  closePinModal();
  closePinDetail();
  showSkeletons(10);
  $('progress-card').classList.remove('hidden');
  $('progress-title').textContent = 'Finding similar pins…';
  $('progress-bar').classList.add('indeterminate');
  try {
    const res = await fetch(`/api/visual-search?pin_id=${pinId}&limit=30`);
    const data = await res.json();
    $('progress-card').classList.add('hidden');
    if (!res.ok) { window.showError(data.detail || 'Visual search failed'); return; }
    lastPins = data.pins || [];
    window._lastPins = lastPins;
    allPins = lastPins;
    addHistory({ type: 'visual', pin_id: pinId, count: lastPins.length });
    $('stats-card').innerHTML = `
      <div class="stats-header">
        <span class="stats-title"><i class="bi bi-stars"></i> Visually similar pins</span>
        <span class="stats-query">${lastPins.length} pins</span>
      </div>`;
    $('stats-card').classList.remove('hidden');
    $('export-bar').classList.add('hidden');
    $('chart-card').classList.add('hidden');
    applyFilterAndSort();
  } catch {
    $('progress-card').classList.add('hidden');
    window.showError('Visual search failed');
  }
}

function renderChart() {
  if (!settings.show_insights) { $('chart-card').classList.add('hidden'); return; }
  const pins = (window._lastPins || lastPins || []).filter(p => p.saves != null);
  if (pins.length < 2) { $('chart-card').classList.add('hidden'); return; }
  const top = [...pins].sort((a, b) => b.saves - a.saves).slice(0, 12);
  $('chart-card').classList.remove('hidden');
  const dark = document.body.dataset.theme === 'dark';
  const ctx = document.getElementById('chart-canvas');
  if (window._chart) window._chart.destroy();
  window._chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(p => (p.title || p.pin_id).slice(0, 22)),
      datasets: [{ label: 'Saves', data: top.map(p => p.saves), backgroundColor: '#E60023', borderRadius: 7 }],
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: dark ? '#8E8E99' : '#5f5f5f' }, grid: { color: dark ? '#202026' : '#eee' } },
        y: { ticks: { color: dark ? '#8E8E99' : '#5f5f5f' }, grid: { display: false } },
      },
    },
  });
}

// ====== Theme ======
function applyTheme(t) {
  document.body.dataset.theme = t;
  try { localStorage.setItem(STORAGE_KEYS.theme, t); } catch {}
  const icon = document.getElementById('theme-icon');
  if (icon) icon.className = t === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t === 'dark' ? '#08080A' : '#E60023');
  if (window._chart) { window._chart.destroy(); window._chart = null; renderChart(); }
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem(STORAGE_KEYS.theme); } catch {}
  const sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  applyTheme(saved || sys);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.onclick = () => {
    applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
  };
}

// ====== Collections ======
function getCollections() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEYS.collections) || '[]'); }
  catch { return []; }
}
function saveCollections(list) {
  try { localStorage.setItem(STORAGE_KEYS.collections, JSON.stringify(list)); } catch {}
  renderCollections();
  updateNavBadges();
}
function renderCollections() {
  const list = $('collections-list');
  if (!list) return;
  const cols = getCollections();
  if (!cols.length) {
    list.innerHTML = `<div class="panel-empty"><i class="bi bi-bookmark"></i><span>No collections yet</span></div>`;
    return;
  }
  list.innerHTML = cols.map(c => `
    <div class="collection-item" data-col-id="${c.id}">
      <div class="collection-item-info">
        <div class="collection-item-title">${escapeHtml(c.name)}</div>
        <div class="collection-item-meta">${(c.pins || []).length} pins</div>
      </div>
      <button data-col-delete="${c.id}" title="Delete"><i class="bi bi-trash3"></i></button>
    </div>
  `).join('');
  list.querySelectorAll('[data-col-delete]').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const id = btn.dataset.colDelete;
      const cols2 = getCollections().filter(c => c.id !== id);
      saveCollections(cols2);
      window.showToast('Collection removed', 'success');
    };
  });
  list.querySelectorAll('.collection-item').forEach(item => {
    item.onclick = () => {
      const id = item.dataset.colId;
      const col = getCollections().find(c => c.id === id);
      if (!col) return;
      const pins = (window._lastPins || []).filter(p => (col.pins || []).includes(p.pin_id));
      if (!pins.length) {
        window.showToast('No pins from current results in this collection', 'info');
        return;
      }
      allPins = pins;
      applyFilterAndSort();
      closeAllPanels();
      window.showToast(`Showing "${col.name}" (${pins.length})`, 'success');
    };
  });
}

function updateNavBadges() {
  const cols = getCollections();
  const colBadge = $('nav-collections-count');
  if (colBadge) colBadge.textContent = cols.length;
  refreshSchedulesBadge();
}

async function refreshSchedulesBadge() {
  try {
    const res = await fetch('/api/schedules');
    if (res.ok) {
      const data = await res.json();
      const badge = $('nav-schedules-count');
      if (badge) badge.textContent = (data.schedules || []).length;
      renderSchedules(data.schedules || []);
    }
  } catch {}
}

function renderSchedules(list) {
  const el = $('schedules-list');
  if (!el) return;
  if (!list.length) {
    el.innerHTML = `<div class="panel-empty"><i class="bi bi-clock"></i><span>No active schedules</span></div>`;
    return;
  }
  el.innerHTML = list.map(s => `
    <div class="schedule-item">
      <div class="schedule-item-info">
        <div class="schedule-item-title">${escapeHtml(s.query)}</div>
        <div class="schedule-item-meta">${escapeHtml(s.mode)} · every ${s.interval_hours}h · limit ${s.limit}${s.runs ? ' · ran ' + s.runs + 'x' : ''}</div>
      </div>
      <button data-sch-delete="${s.id}" title="Delete"><i class="bi bi-trash3"></i></button>
    </div>
  `).join('');
  el.querySelectorAll('[data-sch-delete]').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.schDelete;
      try {
        await fetch(`/api/schedules/${id}`, { method: 'DELETE' });
        window.showToast('Schedule removed', 'success');
        refreshSchedulesBadge();
      } catch {
        window.showError('Delete failed');
      }
    };
  });
}

async function addSchedule() {
  const q = $('sch-query').value.trim();
  if (!q) { window.showError('Enter a query'); return; }
  const body = {
    mode: $('sch-mode').value,
    query: q,
    interval_hours: +$('sch-interval').value || 24,
    limit: +$('sch-limit').value || 25,
  };
  try {
    const res = await fetch('/api/schedules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('Failed');
    window.showToast('Schedule created', 'success');
    $('sch-query').value = '';
    refreshSchedulesBadge();
    addHistory({ type: 'schedule', query: q });
  } catch {
    window.showError('Failed to create schedule');
  }
}

// ====== History ======
function renderHistory() {
  const list = $('history-list');
  if (!list) return;
  const hist = getHistory();
  if (!hist.length) {
    list.innerHTML = `<div class="panel-empty"><i class="bi bi-clock-history"></i><span>No history yet</span></div>`;
    return;
  }
  list.innerHTML = hist.slice(0, 60).map((h, i) => {
    const icon = h.type === 'search' ? 'bi-search' :
                 h.type === 'visual' ? 'bi-stars' :
                 h.type === 'schedule' ? 'bi-clock-history' :
                 h.type === 'result' ? 'bi-check-circle' :
                 h.type === 'delete' ? 'bi-trash3' : 'bi-activity';
    const when = new Date(h.ts).toLocaleString();
    const title = h.query || h.pin_id || h.type;
    const meta = `${h.type}${h.count != null ? ' · ' + h.count + ' pins' : ''} · ${when}`;
    return `<div class="history-item" data-hist-idx="${i}">
      <div class="history-item-info">
        <div class="history-item-title"><i class="bi ${icon}" style="color:var(--text-muted);margin-right:6px;"></i>${escapeHtml(title)}</div>
        <div class="history-item-meta">${escapeHtml(meta)}</div>
      </div>
    </div>`;
  }).join('');
}

function openHistoryPanel() {
  renderHistory();
  openPanel('history-panel');
}

// ====== Side panels ======
function closeAllPanels() {
  $$('.side-panel').forEach(p => p.classList.remove('open'));
  closePinDetail();
  closeContextMenu();
  closeSortMenu();
}
function openPanel(id) {
  closeAllPanels();
  const p = document.getElementById(id);
  if (p) {
    p.classList.add('open');
    p.setAttribute('aria-hidden', 'false');
  }
}
function openSchedulesPanel() { refreshSchedulesBadge(); openPanel('schedules-panel'); }
function openCollectionsPanel() { renderCollections(); openPanel('collections-panel'); }

// ====== Selection ======
function setSelectionMode(on) {
  selectionMode = on;
  document.querySelectorAll('.pin-card').forEach(c => c.classList.toggle('selectable', on));
  if (!on) {
    selectedFiles.clear();
    document.querySelectorAll('.pin-card.selected').forEach(c => c.classList.remove('selected'));
  }
  updateSelBar();
}
function updateSelBar() {
  const bar = document.getElementById('selection-bar');
  bar.classList.toggle('show', selectionMode);
  bar.classList.toggle('hidden', !selectionMode);
  document.getElementById('sel-count').textContent = `${selectedFiles.size} selected`;
}
function toggleSelect(card) {
  const pin = card._pin;
  if (!pin || !pin.local_file) {
    window.showToast('Only downloaded images can be selected', 'info', 2200);
    return;
  }
  if (selectedFiles.has(pin.local_file)) {
    selectedFiles.delete(pin.local_file);
    card.classList.remove('selected');
  } else {
    selectedFiles.add(pin.local_file);
    card.classList.add('selected');
  }
  updateSelBar();
}

async function bulkDownloadSelected() {
  if (!selectedFiles.size) return;
  const pins = (window._lastPins || []).filter(p => selectedFiles.has(p.local_file));
  let n = 0;
  for (const p of pins) {
    const url = `/api/images/${encodeURIComponent(p.local_file)}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = p.local_file;
    a.click();
    n++;
    await new Promise(r => setTimeout(r, 250));
  }
  window.showToast(`Downloading ${n} file${n === 1 ? '' : 's'}`, 'success');
}

async function bulkSaveToCollection() {
  if (!selectedFiles.size) return;
  const cols = getCollections();
  if (!cols.length) {
    window.showToast('Create a collection first', 'info');
    openCollectionsPanel();
    return;
  }
  const target = cols[0];
  if (!target.pins) target.pins = [];
  const pins = (window._lastPins || []).filter(p => selectedFiles.has(p.local_file));
  let added = 0;
  for (const p of pins) {
    if (!target.pins.includes(p.pin_id)) { target.pins.push(p.pin_id); added++; }
  }
  saveCollections(cols);
  window.showToast(`Added ${added} pin${added === 1 ? '' : 's'} to "${target.name}"`, 'success');
}

// ====== Command Palette ======
function getCommands() {
  const cmds = [
    { id: 'focus-search', icon: 'bi-search', label: 'Search pins', sub: 'Focus search box',
      action: () => { closeCP(); $('search-input').focus(); } },
    { id: 'open-gallery', icon: 'bi-images', label: 'Open Gallery', sub: 'View downloaded images',
      action: () => { closeCP(); showGallery(); } },
    { id: 'open-schedules', icon: 'bi-clock-history', label: 'Open Schedules', sub: 'Manage recurring scrapes',
      action: () => { closeCP(); openSchedulesPanel(); } },
    { id: 'open-collections', icon: 'bi-bookmark-heart', label: 'Open Collections', sub: 'Saved pin groups',
      action: () => { closeCP(); openCollectionsPanel(); } },
    { id: 'open-history', icon: 'bi-arrow-counterclockwise', label: 'Open History', sub: 'Recent activity',
      action: () => { closeCP(); openHistoryPanel(); } },
    { id: 'toggle-theme', icon: 'bi-circle-half', label: 'Toggle theme', sub: 'Switch light / dark',
      action: () => { closeCP(); $('theme-btn').click(); } },
    { id: 'toggle-focus', icon: 'bi-fullscreen', label: 'Toggle focus mode', sub: 'Hide chrome',
      action: () => { closeCP(); toggleFocusMode(); } },
    { id: 'open-settings', icon: 'bi-gear-fill', label: 'Open Settings', sub: 'Configure options',
      action: () => { closeCP(); $('settings-btn').click(); } },
    { id: 'view-masonry', icon: 'bi-columns-gap', label: 'Masonry view', sub: 'Pin columns',
      action: () => { closeCP(); applyViewMode('masonry'); } },
    { id: 'view-grid', icon: 'bi-grid-3x3-gap', label: 'Grid view', sub: 'Uniform grid',
      action: () => { closeCP(); applyViewMode('grid'); } },
    { id: 'view-list', icon: 'bi-list-ul', label: 'List view', sub: 'Row layout',
      action: () => { closeCP(); applyViewMode('list'); } },
    { id: 'reset-filters', icon: 'bi-funnel', label: 'Reset filters', sub: 'Clear filter & sort',
      action: () => {
        closeCP();
        activeFilter = 'all'; activeSort = 'newest';
        updateFilterChips(); updateSortLabel();
        applyFilterAndSort();
      } },
  ];
  if (currentView === 'gallery') {
    cmds.push({ id: 'gallery-zip', icon: 'bi-file-zip', label: 'Download gallery ZIP', sub: 'All images',
      action: () => { closeCP(); $('exp-zip')?.click(); } });
  } else if (lastPins.length) {
    cmds.push({ id: 'export-xlsx', icon: 'bi-file-spreadsheet', label: 'Export XLSX', sub: 'Metadata',
      action: () => { closeCP(); $('exp-xlsx')?.click(); } });
  }
  return cmds;
}

let cpIndex = -1;
let cpItems = [];

function fuzzyScore(text, q) {
  if (!q) return 1;
  text = text.toLowerCase(); q = q.toLowerCase();
  let score = 0, ti = 0, qi = 0, consec = 0;
  while (ti < text.length && qi < q.length) {
    if (text[ti] === q[qi]) {
      score += 10 + consec * 4;
      if (ti === 0 || text[ti - 1] === ' ' || text[ti - 1] === '-') score += 6;
      consec++;
      qi++;
    } else consec = 0;
    ti++;
  }
  return qi === q.length ? score - text.length * 0.05 : 0;
}

function renderCP(query = '') {
  const cpBody = $('cp-body');
  const q = query.trim();
  const sections = [];
  const commands = getCommands();

  if (!q) {
    const recents = getRecent().slice(0, 5);
    if (recents.length) {
      sections.push({
        title: 'Recent searches',
        items: recents.map(r => ({
          icon: 'bi-clock-history',
          label: r,
          sub: 'Recent search',
          action: () => { closeCP(); $('search-input').value = r; startScrape(); },
        })),
      });
    }
    sections.push({ title: 'Commands', items: commands });
  } else {
    const scored = commands
      .map(c => ({ c, s: Math.max(fuzzyScore(c.label, q), fuzzyScore(c.sub || '', q) * 0.7) }))
      .filter(x => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map(x => x.c);
    if (scored.length) sections.push({ title: 'Commands', items: scored });
    sections.push({
      title: 'Search',
      items: [{
        icon: 'bi-search',
        label: `Search for "${query}"`,
        sub: 'Start scrape',
        action: () => { closeCP(); $('search-input').value = query; startScrape(); },
      }],
    });
  }

  cpItems = [];
  let html = '';
  sections.forEach(sec => {
    html += `<div class="cp-section">${sec.title}</div>`;
    sec.items.forEach(it => {
      const idx = cpItems.length;
      cpItems.push(it);
      html += `<div class="cp-item" data-idx="${idx}">
        <div class="cp-icon"><i class="bi ${it.icon}"></i></div>
        <div class="cp-content">
          <div class="cp-label">${escapeHtml(it.label)}</div>
          ${it.sub ? `<div class="cp-sub">${escapeHtml(it.sub)}</div>` : ''}
        </div>
      </div>`;
    });
  });
  cpBody.innerHTML = html || `<div class="cp-empty"><i class="bi bi-search" style="font-size:1.6rem;display:block;margin-bottom:10px;opacity:.4"></i>No results</div>`;
  cpBody.querySelectorAll('.cp-item').forEach(el => {
    el.addEventListener('mouseenter', () => setCPIndex(+el.dataset.idx));
    el.addEventListener('click', () => {
      const it = cpItems[+el.dataset.idx];
      if (it) it.action();
    });
  });
  setCPIndex(0);
}
function setCPIndex(i) {
  cpIndex = i;
  const cpBody = $('cp-body');
  cpBody.querySelectorAll('.cp-item').forEach((el, n) => el.classList.toggle('active', n === i));
  const el = cpBody.querySelector(`.cp-item[data-idx="${i}"]`);
  if (el) el.scrollIntoView({ block: 'nearest' });
}
function openCP() {
  const cp = $('command-palette');
  const cpInput = $('cp-input');
  cp.classList.add('open');
  cp.setAttribute('aria-hidden', 'false');
  cpInput.value = '';
  renderCP('');
  setTimeout(() => cpInput.focus(), 50);
}
function closeCP() {
  const cp = $('command-palette');
  cp.classList.remove('open');
  cp.setAttribute('aria-hidden', 'true');
}

// ====== Context Menu ======
let contextMenuTarget = null;
function openContextMenu(x, y, pin) {
  contextMenuTarget = pin;
  const menu = $('context-menu');
  const actions = [
    { icon: 'bi-eye', label: 'Open details', fn: () => openPinDetail(pin) },
    { icon: 'bi-bookmark-plus', label: 'Save to collection', fn: () => quickSaveToCollection(pin) },
    { icon: 'bi-stars', label: 'Find similar', fn: () => runVisualSearch(pin.pin_id) },
    { icon: 'bi-link-45deg', label: 'Copy link', fn: () => {
      const url = pin.pin_url || pin.image_url || '';
      if (url) { navigator.clipboard?.writeText(url); window.showToast('Link copied', 'success'); }
    } },
    { sep: true },
    { icon: 'bi-download', label: 'Save image', fn: () => {
      const src = pin.local_file ? `/api/images/${encodeURIComponent(pin.local_file)}` : pin.image_url;
      if (src) window.open(src, '_blank');
    } },
  ];
  if (pin.local_file) {
    actions.push({ icon: 'bi-trash3', label: 'Remove from disk', danger: true, fn: () => quickRemovePin(pin) });
  }
  menu.innerHTML = actions.map(a => {
    if (a.sep) return '<div class="context-sep"></div>';
    return `<button class="${a.danger ? 'danger' : ''}" data-ctx><i class="bi ${a.icon}"></i>${escapeHtml(a.label)}</button>`;
  }).join('');
  const btns = menu.querySelectorAll('button[data-ctx]');
  let idx = 0;
  actions.forEach(a => {
    if (a.sep) return;
    btns[idx].onclick = () => { closeContextMenu(); a.fn(); };
    idx++;
  });
  menu.classList.remove('hidden');
  const rect = menu.getBoundingClientRect();
  const mw = 220, mh = rect.height || 260;
  menu.style.left = Math.min(x, window.innerWidth - mw - 12) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - mh - 12) + 'px';
}
function closeContextMenu() {
  const menu = $('context-menu');
  menu.classList.add('hidden');
  contextMenuTarget = null;
}

// ====== Sort Menu ======
function openSortMenu() { $('sort-menu').classList.remove('hidden'); }
function closeSortMenu() { $('sort-menu').classList.add('hidden'); }

// ====== View mode ======
function applyViewMode(mode) {
  viewMode = mode;
  document.body.dataset.viewMode = mode;
  try { localStorage.setItem(STORAGE_KEYS.viewMode, mode); } catch {}
  $$('#view-modes button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}
function initViewMode() {
  let saved = 'masonry';
  try { saved = localStorage.getItem(STORAGE_KEYS.viewMode) || 'masonry'; } catch {}
  applyViewMode(saved);
}

// ====== Focus mode ======
function toggleFocusMode() {
  const on = document.body.classList.toggle('focus-mode');
  if (on) {
    let exit = document.querySelector('.focus-exit');
    if (!exit) {
      exit = document.createElement('button');
      exit.className = 'focus-exit';
      exit.innerHTML = '<i class="bi bi-fullscreen-exit"></i> Exit focus';
      exit.onclick = toggleFocusMode;
      document.body.appendChild(exit);
    }
  } else {
    const exit = document.querySelector('.focus-exit');
    if (exit) exit.remove();
  }
}

// ====== Density ======
function applyDensity(density) {
  const btns = $$('#density-toggle button');
  btns.forEach(x => x.classList.toggle('active', x.dataset.density === density));
  document.body.dataset.density = density;
  try { localStorage.setItem(STORAGE_KEYS.density, density); } catch {}
}
function initDensity() {
  const container = $('density-toggle');
  if (!container) return;
  container.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-density]');
    if (!btn) return;
    e.preventDefault();
    applyDensity(btn.dataset.density);
  });
  let saved = 'default';
  try { saved = localStorage.getItem(STORAGE_KEYS.density) || 'default'; } catch {}
  applyDensity(saved);
}

// ====== Sidebar ======
function initSidebar() {
  let state = 'expanded';
  try { state = localStorage.getItem(STORAGE_KEYS.sidebar) || 'expanded'; } catch {}
  document.body.dataset.sidebar = state;

  const collapse = $('sidebar-collapse');
  if (collapse) {
    collapse.onclick = () => {
      const next = document.body.dataset.sidebar === 'collapsed' ? 'expanded' : 'collapsed';
      document.body.dataset.sidebar = next;
      try { localStorage.setItem(STORAGE_KEYS.sidebar, next); } catch {}
    };
  }
  const mobileToggle = $('mobile-sidebar-toggle');
  if (mobileToggle) {
    mobileToggle.onclick = () => {
      const open = document.body.dataset.sidebar === 'mobile-open';
      document.body.dataset.sidebar = open ? 'expanded' : 'mobile-open';
    };
  }
  let mo = document.querySelector('.mobile-overlay');
  if (!mo) {
    mo = document.createElement('div');
    mo.className = 'mobile-overlay';
    document.body.appendChild(mo);
    mo.onclick = () => { if (window.innerWidth <= 860) closeMobileSidebar(); };
  }
}
function closeMobileSidebar() {
  if (document.body.dataset.sidebar === 'mobile-open') {
    document.body.dataset.sidebar = 'expanded';
  }
}

// ====== URL state ======
function pushURLState(extra = {}) {
  const params = new URLSearchParams();
  const q = $('search-input').value.trim();
  if (q) params.set('q', q);
  if (activeFilter !== 'all') params.set('filter', activeFilter);
  if (activeSort !== 'newest') params.set('sort', activeSort);
  if (viewMode !== 'masonry') params.set('view', viewMode);
  const url = params.toString() ? '?' + params.toString() : '';
  try { history.replaceState(null, '', url); } catch {}
}
function readURLState() {
  const params = new URLSearchParams(window.location.search);
  const q = params.get('q');
  if (q) $('search-input').value = q;
  const f = params.get('filter');
  if (f) activeFilter = f;
  const s = params.get('sort');
  if (s) activeSort = s;
  const v = params.get('view');
  if (v) viewMode = v;
  updateFilterChips();
  updateSortLabel();
  applyViewMode(viewMode);
  if (q) setTimeout(() => startScrape(), 200);
}

// ====== Suggestions ======
function initSuggestions() {
  const sugList = $('suggest-list');
  const input = $('search-input');
  if (!sugList || !input) return;
  let debounceTimer = null;
  let sugItems = [];
  let sugIndex = -1;
  let sugAbort = null;
  function hideSuggest() { sugList.classList.remove('show'); sugList.innerHTML = ''; sugItems = []; sugIndex = -1; }
  function highlight(q, text) {
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return escapeHtml(text);
    return escapeHtml(text.slice(0, i)) + '<b>' + escapeHtml(text.slice(i, i + q.length)) + '</b>' + escapeHtml(text.slice(i + q.length));
  }
  function renderSuggest(q, items) {
    sugItems = items;
    sugIndex = -1;
    sugList.innerHTML = items.map(s => {
      if (s.type === 'user') {
        return `<li role="option" class="sug-user">
          <img class="sug-avatar" src="${s.image || ''}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
          <span class="sug-texts">
            <span class="sug-name">${highlight(q, s.text)}${s.verified ? ` <span class="sug-verified"><i class="bi bi-patch-check-fill"></i></span>` : ''}</span>
            ${s.sub ? `<span class="sug-sub">${escapeHtml(s.sub)}</span>` : ''}
          </span>
        </li>`;
      }
      return `<li role="option"><span class="sug-ico"><i class="bi bi-search"></i></span><span>${highlight(q, s.text)}</span></li>`;
    }).join('');
    sugList.classList.toggle('show', items.length > 0);
    [...sugList.children].forEach((li, i) => {
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = sugItems[i].text;
        hideSuggest();
        startScrape();
      });
    });
  }
  input.addEventListener('input', () => {
    const box = input.closest('.search-box');
    if (box) box.classList.toggle('has-value', input.value.length > 0);
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) { hideSuggest(); return; }
    debounceTimer = setTimeout(async () => {
      if (sugAbort) sugAbort.abort();
      sugAbort = new AbortController();
      try {
        const r = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`, { signal: sugAbort.signal });
        const { suggestions } = await r.json();
        if (input.value.trim() === q) renderSuggest(q, suggestions || []);
      } catch {}
    }, 350);
  });
  input.addEventListener('keydown', (e) => {
    if (sugItems.length === 0) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sugIndex = (sugIndex + (e.key === 'ArrowDown' ? 1 : -1) + sugItems.length) % sugItems.length;
      [...sugList.children].forEach((li, i) => li.classList.toggle('active', i === sugIndex));
    } else if (e.key === 'Enter') {
      if (sugIndex >= 0 && sugItems[sugIndex]) {
        e.preventDefault();
        input.value = sugItems[sugIndex].text;
        hideSuggest();
        startScrape();
      }
    } else if (e.key === 'Escape') hideSuggest();
  });
  input.addEventListener('blur', () => setTimeout(hideSuggest, 150));
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-box')) hideSuggest();
  });
  const clearBtn = $('search-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      input.value = '';
      input.focus();
      const box = input.closest('.search-box');
      if (box) box.classList.remove('has-value');
      hideSuggest();
    });
  }
}

function initCommandPalette() {
  const cp = $('command-palette');
  const cpInput = $('cp-input');
  const cpBackdrop = cp.querySelector('.cp-backdrop');
  if (cpBackdrop) cpBackdrop.addEventListener('click', closeCP);
  const kbdTrigger = $('search-kbd');
  if (kbdTrigger) {
    kbdTrigger.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openCP();
    });
  }
  cpInput.addEventListener('input', () => renderCP(cpInput.value));
  cpInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeCP(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setCPIndex(Math.min(cpIndex + 1, cpItems.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCPIndex(Math.max(cpIndex - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); const it = cpItems[cpIndex]; if (it) it.action(); }
  });
}

function initKeyboard() {
  document.addEventListener('keydown', (e) => {
    const tag = (document.activeElement || {}).tagName;
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    const mod = e.metaKey || e.ctrlKey;

    if (mod && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const cp = $('command-palette');
      if (cp.classList.contains('open')) closeCP(); else openCP();
      return;
    }
    if (mod && e.key.toLowerCase() === 'b') {
      e.preventDefault();
      const next = document.body.dataset.sidebar === 'collapsed' ? 'expanded' : 'collapsed';
      document.body.dataset.sidebar = next;
      try { localStorage.setItem(STORAGE_KEYS.sidebar, next); } catch {}
      return;
    }

    if (isInput) return;

    if (e.key === '/') { e.preventDefault(); $('search-input').focus(); return; }
    if (e.key === '?') { e.preventDefault(); openShortcuts(); return; }
    if (e.key === 'Escape') {
      const cp = $('command-palette');
      const drawer = $('settings-drawer');
      const modal = $('pin-modal');
      const shortcuts = $('shortcuts-overlay');
      if (shortcuts.classList.contains('open')) { closeShortcuts(); return; }
      if (cp.classList.contains('open')) { closeCP(); return; }
      if (drawer.classList.contains('open')) { openDrawer(false); return; }
      if (modal.classList.contains('open')) { closePinModal(); return; }
      if ($('pin-detail').classList.contains('open')) { closePinDetail(); return; }
      if (document.querySelector('.side-panel.open')) { closeAllPanels(); return; }
      if (selectionMode) { setSelectionMode(false); return; }
      if (document.body.classList.contains('focus-mode')) { toggleFocusMode(); return; }
    }
    if (e.key.toLowerCase() === 'f' && !mod) {
      if (!$('pin-modal').classList.contains('open') && !$('command-palette').classList.contains('open')) {
        e.preventDefault();
        toggleFocusMode();
      }
      return;
    }
    if (e.key.toLowerCase() === 's' && !mod) {
      if (!$('pin-modal').classList.contains('open')) {
        e.preventDefault();
        const next = document.body.dataset.sidebar === 'collapsed' ? 'expanded' : 'collapsed';
        document.body.dataset.sidebar = next;
        try { localStorage.setItem(STORAGE_KEYS.sidebar, next); } catch {}
      }
      return;
    }
    if (e.key.toLowerCase() === 'g') { e.preventDefault(); showGallery(); return; }
    if (e.key.toLowerCase() === 'd') { e.preventDefault(); $('theme-btn').click(); return; }
    if (e.key === '1') { e.preventDefault(); applyViewMode('masonry'); return; }
    if (e.key === '2') { e.preventDefault(); applyViewMode('grid'); return; }
    if (e.key === '3') { e.preventDefault(); applyViewMode('list'); return; }
    if (e.key === '0') {
      e.preventDefault();
      activeFilter = 'all'; activeSort = 'newest';
      updateFilterChips(); updateSortLabel();
      applyFilterAndSort();
      window.showToast('Filters cleared', 'info', 1500);
      return;
    }
    const modal = $('pin-modal');
    if (modal.classList.contains('open')) {
      if (e.key === 'ArrowLeft') pmNav(-1);
      if (e.key === 'ArrowRight') pmNav(1);
    } else if ($('pin-detail').classList.contains('open')) {
      const pins = filteredPins;
      if (e.key === 'ArrowLeft') { pmIndex = Math.max(0, pmIndex - 1); renderPinDetail(pins, pmIndex); }
      if (e.key === 'ArrowRight') { pmIndex = Math.min(pins.length - 1, pmIndex + 1); renderPinDetail(pins, pmIndex); }
    }
  });
}

function openShortcuts() {
  $('shortcuts-overlay').classList.add('open');
  $('shortcuts-overlay').setAttribute('aria-hidden', 'false');
}
function closeShortcuts() {
  $('shortcuts-overlay').classList.remove('open');
  $('shortcuts-overlay').setAttribute('aria-hidden', 'true');
}

// ====== Wire Events ======
function wireEvents() {
  const searchForm = $('search-form');
  if (searchForm) {
    searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      startScrape();
    });
  }
  $('settings-btn').addEventListener('click', () => {
    syncDrawerFromSettings();
    openDrawer(true);
  });
  $('close-settings').addEventListener('click', () => openDrawer(false));
  $('overlay').addEventListener('click', () => openDrawer(false));
  $('reset-settings').addEventListener('click', () => {
    settings = { ...DEFAULTS, mode: 'search' };
    saveSettings();
    syncDrawerFromSettings();
    window.showToast('Settings reset to defaults', 'success', 2200);
  });
  const drawer = $('settings-drawer');
  if (drawer) {
    drawer.addEventListener('input', readDrawerToSettings);
    drawer.addEventListener('change', readDrawerToSettings);
  }

  $$('.nav-btn-main').forEach(b => {
    b.addEventListener('click', () => {
      const nav = b.dataset.nav;
      if (nav === 'search') showSearch();
      else if (nav === 'gallery') showGallery();
      else if (nav === 'schedules') { setActiveNav('schedules'); openSchedulesPanel(); }
      else if (nav === 'collections') { setActiveNav('collections'); openCollectionsPanel(); }
      else if (nav === 'history') { setActiveNav('history'); openHistoryPanel(); }
      if (window.innerWidth <= 860) closeMobileSidebar();
    });
  });
  $('clear-recent')?.addEventListener('click', (e) => {
    e.stopPropagation();
    try { localStorage.removeItem(STORAGE_KEYS.recent); } catch {}
    renderSidebarRecent();
    renderRecent();
  });
  $('shortcuts-open')?.addEventListener('click', openShortcuts);
  $('focus-toggle')?.addEventListener('click', toggleFocusMode);
  $('shortcuts-btn')?.addEventListener('click', openShortcuts);
  $('shortcuts-close')?.addEventListener('click', closeShortcuts);
  $('shortcuts-overlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'shortcuts-overlay') closeShortcuts();
  });

  $$('[data-close-panel]').forEach(b => b.addEventListener('click', closeAllPanels));

  $$('.filter-chip').forEach(ch => {
    ch.addEventListener('click', () => {
      const f = ch.dataset.filter;
      activeFilter = (activeFilter === f && f !== 'all') ? 'all' : f;
      updateFilterChips();
      applyFilterAndSort();
      pushURLState();
    });
  });

  $('sort-trigger')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = $('sort-menu');
    if (menu.classList.contains('hidden')) openSortMenu(); else closeSortMenu();
  });
  $$('#sort-menu button').forEach(b => {
    b.addEventListener('click', () => {
      activeSort = b.dataset.sort;
      updateSortLabel();
      applyFilterAndSort();
      pushURLState();
      closeSortMenu();
    });
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#sort-dropdown')) closeSortMenu();
    if (!e.target.closest('#context-menu')) closeContextMenu();
  });

  $$('#view-modes button').forEach(b => {
    b.addEventListener('click', () => {
      applyViewMode(b.dataset.mode);
      pushURLState();
    });
  });

  $('bulk-toggle')?.addEventListener('click', () => setSelectionMode(!selectionMode));

  $('cancel-btn').addEventListener('click', async () => {
    if (currentJob) {
      const btn = $('cancel-btn');
      btn.disabled = true;
      btn.innerHTML = '<i class="bi bi-hourglass-split"></i> …';
      try { await fetch(`/api/jobs/${currentJob}/cancel`, { method: 'POST' }); } catch {}
    }
  });

  $('close-pin-modal').addEventListener('click', closePinModal);
  $('pm-prev').addEventListener('click', () => pmNav(-1));
  $('pm-next').addEventListener('click', () => pmNav(1));
  $('pin-modal').addEventListener('click', (e) => {
    if (e.target.id === 'pin-modal') closePinModal();
  });
  const pmImg = $('pm-img');
  if (pmImg) {
    pmImg.addEventListener('click', (e) => { e.stopPropagation(); pmImg.classList.toggle('zoomed'); });
  }

  $('detail-close')?.addEventListener('click', closePinDetail);

  $('sel-cancel').addEventListener('click', () => setSelectionMode(false));
  $('sel-download')?.addEventListener('click', bulkDownloadSelected);
  $('sel-collection')?.addEventListener('click', bulkSaveToCollection);
  $('sel-delete').addEventListener('click', async () => {
    if (!selectedFiles.size) return;
    const deleteBtn = $('sel-delete');
    deleteBtn.disabled = true;
    try {
      const toDelete = [...selectedFiles];
      const res = await fetch('/api/images/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names: toDelete }),
      });
      const { deleted } = await res.json();
      const selectedCards = document.querySelectorAll('.pin-card.selected');
      selectedCards.forEach(c => c.classList.add('deleting'));
      await new Promise(r => setTimeout(r, 320));
      selectedCards.forEach(c => c.remove());
      const deletedSet = new Set(toDelete);
      lastPins = lastPins.filter(p => !p.local_file || !deletedSet.has(p.local_file));
      allPins = allPins.filter(p => !p.local_file || !deletedSet.has(p.local_file));
      window._lastPins = lastPins;
      addHistory({ type: 'delete', count: deleted });

      setSelectionMode(false);
      await updateGalleryBadge();
      window.showToast(`${deleted} image${deleted === 1 ? '' : 's'} deleted`, 'success', 6000, {
        label: 'Undo',
        onClick: () => {
          window.showToast('File already deleted from disk', 'info', 2400);
        },
      });
      $('stats-card').innerHTML = `
        <div class="stats-header">
          <span class="stats-title"><i class="bi bi-trash3"></i> ${deleted} images deleted</span>
          ${currentView === 'gallery' ? `<span class="stats-query">${lastPins.length} pins remaining</span>` : ''}
        </div>`;
      $('stats-card').classList.remove('hidden');
      $('export-bar').classList.add('hidden');
      if (!document.querySelector('.pin-card')) $('empty').classList.remove('hidden');
    } finally {
      deleteBtn.disabled = false;
    }
  });

  $('sch-add')?.addEventListener('click', addSchedule);

  $('col-add')?.addEventListener('click', () => {
    const name = $('col-name').value.trim();
    if (!name) { window.showError('Enter a name'); return; }
    const cols = getCollections();
    cols.push({ id: 'c' + Math.random().toString(36).slice(2, 10), name, pins: [], created: Date.now() });
    saveCollections(cols);
    $('col-name').value = '';
    window.showToast(`Collection "${name}" created`, 'success');
  });

  $('history-clear')?.addEventListener('click', clearHistory);

  document.addEventListener('pointerdown', (e) => {
    const card = e.target.closest('.pin-card');
    if (!card || selectionMode) return;
    if (!card._pin?.local_file) return;
    card.classList.add('holding');
    pressTimer = setTimeout(() => {
      pressTimer = null;
      suppressClickUntil = Date.now() + 450;
      card.classList.remove('holding');
      setSelectionMode(true);
      toggleSelect(card);
    }, 400);
  });
  ['pointerup', 'pointerleave', 'pointercancel', 'scroll'].forEach(ev =>
    document.addEventListener(ev, () => {
      if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
      document.querySelectorAll('.pin-card.holding').forEach(c => c.classList.remove('holding'));
    }, true)
  );
  document.addEventListener('click', (e) => {
    if (Date.now() < suppressClickUntil) {
      e.stopPropagation();
      e.preventDefault();
      return;
    }
    if (!selectionMode) return;
    const card = e.target.closest('.pin-card');
    if (!card) return;
    e.stopPropagation();
    e.preventDefault();
    toggleSelect(card);
  }, true);

  const _io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadMore();
  }, { rootMargin: '600px' });
  const _sentinel = document.getElementById('scroll-sentinel');
  if (_sentinel) _io.observe(_sentinel);

  const hero = $('hero');
  const grid = $('grid');
  if (hero && grid) {
    const observer = new MutationObserver(() => {
      const hasCards = grid.querySelector('.pin-card, .skeleton');
      hero.classList.toggle('hidden', !!hasCards);
    });
    observer.observe(grid, { childList: true });
  }

  window.addEventListener('resize', () => {
    if (window.innerWidth > 860 && document.body.dataset.sidebar === 'mobile-open') {
      document.body.dataset.sidebar = 'expanded';
    }
  });
  window.addEventListener('orientationchange', () => {
    setTimeout(() => { if (window.innerWidth > 860 && document.body.dataset.sidebar === 'mobile-open') document.body.dataset.sidebar = 'expanded'; }, 200);
  });

  initKeyboard();
  readURLState();
}

function init() {
  syncDrawerFromSettings();
  updateGalleryBadge();
  refreshSchedulesBadge();
  checkHealth();
  setInterval(checkHealth, 30000);
  initTheme();
  initDensity();
  initViewMode();
  initSidebar();
  initCommandPalette();
  initSuggestions();
  renderRecent();
  renderSidebarRecent();
  renderHistory();
  renderCollections();
  updateNavBadges();
  updateFilterChips();
  updateSortLabel();
  wireEvents();
  const sb = $('search-input');
  if (sb) {
    sb.addEventListener('input', () => {
      const box = sb.closest('.search-box');
      if (box) box.classList.toggle('has-value', sb.value.length > 0);
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}