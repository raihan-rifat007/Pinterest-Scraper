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
let renderedCount = 0;
let loadingMore = false;
const PAGE_SIZE = 25;

let selectionMode = false;
const selectedFiles = new Set();
let pressTimer = null;
let suppressClickUntil = 0;
let pmIndex = -1;

const phaseOrder = ['collect', 'details', 'download'];
const phaseState = {};
let currentPhase = null;

function loadSettings() {
  try {
    const raw = localStorage.getItem('ps_settings');
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { return { ...DEFAULTS }; }
}

function saveSettings() {
  try { localStorage.setItem('ps_settings', JSON.stringify(settings)); } catch {}
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

window.showToast = function (msg, type = 'info', duration = 3500) {
  const icons = {
    success: 'bi-check-circle-fill',
    error: 'bi-exclamation-octagon-fill',
    info: 'bi-info-circle-fill',
  };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<i class="bi ${icons[type] || icons.info}"></i><div class="toast-msg"></div>`;
  el.querySelector('.toast-msg').textContent = msg;
  $('toast-container').appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 320);
  }, duration);
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
    setActiveTab('search');
  }

  const hero = $('hero');
  if (hero) hero.classList.add('hidden');

  $('empty').classList.add('hidden');
  $('stats-card').classList.add('hidden');
  showSkeletons();
  addRecent(query);
  initProgress('Collecting pins');

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
    const labels = {
      collect: 'Collecting pins',
      details: 'Fetching details',
      download: 'Downloading images',
    };
    $('progress-title').textContent = labels[ev.phase] || ev.phase;
    $('progress-bar').classList.toggle('indeterminate', ev.phase === 'collect' && !ev.total);
    const prevIdx = phaseOrder.indexOf(ev.phase);
    for (let i = 0; i < prevIdx; i++) {
      if (phaseState[phaseOrder[i]]) phaseState[phaseOrder[i]].done = true;
    }
    currentPhase = ev.phase;
    if (!phaseState[ev.phase]) {
      phaseState[ev.phase] = { count: 0, total: ev.total || 0, done: false };
    }
    if (ev.total) phaseState[ev.phase].total = ev.total;
    updatePhaseUI();
  } else if (ev.event === 'progress') {
    if (ev.phase) currentPhase = ev.phase;
    if (currentPhase && phaseState[currentPhase]) {
      phaseState[currentPhase].count = ev.count;
      if (ev.total) phaseState[currentPhase].total = ev.total;
      if (phaseState[currentPhase].total > 0 &&
          phaseState[currentPhase].count >= phaseState[currentPhase].total) {
        phaseState[currentPhase].done = true;
      }
    }
    updatePhaseUI();
  } else if (ev.event === 'nothing_new') {
    const meta = $('progress-meta');
    if (meta) meta.textContent = `${meta.textContent} Pins are already up to date.`.trim();
  } else if (ev.event === 'done') {
    es.close();
    finishJob(ev);
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
    renderStats(ev);

    const hasImages = lastPins.some(p => p.local_file);
    if (!lastPins.length) {
      window.showError(hasImages || ev.stats?.downloaded > 0
        ? 'Pins are already up to date.'
        : 'No results found for this query.');
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

  const cancelBtn = $('cancel-btn');
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = '<i class="bi bi-x-circle"></i> Cancel';
  }

  phaseOrder.forEach(p => { phaseState[p] = { count: 0, total: 0, done: false }; });
  currentPhase = 'collect';
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
    html += `
      <div class="stat-card stat-failed">
        <span class="stat-icon"><i class="bi bi-exclamation-triangle"></i></span>
        <div class="stat-data"><span class="stat-num">${failed}</span><span class="stat-lbl">Failed</span></div>
      </div>`;
  }

  if (s.skipped_small) {
    html += `
      <div class="stat-card">
        <span class="stat-icon"><i class="bi bi-aspect-ratio"></i></span>
        <div class="stat-data"><span class="stat-num">${s.skipped_small}</span><span class="stat-lbl">Too small</span></div>
      </div>`;
  }

  html += '</div>';
  $('stats-card').innerHTML = html;
  $('stats-card').classList.remove('hidden');
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
    card.style.animationDelay = `${Math.min(i * 0.03, 0.6)}s`;

    const imgBlock = src
      ? `<img class="pin-img" loading="lazy" src="${src}"
            alt="${escapeHtml(pin.title || pin.pin_id)}"
            onerror="this.onerror=null;this.src='${escapeHtml(pin.image_url || '')}'"
            style="aspect-ratio:${pin.width && pin.height ? pin.width + '/' + pin.height : 'auto'}">`
      : `<div class="pin-no-img"><i class="bi bi-image"></i></div>`;

    const videoBadge = isVideo
      ? `<div class="video-badge"><i class="bi bi-play-fill"></i></div>`
      : '';

    const statsLine = (pin.saves || pin.comments)
      ? `<div class="stats">
          ${pin.saves ? `<span><i class="bi bi-bookmark-heart"></i> ${fmtNum(pin.saves)}</span>` : ''}
          ${pin.comments ? `<span><i class="bi bi-chat-dots"></i> ${fmtNum(pin.comments)}</span>` : ''}
        </div>`
      : '';

    const sizeLine = pin.width
      ? `<div class="stats"><span><i class="bi bi-aspect-ratio"></i> ${pin.width} × ${pin.height}</span></div>`
      : '';

    card.innerHTML = `
      ${imgBlock}
      ${videoBadge}
      <div class="pin-overlay">
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

    const imgEl = card.querySelector('.pin-img');
    if (imgEl) {
      if (imgEl.complete && imgEl.naturalWidth) imgEl.classList.add('img-loaded');
      else imgEl.addEventListener('load', () => imgEl.classList.add('img-loaded'), { once: true });
    }

    card.addEventListener('click', (e) => {
      if (selectionMode) return;
      if (e.target.closest('a')) return;
      openPinModal(pin, src);
    });

    const saveBtn = card.querySelector('.pin-save');
    if (saveBtn) {
      saveBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const target = isVideo ? (pin.video_url || src) : src;
        if (target) window.open(target, '_blank');
      });
    }

    grid.appendChild(card);
  });
}

