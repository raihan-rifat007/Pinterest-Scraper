'use strict';

const DEFAULTS = {
  mode: 'search',
  download: false, details: false, show_insights: false,
  limit: 25, min_width: 0, min_height: 0,
  workers: 4, delay: 1.0, jitter: 0.5, batch_size: 10,
};

const $ = (id) => document.getElementById(id);
let settings = loadSettings();
let currentJob = null;
let lastPins = [];

function loadSettings() {
  try {
    const raw = localStorage.getItem('ps_settings');
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { return { ...DEFAULTS }; }
}
function saveSettings() { localStorage.setItem('ps_settings', JSON.stringify(settings)); }

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

async function startScrape() {
  const query = $('search-input').value.trim();
  if (!query) { showError('Please enter a search term.'); return; }
  readDrawerToSettings();
  hideError();
  if (currentView !== 'search') {
    currentView = 'search';
    $('tab-search').classList.add('active');
    $('tab-gallery').classList.remove('active');
  }
  $('empty').classList.add('hidden');
  $('stats-card').classList.add('hidden');
  showSkeletons();
  addRecent(query);
  initProgress('Collecting pins');

  const body = { mode: 'search', query, ...settings };
  delete body.show_insights;
  delete body.dedup;
  const res = await fetch('/api/scrape', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { showError(`Scraping failed: ${res.status}`); return; }
  const { job_id } = await res.json();
  currentJob = job_id;
  listenEvents(job_id);
}

function listenEvents(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (e) => { const ev = JSON.parse(e.data); handleEvent(ev, es); };
  es.onerror = () => es.close();
}

function handleEvent(ev, es) {
  if (ev.event === 'query_start') {
    els_progress(ev);
  } else if (ev.event === 'queries_done') {
    els_queries_done(ev);
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
  } else if (ev.event === 'nothing_new') {
    appendMeta('Pins are already up to date.');
  } else if (ev.event === 'done') {
    es.close();
    finishJob(ev);
  }
}

async function finishJob(ev) {
  const cancelBtn = $('cancel-btn');
  if (cancelBtn) { cancelBtn.disabled = false; cancelBtn.textContent = 'Cancel'; }
  if (ev.status === 'cancelled') {
    showError('Cancelled');
    $('progress-card').classList.add('hidden');
    currentJob = null;
    return;
  }
  if (ev.status === 'error') {
    showError(`Scraping failed: ${ev.error}`);
    $('progress-card').classList.add('hidden');
    currentJob = null;
    return;
  }
  const res = await fetch(`/api/jobs/${currentJob}/result`);
  const data = await res.json();
  lastPins = data.pins || [];
  window._lastPins = lastPins;
  renderStats(ev);
  const hasImages = lastPins.some(p => p.local_file);
  if (!lastPins.length) {
    showError(hasImages || ev.stats?.downloaded > 0
      ? 'Pins are already up to date.'
      : 'No results found for this query.');
  } else {
    hideError();
  }
  resetFeed(lastPins);
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
  $('progress-card').classList.add('hidden');
  currentJob = null;
}

const phaseOrder = ['collect', 'details', 'download'];
const phaseState = {};
let currentPhase = null;

function initProgress(title) {
  const card = $('progress-card');
  card.classList.remove('hidden');
  $('progress-title').textContent = title;
  $('progress-bar').classList.add('indeterminate');
  $('progress-bar').style.width = '0%';
  $('progress-pct').textContent = '0%';
  $('progress-meta').textContent = '';
  const cancelBtn = $('cancel-btn');
  if (cancelBtn) { cancelBtn.disabled = false; cancelBtn.textContent = 'Cancel'; }
  phaseOrder.forEach(p => { phaseState[p] = { count: 0, total: 0, done: false }; });
  currentPhase = 'collect';
  updatePhaseUI();
}

function updatePhaseUI() {
  document.querySelectorAll('.phase-chip').forEach(ch => {
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
function appendMeta(text) {
  $('progress-meta').textContent = `${$('progress-meta').textContent} ${text}`.trim();
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
      <span class="stats-title">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
        Results Summary
      </span>
      ${currentQuery ? `<span class="stats-query">"${escapeHtml(currentQuery)}"</span>` : ''}
    </div>
    <div class="stats-grid">
      <div class="stat-card stat-total">
        <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg></span>
        <div class="stat-data"><span class="stat-num">${totalPins}</span><span class="stat-lbl">Total Pins</span></div>
      </div>
      <div class="stat-card stat-downloaded">
        <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>
        <div class="stat-data"><span class="stat-num">${downloaded}</span><span class="stat-lbl">Downloaded</span></div>
      </div>
      <div class="stat-card stat-existing">
        <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg></span>
        <div class="stat-data"><span class="stat-num">${onDisk}</span><span class="stat-lbl">Saved on disk</span></div>
      </div>
  `;
  if (failed > 0) html += `
      <div class="stat-card stat-failed">
        <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></span>
        <div class="stat-data"><span class="stat-num">${failed}</span><span class="stat-lbl">Failed</span></div>
      </div>`;
  if (s.skipped_small) html += `
      <div class="stat-card">
        <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/></svg></span>
        <div class="stat-data"><span class="stat-num">${s.skipped_small}</span><span class="stat-lbl">Too small</span></div>
      </div>`;
  html += '</div>';
  $('stats-card').innerHTML = html;
  $('stats-card').classList.remove('hidden');
}

function fmtNum(n) {
  if (n == null) return '';
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
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
    if (selectionMode) card.classList.add('selectable');
    card.style.animationDelay = `${Math.min(i * 0.035, 0.6)}s`;

    card.innerHTML = `
      ${src
        ? `<img class="pin-img" loading="lazy" src="${src}"
              alt="${escapeHtml(pin.title || pin.pin_id)}"
              onerror="this.onerror=null;this.src='${escapeHtml(pin.image_url || '')}'"`
          + ` style="aspect-ratio:${pin.width && pin.height ? pin.width + '/' + pin.height : 'auto'}">`
        : `<div class="pin-no-img"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg></div>`}
      ${isVideo ? `<div class="video-badge">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="white">
          <polygon points="5 3 19 12 5 21 5 3"/>
        </svg>
      </div>` : ''}
      <div class="pin-overlay">
        <button class="pin-save">Save</button>
        <div class="pin-meta">
          ${pin.title ? `<div>${escapeHtml(pin.title.slice(0, 60))}</div>` : ''}
          ${(pin.saves || pin.comments) ? `<div>${pin.saves ? `${fmtNum(pin.saves)} saves` : ''}${pin.saves && pin.comments ? ' · ' : ''}${pin.comments ? `${fmtNum(pin.comments)} comments` : ''}</div>` : ''}
          ${pin.width ? `<div>${pin.width} × ${pin.height}</div>` : ''}
          <a href="${pin.pin_url || '#'}" target="_blank" rel="noopener">Pinterest</a>
          ${src ? `<a href="${src}" target="_blank" rel="noopener">Original</a>` : ''}
        </div>
      </div>`;

    const imgEl = card.querySelector('.pin-img');
    if (imgEl) {
      if (imgEl.complete && imgEl.naturalWidth) imgEl.classList.add('img-loaded');
      else imgEl.addEventListener('load', () => imgEl.classList.add('img-loaded'), { once: true });
    }

    card.addEventListener('click', () => {
      if (selectionMode) return;
      openPinModal(pin, src);
    });
    card.querySelector('.pin-save')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const target = isVideo ? (pin.video_url || src) : src;
      if (target) window.open(target, '_blank');
    });
    grid.appendChild(card);
  });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function showError(msg) {
  const el = $('error-card');
  el.textContent = msg;
  el.classList.remove('hidden');
}
function hideError() { $('error-card').classList.add('hidden'); }

let currentView = 'search';

async function updateGalleryBadge() {
  try {
    const res = await fetch('/api/gallery');
    if (res.ok) {
      const data = await res.json();
      const badge = $('gallery-badge');
      if (badge) badge.textContent = data.total ?? 0;
    }
  } catch {}
}

async function showGallery() {
  currentView = 'gallery';
  $('tab-gallery').classList.add('active');
  $('tab-search').classList.remove('active');
  hideError();
  $('progress-card').classList.add('hidden');
  $('stats-card').classList.add('hidden');
  $('chart-card').classList.add('hidden');
  const recentRow = $('recent-row');
  if (recentRow) recentRow.classList.add('hidden');
  showSkeletons(12);

  try {
    const res = await fetch('/api/gallery');
    const data = await res.json();
    const pins = data.pins || [];
    $('gallery-badge').textContent = data.total ?? pins.length;

    if (!pins.length) {
      $('grid').innerHTML = '';
      $('empty-icon').innerHTML = '<svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
      $('empty-title').textContent = 'No downloaded images yet';
      $('empty-text').textContent = "Search and scrape pins with 'Download images' enabled to build your gallery.";
      $('empty').classList.remove('hidden');
      $('export-bar').classList.add('hidden');
    } else {
      $('empty').classList.add('hidden');
      resetFeed(pins);
      $('exp-zip').href = '/api/gallery/export/zip';
      $('exp-zip').classList.remove('hidden');
      $('exp-xlsx').classList.add('hidden');
      $('export-bar').classList.remove('hidden');
      $('stats-card').innerHTML = `
        <div class="stats-header">
          <span class="stats-title">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            Gallery
          </span>
          <span class="stats-query">${pins.length} pins</span>
        </div>
        <div class="stats-grid">
          <div class="stat-card stat-downloaded">
            <span class="stat-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg></span>
            <div class="stat-data"><span class="stat-num">${pins.length}</span><span class="stat-lbl">Saved on disk</span></div>
          </div>
        </div>`;
      $('stats-card').classList.remove('hidden');
    }
  } catch { showError('Failed to load gallery'); }
}

function showSearch() {
  currentView = 'search';
  $('tab-search').classList.add('active');
  $('tab-gallery').classList.remove('active');
  hideError();
  $('empty-icon').innerHTML = '<svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
  $('empty-title').textContent = 'Find your inspiration';
  $('empty-text').textContent = 'Search for anything and scrape high-quality images with full metadata.';

  if (lastPins && lastPins.length > 0) {
    $('empty').classList.add('hidden');
    resetFeed(lastPins);
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
  }
  renderRecent();
}

$('search-form').addEventListener('submit', (e) => { e.preventDefault(); startScrape(); });
$('settings-btn').addEventListener('click', () => { syncDrawerFromSettings(); openDrawer(true); });
$('close-settings').addEventListener('click', () => openDrawer(false));
$('overlay').addEventListener('click', () => openDrawer(false));
$('reset-settings').addEventListener('click', () => {
  settings = { ...DEFAULTS, mode: 'search' };
  saveSettings(); syncDrawerFromSettings();
});

const drawer = $('settings-drawer');
if (drawer) {
  drawer.addEventListener('input', readDrawerToSettings);
  drawer.addEventListener('change', readDrawerToSettings);
}

$('tab-search').addEventListener('click', () => { if (currentView !== 'search') showSearch(); });
$('tab-gallery').addEventListener('click', () => { if (currentView !== 'gallery') showGallery(); });

$('cancel-btn').addEventListener('click', async () => {
  if (currentJob) {
    const btn = $('cancel-btn');
    btn.disabled = true;
    btn.textContent = '…';
    try { await fetch(`/api/jobs/${currentJob}/cancel`, { method: 'POST' }); } catch {}
  }
});

syncDrawerFromSettings();
updateGalleryBadge();
initLayout();
initTheme();
renderRecent();

const sugList = $('suggest-list');
const input = $('search-input');
let debounceTimer = null, sugItems = [], sugIndex = -1, sugAbort = null;

function hideSuggest() {
  sugList.classList.remove('show');
  sugList.classList.add('hidden');
  sugList.innerHTML = '';
  sugItems = []; sugIndex = -1;
}
function highlight(q, text) {
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return escapeHtml(text);
  return escapeHtml(text.slice(0, i)) + '<b>' + escapeHtml(text.slice(i, i + q.length)) + '</b>' +
         escapeHtml(text.slice(i + q.length));
}
function renderSuggest(q, items) {
  sugItems = items; sugIndex = -1;
  sugList.innerHTML = items.map(s => {
    if (s.type === 'user') {
      return `<li role="option" class="sug-user">
        <img class="sug-avatar" src="${s.image || ''}" alt="" loading="lazy"
             onerror="this.style.visibility='hidden'">
        <span class="sug-texts"><span class="sug-name">${highlight(q, s.text)}
          ${s.verified ? `<span class="sug-verified" title="Verified"><svg viewBox="0 0 24 24" width="12" height="12" fill="#0074E8"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg></span>` : ''}</span>
          ${s.sub ? `<span class="sug-sub">${escapeHtml(s.sub)}</span>` : ''}</span>
      </li>`;
    }
    return `<li role="option"><span class="sug-ico"><svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M10 2a8 8 0 105.3 14l4.4 4.4 1.4-1.4-4.4-4.4A8 8 0 0010 2z"/></svg></span><span>${highlight(q, s.text)}</span></li>`;
  }).join('');
  sugList.classList.toggle('show', items.length > 0);
  sugList.classList.toggle('hidden', items.length === 0);
  [...sugList.children].forEach((li, i) =>
    li.addEventListener('mousedown', (e) => {
      e.preventDefault();
      input.value = sugItems[i].text;
      hideSuggest();
      startScrape();
    }));
}
input.addEventListener('input', () => {
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
    e.preventDefault();
    if (sugIndex >= 0 && sugItems[sugIndex]) input.value = sugItems[sugIndex].text;
    hideSuggest(); startScrape();
  } else if (e.key === 'Escape') { hideSuggest(); }
});
input.addEventListener('blur', () => setTimeout(hideSuggest, 150));
document.addEventListener('click', (e) => { if (!e.target.closest('.search-wrap')) hideSuggest(); });

let pmIndex = -1;

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
      pmImg.classList.remove('hidden');
      pmImg.classList.remove('pm-img-fade');
      void pmImg.offsetWidth;
      pmImg.src = src;
      pmImg.classList.add('pm-img-fade');
      pmImg.alt = pin.title || pin.pin_id || '';
      pmImg.onerror = () => {
        pmImg.onerror = null;
        if (pin.image_url && pmImg.src !== pin.image_url) pmImg.src = pin.image_url;
      };
    }
  }

  const creatorName = pin.creator_name || pin.creator_username || 'Pinterest Creator';
  const creatorUser = pin.creator_username ? `@${pin.creator_username}` : '';
  const avatarEl = $('pm-creator-avatar');
  if (avatarEl) avatarEl.textContent = (creatorName.trim()[0] || 'P').toUpperCase();
  const nameEl = $('pm-creator-name');
  if (nameEl) nameEl.textContent = creatorName;
  const userEl = $('pm-creator-user');
  if (userEl) userEl.textContent = creatorUser;
  const linkEl = $('pm-creator-link');
  if (linkEl) {
    if (pin.creator_username) {
      linkEl.href = `https://www.pinterest.com/${pin.creator_username}/`;
      linkEl.classList.remove('hidden');
    } else { linkEl.classList.add('hidden'); }
  }

  const titleEl = $('pm-title');
  if (titleEl) titleEl.textContent = pin.title || `Pin ${pin.pin_id}`;
  const descEl = $('pm-desc');
  if (descEl) {
    descEl.textContent = pin.description || '';
    descEl.classList.toggle('hidden', !pin.description);
  }

  const savesVal = $('pm-val-saves');
  if (savesVal) savesVal.textContent = fmtNum(pin.saves ?? 0);
  const commVal = $('pm-val-comments');
  if (commVal) commVal.textContent = fmtNum(pin.comments ?? 0);
  const sizeVal = $('pm-val-size');
  if (sizeVal) sizeVal.textContent = (pin.width && pin.height) ? `${pin.width} × ${pin.height}` : '—';

  const boardRow = $('pm-board-row');
  const boardLink = $('pm-board-name');
  if (boardRow && boardLink) {
    if (pin.board_name) {
      boardRow.classList.remove('hidden');
      boardLink.textContent = pin.board_name;
      boardLink.href = pin.board_url || '#';
    } else { boardRow.classList.add('hidden'); }
  }

  const colorsWrap = $('pm-colors');
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
        };
        colorsWrap.appendChild(c);
      });
      colorsWrap.parentElement.classList.remove('hidden');
    } else { colorsWrap.parentElement.classList.add('hidden'); }
  }

  const dlBtn = $('pm-download');
  if (dlBtn) {
    dlBtn.href = isVideo ? (pin.video_url || src) : src;
    dlBtn.download = isVideo ? `pin_${pin.pin_id}.mp4` : `pin_${pin.pin_id}.jpg`;
  }
  const pinLink = $('pm-pin-link');
  if (pinLink) pinLink.href = pin.pin_url || `https://www.pinterest.com/pin/${pin.pin_id}/`;

  const copyBtn = $('pm-copy-link');
  if (copyBtn) {
    copyBtn.onclick = async () => {
      const urlToCopy = pin.pin_url || pin.image_url || window.location.href;
      try {
        await navigator.clipboard.writeText(urlToCopy);
        const origHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="#00a300" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        setTimeout(() => { copyBtn.innerHTML = origHtml; }, 1400);
      } catch {}
    };
  }

  const visualBtn = $('pm-visual');
  if (visualBtn) visualBtn.onclick = () => runVisualSearch(pin.pin_id);
}

