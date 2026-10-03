/* Local reading preferences. Public navigation never initiates AI work. */
(() => {
  'use strict';
  if (location.pathname.startsWith('/admin')) return;
  const KEYS = {saved: 'news-saved-v1', density: 'news-density-v1', visit: 'news-last-visit-v1', session: 'news-visit-session-v1'};
  const MAX_SAVED = 300;
  const ID = /^[A-Za-z0-9_-]{1,80}$/;
  const memory = new Map();
  let persistent = true;
  function get(key, session = false) {
    try { return (session ? sessionStorage : localStorage).getItem(key); }
    catch (_) { persistent = false; return memory.get(key) ?? null; }
  }
  function set(key, value, session = false) {
    memory.set(key, value);
    try { (session ? sessionStorage : localStorage).setItem(key, value); }
    catch (_) { persistent = false; }
  }
  function readSaved() {
    try {
      const value = JSON.parse(get(KEYS.saved) || '[]');
      return Array.isArray(value) ? [...new Set(value.filter(id => typeof id === 'string' && ID.test(id)))].slice(0, MAX_SAVED) : [];
    } catch (_) { return []; }
  }
  let saved = readSaved();
  let density = get(KEYS.density) === 'compact' ? 'compact' : 'comfortable';
  const now = Date.now();
  let visit;
  try { visit = JSON.parse(get(KEYS.session, true) || 'null'); } catch (_) { visit = null; }
  const previous = Number(get(KEYS.visit));
  if (!visit || !Number.isFinite(visit.cutoff) || !Number.isFinite(visit.lastActivity) || now - visit.lastActivity > 30 * 60 * 1000 || visit.lastActivity > now) {
    visit = {cutoff: previous > 0 && previous <= now ? previous : now, first: !(previous > 0 && previous <= now), lastActivity: now};
  }
  function rememberVisit() {
    visit.lastActivity = Date.now();
    set(KEYS.session, JSON.stringify(visit), true);
    set(KEYS.visit, String(visit.lastActivity));
  }
  rememberVisit();
  window.addEventListener('pagehide', rememberVisit);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') rememberVisit(); });

  function savedHeader(url) {
    const target = new URL(url, location.href);
    if (target.origin !== location.origin || target.pathname !== '/ulozene') return {};
    // Stay below the ordinary per-header limit even with 300 saved articles.
    const chunks = [''];
    for (const id of saved) {
      const last = chunks.length - 1;
      const candidate = chunks[last] ? chunks[last] + ',' + id : id;
      if (candidate.length > 6000) chunks.push(id);
      else chunks[last] = candidate;
    }
    return Object.fromEntries(chunks.map((chunk, i) => ['X-Saved-Articles' + (i ? '-' + (i + 1) : ''), chunk]));
  }
  window.newsReaderHeaders = savedHeader;

  function feedback(message) {
    let region = document.getElementById('reader-feedback');
    if (!region) {
      region = document.createElement('p');
      region.id = 'reader-feedback';
      region.className = 'reader-feedback';
      region.setAttribute('role', 'status');
      (document.querySelector('.reader-toolbar') || document.querySelector('.detail-header') || document.getElementById('main'))?.append(region);
    }
    region.textContent = message;
  }

  function firstSeen(value) {
    if (!value) return NaN;
    let text = value.replace(' ', 'T');
    if (!/(?:Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z';
    return Date.parse(text);
  }
  function paint() {
    document.body.dataset.readerDensity = density;
    const toggle = document.getElementById('density-toggle');
    if (toggle) toggle.setAttribute('aria-pressed', String(density === 'compact'));
    const count = document.getElementById('saved-count');
    if (count) { count.textContent = String(saved.length); count.hidden = !saved.length; }
    document.querySelectorAll('[data-save-id]').forEach(button => {
      const active = saved.includes(button.dataset.saveId);
      button.setAttribute('aria-pressed', String(active));
      const title = button.dataset.articleTitle || '';
      const label = active ? 'Odstrániť z uložených' : 'Uložiť na neskôr';
      button.setAttribute('aria-label', title ? `${label}: ${title}` : label);
      button.title = label;
      const text = button.querySelector('[data-save-label]');
      if (text) text.textContent = label;
    });
    const newIds = new Set();
    document.querySelectorAll('[data-article-id][data-first-seen]').forEach(item => {
      const isNew = firstSeen(item.dataset.firstSeen) > visit.cutoff;
      if (isNew) newIds.add(item.dataset.articleId);
    });
    // Badges use their closest article, so opening a grouped member remains accurate.
    document.querySelectorAll('[data-new-badge]').forEach(badge => {
      const item = badge.closest('[data-article-id]');
      badge.hidden = !item || !(firstSeen(item.dataset.firstSeen) > visit.cutoff);
    });
    document.querySelectorAll('[data-group-new-badge]').forEach(badge => {
      const group = badge.closest('.story-group');
      const representative = group.closest('[data-article-id]');
      badge.hidden = firstSeen(representative.dataset.firstSeen) > visit.cutoff || ![...group.querySelectorAll('[data-article-id]')].some(item => firstSeen(item.dataset.firstSeen) > visit.cutoff);
    });
    const news = document.getElementById('reader-new-count');
    const newLabel = newIds.size === 1 ? 'nový článok' : newIds.size < 5 ? 'nové články' : 'nových článkov';
    if (news) news.textContent = newIds.size ? `${newIds.size} ${newLabel} na tejto stránke` : visit.first ? 'Pri ďalšej návšteve označíme nové články.' : 'Na tejto stránke nie sú nové články od poslednej návštevy.';
    const mark = document.getElementById('mark-news-read');
    if (mark) mark.disabled = !newIds.size;
  }

  let pending = null;
  let sequence = 0;
  function cancelSaved() { sequence += 1; pending?.abort(); pending = null; }
  document.addEventListener('news:navigating', cancelSaved);
  window.addEventListener('popstate', cancelSaved);
  async function refreshSaved() {
    if (location.pathname !== '/ulozene') return;
    const main = document.getElementById('main');
    const marker = document.getElementById('reader-content');
    if (!main || main.hasAttribute('aria-busy') || !marker || !window.fetch || !window.AbortController) return;
    let rendered = [];
    try { rendered = JSON.parse(marker.dataset.savedIds || '[]'); } catch (_) { /* Re-fetch invalid markup. */ }
    if (JSON.stringify(rendered) === JSON.stringify(saved)) return;
    cancelSaved();
    const ticket = sequence;
    const controller = new AbortController();
    pending = controller;
    const target = new URL(location.href);
    main.setAttribute('aria-busy', 'true');
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(target.href, {credentials: 'same-origin', signal: controller.signal, headers: {'Accept': 'text/html', ...savedHeader(target)}});
      if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html') || new URL(response.url || target.href).origin !== location.origin) throw new Error('saved_unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = page.getElementById('main');
      if (!replacement) throw new Error('saved_unavailable');
      if (ticket !== sequence || location.href !== target.href || document.getElementById('main') !== main) return;
      replacement.querySelectorAll('script').forEach(script => script.remove());
      main.replaceWith(document.importNode(replacement, true));
      pending = null;
      document.dispatchEvent(new CustomEvent('news:navigated', {detail: {url: target.href, main: document.getElementById('main')}}));
      const heading = document.querySelector('#main h1');
      heading?.setAttribute('tabindex', '-1');
      heading?.focus({preventScroll: true});
    } catch (_) {
      if (ticket === sequence && location.href === target.href) feedback('Uložené články sa nepodarilo načítať. Obnovte stránku a skúste to znova.');
    } finally {
      clearTimeout(timeout);
      if (ticket === sequence) { pending = null; main.removeAttribute('aria-busy'); }
    }
  }

  document.addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('button') : null;
    if (!button) return;
    if (button.matches('[data-save-id]')) {
      const id = button.dataset.saveId;
      if (!ID.test(id)) return;
      const active = saved.includes(id);
      if (!active && saved.length >= MAX_SAVED) { feedback('Môžete uložiť najviac 300 článkov. Najprv niektorý odstráňte z uložených.'); return; }
      saved = active ? saved.filter(value => value !== id) : [...saved, id];
      set(KEYS.saved, JSON.stringify(saved));
      paint();
      feedback(persistent ? (active ? 'Článok bol odstránený z uložených.' : 'Článok bol uložený v tomto prehliadači.') : 'Trvalé uloženie v tomto prehliadači nie je dostupné. Výber zostane iba do zatvorenia stránky.');
      refreshSaved();
    } else if (button.id === 'density-toggle') {
      density = density === 'compact' ? 'comfortable' : 'compact';
      set(KEYS.density, density);
      paint();
    } else if (button.id === 'mark-news-read') {
      visit.cutoff = Date.now();
      visit.first = false;
      rememberVisit();
      paint();
      feedback('Nové články boli označené ako prečítané.');
    }
  });
  window.addEventListener('storage', event => {
    if (event.key === KEYS.saved || event.key === null) { saved = readSaved(); paint(); refreshSaved(); }
    if (event.key === KEYS.density || event.key === null) { density = get(KEYS.density) === 'compact' ? 'compact' : 'comfortable'; paint(); }
  });
  document.addEventListener('news:navigated', () => { rememberVisit(); paint(); refreshSaved(); });
  paint();
  refreshSaved();
})();
