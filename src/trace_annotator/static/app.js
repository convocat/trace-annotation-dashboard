// trace-annotation-dashboard — browser logic
//
// Fetches trace *IDs* up front (cheap list) and fetches full trace content on
// demand when the user navigates to one. Content is PII-scrubbed on the server
// before it reaches us; we never hold raw trace text.

const STATE_KEY = 'trace_dashboard_state_v1';

let TRACE_IDS = [];      // [{id}, ...]
let ANNOTATIONS = {};    // {trace_id: annotation}
let FILTERED = [];       // filtered subset
let CURRENT = 0;         // index within FILTERED
let TRACE_INDEX = {};    // trace_id → fetched Trace (session cache, mirrors server cache)

function saveState() {
  try {
    const state = {
      position: CURRENT,
      trace_id: FILTERED[CURRENT]?.id || null,
      filters: {
        source: document.getElementById('filterSource').value,
        status: document.getElementById('filterStatus').value,
        search: document.getElementById('filterSearch').value,
      },
    };
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
  } catch (e) { /* ignore quota errors */ }
}

function loadState() {
  try { return JSON.parse(localStorage.getItem(STATE_KEY)) || null; }
  catch { return null; }
}

async function init() {
  const [ids, anns] = await Promise.all([
    fetch('/api/traces').then(r => r.json()),
    fetch('/api/annotations').then(r => r.json()),
  ]);
  TRACE_IDS = ids;
  ANNOTATIONS = anns;

  const state = loadState();
  setupFilters(state?.filters);
  applyFilters();

  if (state) {
    if (state.trace_id) {
      const idx = FILTERED.findIndex(t => t.id === state.trace_id);
      if (idx >= 0) { CURRENT = idx; }
    } else if (typeof state.position === 'number' && state.position < FILTERED.length) {
      CURRENT = state.position;
    }
  }
  await render();
  setupHotkeys();
}

function setupFilters(restored) {
  // Source list comes from annotation data (sources we've already annotated)
  // plus whatever metadata the backend returns later.
  const sources = [...new Set(Object.values(ANNOTATIONS).map(a => a.source).filter(Boolean))].sort();
  const srcSel = document.getElementById('filterSource');
  for (const s of sources) srcSel.add(new Option(s, s));

  if (restored) {
    if (restored.source) srcSel.value = restored.source;
    if (restored.status) document.getElementById('filterStatus').value = restored.status;
    if (restored.search) document.getElementById('filterSearch').value = restored.search;
  }

  for (const id of ['filterSource', 'filterStatus', 'filterSearch']) {
    document.getElementById(id).addEventListener('input', applyFilters);
  }
}

function applyFilters() {
  const fSrc = document.getElementById('filterSource').value;
  const fStatus = document.getElementById('filterStatus').value;
  const fSearch = document.getElementById('filterSearch').value.toLowerCase().trim();

  FILTERED = TRACE_IDS.filter(t => {
    const ann = ANNOTATIONS[t.id];
    if (fSrc && ann?.source !== fSrc) return false;
    if (fStatus === 'todo' && ann) return false;
    if (fStatus === 'done' && !ann) return false;
    if (fStatus === 'pass' && (!ann || ann.pass_fail !== 'pass')) return false;
    if (fStatus === 'fail' && (!ann || ann.pass_fail !== 'fail')) return false;
    if (fSearch) {
      // Search matches annotated question excerpts. Full-text search on un-fetched
      // traces would require a round-trip per trace — we defer that.
      const text = ((ann?.question_excerpt || '') + ' ' + (ann?.note || '')).toLowerCase();
      if (!text.includes(fSearch)) return false;
    }
    return true;
  });

  CURRENT = 0;
  renderProgress();
  renderCategoryCounts();
  render();
  saveState();
}

function renderProgress() {
  const total = FILTERED.length;
  const done = FILTERED.filter(t => ANNOTATIONS[t.id]).length;
  const suffix = window.i18n ? window.i18n.t('progress.labelSuffix') : 'annotated';
  document.getElementById('progressText').textContent = `${done} / ${total} ${suffix}`;
  document.getElementById('progressFill').style.width = total ? (100 * done / total) + '%' : '0%';
}