function openPinModal(pin, src) {
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
  if (pmImg) pmImg.classList.remove('hidden');
  document.body.style.overflow = '';
  const m = $('pin-modal');
  m.classList.add('closing');
  m.classList.remove('open');
  setTimeout(() => {
    m.classList.remove('closing');
    m.setAttribute('aria-hidden', 'true');
  }, 280);
}

function pmNav(dir) { showPinAt(pmIndex + dir); }

$('close-pin-modal').addEventListener('click', closePinModal);
$('pm-prev').addEventListener('click', () => pmNav(-1));
$('pm-next').addEventListener('click', () => pmNav(1));
$('pin-modal').addEventListener('click', (e) => { if (e.target.id === 'pin-modal') closePinModal(); });

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if ($('settings-drawer').classList.contains('open')) { openDrawer(false); return; }
    if ($('pin-modal').classList.contains('open')) { closePinModal(); return; }
    if (selectionMode) { setSelectionMode(false); return; }
  }
  if ($('pin-modal').classList.contains('open')) {
    if (e.key === 'ArrowLeft') pmNav(-1);
    if (e.key === 'ArrowRight') pmNav(1);
  }
});

async function runVisualSearch(pinId) {
  closePinModal();
  showSkeletons(10);
  $('progress-card').classList.remove('hidden');
  $('progress-title').textContent = 'Finding similar pins…';
  $('progress-bar').classList.add('indeterminate');
  try {
    const res = await fetch(`/api/visual-search?pin_id=${pinId}&limit=30`);
    const data = await res.json();
    $('progress-card').classList.add('hidden');
    if (!res.ok) { showError(data.detail || 'Visual search failed'); return; }
    lastPins = data.pins || [];
    window._lastPins = lastPins;
    $('stats-card').innerHTML = `
      <div class="stats-header">
        <span class="stats-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px"><path d="M12 2l2.4 6.6L21 11l-5.6 4.4L17 22l-5-4-5 4 1.6-6.6L3 11l6.6-2.4z"/></svg>
          Visually similar pins
        </span>
        <span class="stats-query">${lastPins.length} pins</span>
      </div>`;
    $('stats-card').classList.remove('hidden');
    $('export-bar').classList.add('hidden');
    $('chart-card').classList.add('hidden');
    resetFeed(lastPins);
  } catch {
    $('progress-card').classList.add('hidden');
    showError('Visual search failed');
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
      indexAxis: 'y', plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: dark ? '#A8A8A8' : '#5f5f5f' }, grid: { color: dark ? '#333' : '#eee' } },
        y: { ticks: { color: dark ? '#A8A8A8' : '#5f5f5f' }, grid: { display: false } },
      },
    },
  });
}