function setActiveTab(view) {
  $$('.segmented .tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });
  moveIndicator();
}

function moveIndicator() {
  const active = document.querySelector('.segmented .tab.active');
  const indicator = $('tab-indicator');
  if (!active || !indicator) return;
  const parent = active.parentElement;
  const pRect = parent.getBoundingClientRect();
  const aRect = active.getBoundingClientRect();
  indicator.style.width = aRect.width + 'px';
  indicator.style.transform = `translateX(${aRect.left - pRect.left - 4}px)`;
}

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
  setActiveTab('gallery');
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

    if (!pins.length) {
      $('grid').innerHTML = '';
      $('empty-icon').innerHTML = '<i class="bi bi-images"></i>';
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
  setActiveTab('search');
  $('empty-icon').innerHTML = '<i class="bi bi-stars"></i>';
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
    const hero = $('hero');
    if (hero) hero.classList.remove('hidden');
  }
  renderRecent();
}

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
    if (pmVideo) {
      pmVideo.pause();
      pmVideo.src = '';
      pmVideo.classList.add('hidden');
    }
    if (pmImg) {
      pmImg.classList.remove('hidden', 'zoomed', 'pm-img-fade');
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

  const creatorName = pin.creator_name || pin.creator_username || '';
  const creatorUser = pin.creator_username ? `@${pin.creator_username}` : '';
  const avatarEl = $('pm-creator-avatar');
  if (avatarEl) {
    if (creatorName) avatarEl.textContent = (creatorName.trim()[0] || 'P').toUpperCase();
    else if (pin.creator_username) avatarEl.textContent = (pin.creator_username[0] || 'P').toUpperCase();
    else avatarEl.textContent = '?';
  }
  const nameEl = $('pm-creator-name');
  if (nameEl) nameEl.textContent = creatorName || 'Unknown creator';
  const userEl = $('pm-creator-user');
  if (userEl) userEl.textContent = creatorUser;
  const linkEl = $('pm-creator-link');
  if (linkEl) {
    if (pin.creator_username) {
      linkEl.href = `https://www.pinterest.com/${pin.creator_username}/`;
      linkEl.classList.remove('hidden');
    } else {
      linkEl.classList.add('hidden');
    }
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
    } else {
      boardRow.classList.add('hidden');
    }
  }

  const colorsWrap = $('pm-colors');
  const colorsParent = colorsWrap ? colorsWrap.closest('.pm-colors-wrap') : null;
  if (colorsWrap) {
    colorsWrap.innerHTML = '';
    const palette = [];
    if (pin.dominant_color) palette.push(pin.dominant_color);
    if (Array.isArray(pin.colors)) {
      pin.colors.forEach(c => { if (!palette.includes(c)) palette.push(c); });
    }
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
      if (colorsParent) colorsParent.classList.remove('hidden');
    } else {
      if (colorsParent) colorsParent.classList.add('hidden');
    }
  }

  const dlBtn = $('pm-download');
  if (dlBtn) {
    dlBtn.href = isVideo ? (pin.video_url || src) : src;
    dlBtn.download = isVideo ? `pin_${pin.pin_id}.mp4` : `pin_${pin.pin_id}.jpg`;
  }

  const pinLink = $('pm-pin-link');
  if (pinLink) {
    pinLink.href = pin.pin_url || `https://www.pinterest.com/pin/${pin.pin_id}/`;
  }

  const copyBtn = $('pm-copy-link');
  if (copyBtn) {
    copyBtn.onclick = async () => {
      const urlToCopy = pin.pin_url || pin.image_url || window.location.href;
      try {
        await navigator.clipboard.writeText(urlToCopy);
        const origHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="bi bi-check-lg" style="color:var(--green)"></i>';
        window.showToast('Link copied to clipboard', 'success', 2000);
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
  if (pmVideo) {
    pmVideo.pause();
    pmVideo.src = '';
    pmVideo.classList.add('hidden');
  }
  const pmImg = $('pm-img');
  if (pmImg) pmImg.classList.remove('hidden', 'zoomed');
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

    if (!res.ok) {
      window.showError(data.detail || 'Visual search failed');
      return;
    }

    lastPins = data.pins || [];
    window._lastPins = lastPins;

    $('stats-card').innerHTML = `
      <div class="stats-header">
        <span class="stats-title"><i class="bi bi-stars"></i> Visually similar pins</span>
        <span class="stats-query">${lastPins.length} pins</span>
      </div>`;
    $('stats-card').classList.remove('hidden');
    $('export-bar').classList.add('hidden');
    $('chart-card').classList.add('hidden');
    resetFeed(lastPins);
  } catch {
    $('progress-card').classList.add('hidden');
    window.showError('Visual search failed');
  }
}

function renderChart() {
  if (!settings.show_insights) {
    $('chart-card').classList.add('hidden');
    return;
  }
  const pins = (window._lastPins || lastPins || []).filter(p => p.saves != null);
  if (pins.length < 2) {
    $('chart-card').classList.add('hidden');
    return;
  }
  const top = [...pins].sort((a, b) => b.saves - a.saves).slice(0, 12);
  $('chart-card').classList.remove('hidden');
  const dark = document.body.dataset.theme === 'dark';
  const ctx = document.getElementById('chart-canvas');
  if (window._chart) window._chart.destroy();
  window._chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(p => (p.title || p.pin_id).slice(0, 22)),
      datasets: [{
        label: 'Saves',
        data: top.map(p => p.saves),
        backgroundColor: '#E60023',
        borderRadius: 7,
      }],
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

function applyTheme(t) {
  document.body.dataset.theme = t;
  try { localStorage.setItem('theme', t); } catch {}
  const icon = document.getElementById('theme-icon');
  if (icon) icon.className = t === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t === 'dark' ? '#08080A' : '#E60023');
  if (window._chart) {
    window._chart.destroy();
    window._chart = null;
    renderChart();
  }
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch {}
  const sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  applyTheme(saved || sys);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.onclick = () => {
    applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
  };
}

function getRecent() {
  try { return JSON.parse(localStorage.getItem('recentSearches') || '[]'); }
  catch { return []; }
}

function addRecent(q) {
  if (!q) return;
  const list = getRecent().filter(x => x !== q);
  list.unshift(q);
  try { localStorage.setItem('recentSearches', JSON.stringify(list.slice(0, 8))); } catch {}
  renderRecent();
}

function renderRecent() {
  const row = document.getElementById('recent-row');
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
      document.getElementById('search-input').value = b.dataset.q;
      startScrape();
    };
  });
}