function renderCategoryCounts() {
  const counts = {};
  for (const ann of Object.values(ANNOTATIONS)) {
    if (ann.category) counts[ann.category] = (counts[ann.category] || 0) + 1;
  }
  const list = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  const dl = document.getElementById('catOptions');
  dl.innerHTML = '';
  for (const [c] of list) {
    const opt = document.createElement('option');
    opt.value = c;
    dl.appendChild(opt);
  }

  const cl = document.getElementById('catList');
  if (list.length === 0) {
    const empty = window.i18n ? window.i18n.t('categories.empty') : 'No categories yet';
    cl.innerHTML = `<em class="muted" data-i18n="categories.empty">${escapeHtml(empty)}</em>`;
  } else {
    cl.innerHTML = list
      .map(([c, n]) => `<div class="cat-row"><span>${escapeHtml(c)}</span><span class="count">${n}</span></div>`)
      .join('');
  }
}

async function fetchTrace(trace_id) {
  if (TRACE_INDEX[trace_id]) return TRACE_INDEX[trace_id];
  const r = await fetch(`/api/traces/${encodeURIComponent(trace_id)}`);
  if (!r.ok) return null;
  const trace = await r.json();
  TRACE_INDEX[trace_id] = trace;
  return trace;
}

async function render() {
  const T = (k, fb) => window.i18n ? window.i18n.t(k) : fb;
  if (FILTERED.length === 0) {
    document.getElementById('position').textContent = T('position.noMatch', 'No traces match the filter');
    document.getElementById('traceCard').style.display = 'none';
    return;
  }
  document.getElementById('traceCard').style.display = '';
  const stub = FILTERED[CURRENT];
  document.getElementById('position').textContent =
    `${T('position.tracePrefix', 'Trace')} ${CURRENT + 1} / ${FILTERED.length}`;
  document.getElementById('traceIdLabel').textContent = stub.id;

  const trace = await fetchTrace(stub.id);
  if (!trace || trace.error) {
    document.getElementById('messages').innerHTML =
      `<div class="bubble empty">${escapeHtml(T('trace.cannotLoad', 'Could not load this trace.'))}</div>`;
    return;
  }

  const meta = document.getElementById('traceMeta');
  meta.innerHTML = '';
  // Source tag from metadata
  const source = trace.metadata?._source || trace.metadata?.name || '';
  if (source) meta.appendChild(tag(source, 'source'));

  // Other metadata tags (skip internal underscore-prefixed keys)
  for (const [k, v] of Object.entries(trace.metadata || {})) {
    if (k.startsWith('_')) continue;
    if (typeof v === 'string' || typeof v === 'number') {
      meta.appendChild(tag(`${k}: ${v}`));
    }
  }

  // Langfuse deep-link when metadata carries the hints
  const lfHost = trace.metadata?._langfuse_host;
  const lfProj = trace.metadata?._langfuse_project_id;
  if (lfHost) {
    const a = document.createElement('a');
    const href = lfProj
      ? `${lfHost}/project/${encodeURIComponent(lfProj)}/traces/${encodeURIComponent(trace.id)}`
      : `${lfHost}/traces/${encodeURIComponent(trace.id)}`;
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'tag langfuse-link';
    a.textContent = T('trace.openInLangfuse', '↗ Open in Langfuse');
    meta.appendChild(a);
  }

  // Render messages
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
  if (!trace.messages?.length) {
    const d = document.createElement('div');
    d.className = 'bubble empty';
    d.textContent = T('trace.noMessages', '(no messages available for this trace)');
    msgs.appendChild(d);
  } else {
    for (const m of trace.messages) {
      const d = document.createElement('div');
      d.className = `bubble ${m.role}`;
      const label = document.createElement('div');
      label.className = 'bubble-label';
      label.textContent = T(`bubble.${m.role}`, m.role);
      const body = document.createElement('div');
      body.textContent = m.content;
      d.appendChild(label);
      d.appendChild(body);
      msgs.appendChild(d);
    }
  }

  // Context block (prior review)
  const ctx = trace.metadata?._context || {};
  const ctxKeys = Object.keys(ctx);
  const ctxBlock = document.getElementById('contextBlock');
  if (ctxKeys.length === 0) {
    ctxBlock.hidden = true;
  } else {
    ctxBlock.hidden = false;
    const dl = document.getElementById('contextList');
    dl.innerHTML = '';
    for (const k of ctxKeys) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = ctx[k];
      dl.appendChild(dt); dl.appendChild(dd);
    }
  }

  // Sources
  const sourcesBlock = document.getElementById('sources');
  if (trace.sources?.length) {
    sourcesBlock.hidden = false;
    const ul = document.getElementById('sourceList');
    ul.innerHTML = '';
    for (const src of trace.sources) {
      const li = document.createElement('li');
      li.textContent = src;
      ul.appendChild(li);
    }
  } else {
    sourcesBlock.hidden = true;
  }

  // Prefill form
  const ann = ANNOTATIONS[trace.id];
  document.getElementById('fldNote').value = ann?.note || '';
  document.getElementById('fldCategory').value = ann?.category || '';
  document.getElementById('fldAction').value = ann?.action || '';
  document.getElementById('fldResponse').value = ann?.response || '';
  setPF(ann?.pass_fail || '');
}