function applyTheme(t) {
  document.body.dataset.theme = t;
  localStorage.setItem('theme', t);
  const icon = document.getElementById('theme-icon');
  if (icon) {
    icon.innerHTML = t === 'dark'
      ? `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
      : `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>`;
  }
  if (window._chart) { window._chart.destroy(); window._chart = null; renderChart(); }
}
function initTheme() {
  const saved = localStorage.getItem('theme');
  const sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  applyTheme(saved || sys);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.onclick = () => applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
}

function applyLayout(layout) {
  document.body.dataset.layout = layout;
  localStorage.setItem('ps_layout', layout);
  const icon = document.getElementById('layout-icon');
  const isWide = layout === 'wide';
  if (icon) {
    icon.innerHTML = isWide
      ? `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7"/></svg>`
      : `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>`;
  }
  const btn = document.getElementById('layout-btn');
  if (btn) btn.title = isWide ? 'Standard width' : 'Full width';
}
function initLayout() {
  const saved = localStorage.getItem('ps_layout') || 'contained';
  applyLayout(saved);
  const btn = document.getElementById('layout-btn');
  if (btn) btn.onclick = () => applyLayout(document.body.dataset.layout === 'wide' ? 'contained' : 'wide');
}

function getRecent() { try { return JSON.parse(localStorage.getItem('recentSearches') || '[]'); } catch { return []; } }
function addRecent(q) {
  if (!q) return;
  const list = getRecent().filter(x => x !== q);
  list.unshift(q);
  localStorage.setItem('recentSearches', JSON.stringify(list.slice(0, 8)));
  renderRecent();
}
function renderRecent() {
  const row = document.getElementById('recent-row');
  if (!row) return;
  const list = getRecent();
  const starters = ['taylor swift', 'interior design', 'minimal wallpaper', 'dark aesthetic'];
  const items = list.length ? list : (lastPins && lastPins.length ? [] : starters);
  if (!items.length) { row.classList.add('hidden'); return; }
  row.classList.remove('hidden');
  const label = list.length ? 'Recent:' : 'Try:';
  row.innerHTML = `<span class="row-label">${label}</span>` +
    items.map(q => `<button class="chip">${escapeHtml(q)}</button>`).join('') +
    (list.length ? `<button id="clear-recents" class="chip clear-chip"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:3px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>Clear</button>` : '');
  row.querySelectorAll('.chip:not(.clear-chip)').forEach((b, idx) => {
    b.onclick = () => {
      document.getElementById('search-input').value = items[idx];
      startScrape();
    };
  });
  const clr = row.querySelector('#clear-recents');
  if (clr) clr.onclick = () => { localStorage.removeItem('recentSearches'); renderRecent(); };
}