function setSelectionMode(on) {
  selectionMode = on;
  document.querySelectorAll('.pin-card').forEach(c =>
    c.classList.toggle('selectable', on)
  );
  if (!on) {
    selectedFiles.clear();
    document.querySelectorAll('.pin-card.selected').forEach(c =>
      c.classList.remove('selected')
    );
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

function getCommands() {
  const cmds = [
    { id: 'focus-search', icon: 'bi-search', label: 'Search pins', sub: 'Focus search box',
      action: () => { closeCP(); $('search-input').focus(); } },
    { id: 'open-gallery', icon: 'bi-images', label: 'Open Gallery', sub: 'View downloaded images',
      action: () => { closeCP(); $('tab-gallery').click(); } },
    { id: 'open-search-tab', icon: 'bi-house', label: 'Back to Search', sub: 'Return to search view',
      action: () => { closeCP(); $('tab-search').click(); } },
    { id: 'toggle-theme', icon: 'bi-circle-half', label: 'Toggle theme', sub: 'Switch light / dark',
      action: () => { closeCP(); $('theme-btn').click(); } },
    { id: 'open-settings', icon: 'bi-gear-fill', label: 'Open Settings', sub: 'Configure options',
      action: () => { closeCP(); $('settings-btn').click(); } },
    { id: 'density-comfortable', icon: 'bi-grid-3x3', label: 'Density: Comfortable', sub: 'Large cards',
      action: () => { closeCP(); applyDensity('comfortable'); } },
    { id: 'density-default', icon: 'bi-grid', label: 'Density: Default', sub: 'Balanced layout',
      action: () => { closeCP(); applyDensity('default'); } },
    { id: 'density-compact', icon: 'bi-grid-3x3-gap', label: 'Density: Compact', sub: 'More cards',
      action: () => { closeCP(); applyDensity('compact'); } },
  ];
  const zip = $('exp-zip');
  if (zip && !zip.classList.contains('hidden')) {
    cmds.push({ id: 'download-zip', icon: 'bi-file-zip', label: 'Download ZIP', sub: 'Images as archive',
      action: () => { closeCP(); zip.click(); } });
  }
  const xlsx = $('exp-xlsx');
  if (xlsx && !xlsx.classList.contains('hidden')) {
    cmds.push({ id: 'export-xlsx', icon: 'bi-file-spreadsheet', label: 'Export XLSX', sub: 'Metadata spreadsheet',
      action: () => { closeCP(); xlsx.click(); } });
  }
  return cmds;
}

let cpIndex = -1;
let cpItems = [];

function renderCP(query = '') {
  const cpBody = $('cp-body');
  const q = query.trim().toLowerCase();
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
          action: () => {
            closeCP();
            $('search-input').value = r;
            startScrape();
          },
        })),
      });
    }
    sections.push({ title: 'Commands', items: commands });
  } else {
    const matched = commands.filter(c =>
      c.label.toLowerCase().includes(q) || c.sub.toLowerCase().includes(q)
    );
    if (matched.length) sections.push({ title: 'Commands', items: matched });
    sections.push({
      title: 'Search',
      items: [{
        icon: 'bi-search',
        label: `Search for "${query}"`,
        sub: 'Start scrape',
        action: () => {
          closeCP();
          $('search-input').value = query;
          startScrape();
        },
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

  cpBody.innerHTML = html ||
    `<div class="cp-empty">
      <i class="bi bi-search" style="font-size:1.6rem;display:block;margin-bottom:10px;opacity:.4"></i>
      No results
    </div>`;

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
  cpBody.querySelectorAll('.cp-item').forEach((el, n) =>
    el.classList.toggle('active', n === i)
  );
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

function applyDensity(density) {
  const btns = $$('#density-toggle button');
  btns.forEach(x => x.classList.toggle('active', x.dataset.density === density));
  document.body.dataset.density = density;
  try { localStorage.setItem('ps_density', density); } catch {}
  window.showToast(`Layout: ${density}`, 'info', 1500);
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
  let savedDensity = 'default';
  try { savedDensity = localStorage.getItem('ps_density') || 'default'; } catch {}
  const btns = $$('#density-toggle button');
  btns.forEach(b => b.classList.toggle('active', b.dataset.density === savedDensity));
  document.body.dataset.density = savedDensity;
}

function initSort() {
  const sortModes = [
    { label: 'Newest', icon: 'bi-sort-down' },
    { label: 'Popular', icon: 'bi-fire' },
    { label: 'Oldest', icon: 'bi-sort-up' },
  ];
  let sortIdx = 0;
  const btn = $('sort-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    sortIdx = (sortIdx + 1) % sortModes.length;
    const m = sortModes[sortIdx];
    btn.innerHTML = `<i class="bi ${m.icon}"></i><span>${m.label}</span>`;
  });
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
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCPIndex(Math.min(cpIndex + 1, cpItems.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCPIndex(Math.max(cpIndex - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const it = cpItems[cpIndex];
      if (it) it.action();
    }
  });

  document.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    const isInput = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
    if (mod && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (cp.classList.contains('open')) closeCP();
      else openCP();
    } else if (e.key === '/' && !cp.classList.contains('open') && !isInput) {
      e.preventDefault();
      $('search-input').focus();
    }
  });
}

function initSuggestions() {
  const sugList = $('suggest-list');
  const input = $('search-input');
  if (!sugList || !input) return;

  let debounceTimer = null;
  let sugItems = [];
  let sugIndex = -1;
  let sugAbort = null;

  function hideSuggest() {
    sugList.classList.remove('show');
    sugList.innerHTML = '';
    sugItems = [];
    sugIndex = -1;
  }

  function highlight(q, text) {
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return escapeHtml(text);
    return escapeHtml(text.slice(0, i)) +
      '<b>' + escapeHtml(text.slice(i, i + q.length)) + '</b>' +
      escapeHtml(text.slice(i + q.length));
  }

  function renderSuggest(q, items) {
    sugItems = items;
    sugIndex = -1;
    sugList.innerHTML = items.map(s => {
      if (s.type === 'user') {
        return `<li role="option" class="sug-user">
          <img class="sug-avatar" src="${s.image || ''}" alt="" loading="lazy"
               onerror="this.style.visibility='hidden'">
          <span class="sug-texts">
            <span class="sug-name">${highlight(q, s.text)}
              ${s.verified ? `<span class="sug-verified"><i class="bi bi-patch-check-fill"></i></span>` : ''}
            </span>
            ${s.sub ? `<span class="sug-sub">${escapeHtml(s.sub)}</span>` : ''}
          </span>
        </li>`;
      }
      return `<li role="option">
        <span class="sug-ico"><i class="bi bi-search"></i></span>
        <span>${highlight(q, s.text)}</span>
      </li>`;
    }).join('');
    sugList.classList.toggle('show', items.length > 0);
    [...sugList.children].forEach((li, i) =>
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = sugItems[i].text;
        hideSuggest();
        startScrape();
      })
    );
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
        const r = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`, {
          signal: sugAbort.signal,
        });
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
      [...sugList.children].forEach((li, i) =>
        li.classList.toggle('active', i === sugIndex)
      );
    } else if (e.key === 'Enter') {
      if (sugIndex >= 0 && sugItems[sugIndex]) {
        e.preventDefault();
        input.value = sugItems[sugIndex].text;
        hideSuggest();
        startScrape();
      }
    } else if (e.key === 'Escape') {
      hideSuggest();
    }
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

  $('tab-search').addEventListener('click', () => {
    if (currentView !== 'search') showSearch();
  });
  $('tab-gallery').addEventListener('click', () => {
    if (currentView !== 'gallery') showGallery();
  });

  $('cancel-btn').addEventListener('click', async () => {
    if (currentJob) {
      const btn = $('cancel-btn');
      btn.disabled = true;
      btn.innerHTML = '<i class="bi bi-hourglass-split"></i> …';
      try {
        await fetch(`/api/jobs/${currentJob}/cancel`, { method: 'POST' });
      } catch {}
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
    pmImg.addEventListener('click', (e) => {
      e.stopPropagation();
      pmImg.classList.toggle('zoomed');
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const drawer = $('settings-drawer');
      const modal = $('pin-modal');
      const cp = $('command-palette');
      if (cp.classList.contains('open')) { closeCP(); return; }
      if (drawer.classList.contains('open')) { openDrawer(false); return; }
      if (modal.classList.contains('open')) { closePinModal(); return; }
      if (selectionMode) { setSelectionMode(false); return; }
    }
    const modal = $('pin-modal');
    if (modal.classList.contains('open')) {
      if (e.key === 'ArrowLeft') pmNav(-1);
      if (e.key === 'ArrowRight') pmNav(1);
    }
  });

  $('sel-cancel').addEventListener('click', () => setSelectionMode(false));
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

      setSelectionMode(false);
      await updateGalleryBadge();
      window.showToast(`${deleted} image${deleted === 1 ? '' : 's'} deleted`, 'success');
      $('stats-card').innerHTML = `
        <div class="stats-header">
          <span class="stats-title">
            <i class="bi bi-trash3"></i> ${deleted} images deleted
          </span>
          ${currentView === 'gallery' ? `<span class="stats-query">${lastPins.length} pins remaining</span>` : ''}
        </div>`;
      $('stats-card').classList.remove('hidden');
      $('export-bar').classList.add('hidden');
      if (!document.querySelector('.pin-card')) $('empty').classList.remove('hidden');
    } finally {
      deleteBtn.disabled = false;
    }
  });

  const shortcutsBtn = $('shortcuts-btn');
  if (shortcutsBtn) {
    shortcutsBtn.addEventListener('click', () => {
      window.showToast('⌘K search · / focus · ESC close · ← → navigate · long-press select', 'info', 6000);
    });
  }

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
      document.querySelectorAll('.pin-card.holding').forEach(c =>
        c.classList.remove('holding')
      );
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
    moveIndicator();
  });
  window.addEventListener('orientationchange', () => {
    setTimeout(moveIndicator, 200);
  });
  setTimeout(moveIndicator, 50);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => moveIndicator());
  }
}

function init() {
  syncDrawerFromSettings();
  updateGalleryBadge();
  checkHealth();
  setInterval(checkHealth, 30000);
  initTheme();
  initDensity();
  initSort();
  initCommandPalette();
  initSuggestions();
  wireEvents();
  renderRecent();
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