function setPF(value) {
  document.getElementById('btnPass').classList.toggle('active', value === 'pass');
  document.getElementById('btnFail').classList.toggle('active', value === 'fail');
}

function getPF() {
  if (document.getElementById('btnPass').classList.contains('active')) return 'pass';
  if (document.getElementById('btnFail').classList.contains('active')) return 'fail';
  return '';
}

function tag(text, cls = '') {
  const span = document.createElement('span');
  span.className = 'tag ' + cls;
  span.textContent = text;
  return span;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function _collectPayload() {
  if (FILTERED.length === 0) return null;
  const stub = FILTERED[CURRENT];
  const trace = TRACE_INDEX[stub.id];
  const firstUser = trace?.messages?.find(m => m.role === 'user')?.content || '';
  const firstAsst = trace?.messages?.find(m => m.role === 'assistant')?.content || '';
  return {
    trace_id: stub.id,
    project: trace?.metadata?._langfuse_project_id || '',
    source: trace?.metadata?._source || trace?.metadata?.name || '',
    question_excerpt: firstUser.slice(0, 500),
    answer_excerpt: firstAsst.slice(0, 500),
    pass_fail: getPF(),
    note: document.getElementById('fldNote').value.trim(),
    category: document.getElementById('fldCategory').value.trim(),
    action: document.getElementById('fldAction').value.trim(),
    response: document.getElementById('fldResponse').value.trim(),
  };
}

function _hasContent(p) {
  return !!(p && (p.pass_fail || p.note || p.category || p.action || p.response));
}

async function _writeAnnotation(payload, showToast = true) {
  await fetch('/api/annotate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  ANNOTATIONS[payload.trace_id] = { ...payload, timestamp: new Date().toISOString() };
  renderProgress();
  renderCategoryCounts();
  if (showToast) toast(window.i18n ? window.i18n.t('toast.saved') : 'Saved ✓');
}

async function save() {
  const p = _collectPayload();
  if (!_hasContent(p)) {
    toast(window.i18n ? window.i18n.t('toast.nothing') : 'Nothing to save', '#888');
    return false;
  }
  await _writeAnnotation(p, true);
  return true;
}

async function autoSaveBeforeNav() {
  const p = _collectPayload();
  if (_hasContent(p)) {
    const existing = ANNOTATIONS[p.trace_id];
    if (existing &&
        existing.pass_fail === p.pass_fail &&
        existing.note === p.note &&
        existing.category === p.category &&
        existing.action === p.action &&
        existing.response === p.response) {
      return;
    }
    await _writeAnnotation(p, false);
  }
}

async function saveAndNext() {
  const ok = await save();
  if (ok !== false) _advance();
}

async function next() { await autoSaveBeforeNav(); _advance(); }
async function prev() {
  await autoSaveBeforeNav();
  if (CURRENT > 0) { CURRENT--; await render(); saveState(); }
}

async function _advance() {
  if (CURRENT < FILTERED.length - 1) { CURRENT++; await render(); saveState(); }
}

function toast(msg, color = '#2d8a4d') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1500);
}

function setupHotkeys() {
  document.addEventListener('keydown', e => {
    const inField = ['TEXTAREA', 'INPUT'].includes(e.target.tagName);
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); saveAndNext(); return; }
    if (inField) return;
    if (e.key === 'j' || e.key === 'ArrowRight') { e.preventDefault(); next(); }
    else if (e.key === 'k' || e.key === 'ArrowLeft') { e.preventDefault(); prev(); }
    else if (e.key === 'p' || e.key === 'P') { e.preventDefault(); setPF('pass'); }
    else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); setPF('fail'); }
  });
}

// Re-render dynamic parts when language changes (static strings handled by i18n.js)
document.addEventListener('langchanged', () => {
  renderProgress();
  renderCategoryCounts();
  render();
});

init();