function showSkeletons(n = 12) {
  const grid = document.getElementById('grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const d = document.createElement('div');
    d.className = 'skeleton';
    d.style.height = (140 + Math.random() * 180) + 'px';
    grid.appendChild(d);
  }
}

let selectionMode = false;
const selectedFiles = new Set();
let pressTimer = null;

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
  bar.classList.toggle('hidden', !selectionMode);
  document.getElementById('sel-count').textContent = `${selectedFiles.size} selected`;
}
function toggleSelect(card) {
  const pin = card._pin;
  if (!pin || !pin.local_file) return;
  if (selectedFiles.has(pin.local_file)) {
    selectedFiles.delete(pin.local_file);
    card.classList.remove('selected');
  } else {
    selectedFiles.add(pin.local_file);
    card.classList.add('selected');
  }
  updateSelBar();
}

let suppressClickUntil = 0;

document.addEventListener('pointerdown', (e) => {
  const card = e.target.closest('.pin-card');
  if (!card || selectionMode) return;
  if (!card._pin?.local_file && currentView !== 'gallery') return;
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
  }, true));

document.addEventListener('click', (e) => {
  if (Date.now() < suppressClickUntil) { e.stopPropagation(); e.preventDefault(); return; }
  if (!selectionMode) return;
  const card = e.target.closest('.pin-card');
  if (!card) return;
  e.stopPropagation(); e.preventDefault();
  toggleSelect(card);
}, true);

$('sel-cancel').addEventListener('click', () => setSelectionMode(false));
$('sel-delete').addEventListener('click', async () => {
  if (!selectedFiles.size) return;
  const deleteBtn = $('sel-delete');
  deleteBtn.disabled = true;
  try {
    const toDelete = [...selectedFiles];
    const res = await fetch('/api/images/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
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
    setSelectionMode(false);
    await updateGalleryBadge();
    $('stats-card').innerHTML = `
      <div class="stats-header">
        <span class="stats-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          ${deleted} images deleted
        </span>
        ${currentView === 'gallery' ? `<span class="stats-query">${lastPins.length} pins remaining</span>` : ''}
      </div>`;
    $('stats-card').classList.remove('hidden');
    $('export-bar').classList.add('hidden');
    if (!document.querySelector('.pin-card')) $('empty').classList.remove('hidden');
  } finally { deleteBtn.disabled = false; }
});

const PAGE_SIZE = 25;
let allPins = [];
let renderedCount = 0;
let loadingMore = false;

function resetFeed(pins) {
  allPins = pins || [];
  lastPins = allPins;
  window._lastPins = allPins;
  renderedCount = 0;
  renderGrid(allPins.slice(0, PAGE_SIZE));
  renderedCount = Math.min(PAGE_SIZE, allPins.length);
}

function loadMore() {
  if (loadingMore || renderedCount >= allPins.length) return;
  loadingMore = true;
  renderGrid(allPins, true);
  renderedCount = allPins.length;
  loadingMore = false;
}

const _io = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting) loadMore();
}, { rootMargin: '600px' });
const _sentinel = document.getElementById('scroll-sentinel');
if (_sentinel) _io.observe(_sentinel);

function els_progress(ev) {
  const txt = `Query ${ev.index} of ${ev.total}: ${ev.query}`;
  const el = $('progress-title') || $('progress-meta');
  if (el) el.textContent = txt;
}
function els_queries_done(ev) {
  const txt = `All queries done — ${ev.total} pins`;
  const el = $('progress-title') || $('progress-meta');
  if (el) el.textContent = txt;
}
