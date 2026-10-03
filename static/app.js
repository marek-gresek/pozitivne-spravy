/* Public navigation keeps audio playing; a full reload restores it paused. */
(() => {
  'use strict';
  const player = document.getElementById('player');
  const audio = document.getElementById('audio');
  if (!player || !audio) return;
  const title = document.getElementById('player-title');
  const toggle = document.getElementById('player-toggle');
  const progress = document.getElementById('player-progress');
  const time = document.getElementById('player-time');
  const speed = document.getElementById('player-speed');
  const error = document.getElementById('player-error');
  const chapterPanel = document.getElementById('player-chapters');
  const chapterSelect = document.getElementById('player-chapter');
  const previousChapter = document.getElementById('player-previous-chapter');
  const nextChapter = document.getElementById('player-next-chapter');
  const segments = document.getElementById('player-segments');
  const topicLabel = document.getElementById('player-topic-label');
  let chapterDuration = 0;
  let chapters = [];
  let chapterController = null;
  const key = 'pozitivne-spravy-player-v1';
  let current = null;
  let desiredPosition = 0;
  let lastSaved = 0;
  const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  function persist() {
    if (!current) return;
    try { localStorage.setItem(key, JSON.stringify({...current, position: audio.currentTime || desiredPosition || 0, speed: audio.playbackRate, paused: audio.paused})); } catch (_) { /* Storage may be disabled. */ }
  }
  function announce(message) { error.textContent = message; error.hidden = !message; }
  function show() { player.hidden = false; document.body.classList.add('player-open'); }
  function applySpeed() {
    const rate = Number(speed.value);
    audio.defaultPlaybackRate = rate;
    audio.playbackRate = rate;
  }
  function chapterIndex() {
    let index = 0;
    for (let i = 0; i < chapters.length; i++) {
      if (chapters[i].start > audio.currentTime + 0.1) break;
      index = i;
    }
    return index;
  }
  function updateChapters() {
    if (!chapters.length) return;
    const index = chapterIndex();
    chapterSelect.value = String(index);
    if (segments) Array.from(segments.children).forEach((button,i) => {
      button.dataset.active = String(i === index);
      if (i === index) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    });
    if (topicLabel) { topicLabel.textContent = chapters[index].title; topicLabel.hidden = false; }
    previousChapter.disabled = index === 0 && audio.currentTime <= chapters[0].start + 3;
    nextChapter.disabled = index === chapters.length - 1;
    previousChapter.title = index > 0 && audio.currentTime <= chapters[index].start + 3
      ? 'Predchádzajúca kapitola: ' + chapters[index - 1].title : 'Začiatok kapitoly: ' + chapters[index].title;
    previousChapter.setAttribute('aria-label', previousChapter.title);
    nextChapter.title = index < chapters.length - 1 ? 'Ďalšia kapitola: ' + chapters[index + 1].title : 'Posledná kapitola';
    nextChapter.setAttribute('aria-label', nextChapter.title);
  }
  function clearTimeline() {
    chapterDuration = 0;
    if (segments) { segments.replaceChildren(); segments.hidden = true; }
    if (topicLabel) { topicLabel.textContent = ''; topicLabel.hidden = true; }
  }
  function renderTimeline() {
    if (!segments) return;
    const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : chapterDuration;
    segments.replaceChildren(); segments.hidden = true;
    if (!chapters.length || !duration) return;
    // Ignore malformed/out-of-range starts; preserve proportional widths, including short topics.
    chapters = chapters.filter(ch => ch.start < duration);
    chapterSelect.replaceChildren();
    chapters.forEach((chapter,index) => {
      const option = document.createElement('option'); option.value = String(index);
      option.textContent = clock(chapter.start) + ' · ' + chapter.title;
      chapterSelect.append(option);
      const end = index + 1 < chapters.length ? chapters[index + 1].start : duration;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'player-segment';
      button.style.flexBasis = String((end - chapter.start) / duration * 100) + '%';
      button.style.flexGrow = '0'; button.style.flexShrink = '0';
      button.title = clock(chapter.start) + ' · ' + chapter.title;
      button.setAttribute('aria-label', 'Prejsť na tému: ' + button.title);
      const label = document.createElement('span'); label.className = 'player-segment-label';
      label.textContent = chapter.title; button.append(label);
      button.addEventListener('click', () => { seek(chapter.start); update(); persist(); });
      segments.append(button);
    });
    segments.hidden = !chapters.length; chapterPanel.hidden = !chapters.length;
    updateChapters();
  }
  async function loadChapters(episode) {
    if (chapterController) chapterController.abort();
    const controller = new AbortController(); chapterController = controller;
    chapters = []; clearTimeline(); chapterSelect.replaceChildren(); chapterPanel.hidden = true;
    previousChapter.disabled = true; nextChapter.disabled = true;
    try {
      const response = await fetch(episode.href + '/kapitoly.json', {signal: controller.signal, credentials: 'same-origin'});
      if (!response.ok) return;
      const data = await response.json();
      if (controller !== chapterController || !data.available || !Array.isArray(data.chapters)) return;
      chapterDuration = Number.isFinite(data.duration) && data.duration > 0 ? data.duration : 0;
      chapters = data.chapters.filter(ch => ch && typeof ch.title === 'string' && Number.isFinite(ch.start) && ch.start >= 0)
        .sort((a,b) => a.start - b.start)
        .filter((chapter,index,list) => !index || chapter.start > list[index - 1].start);
      chapters.forEach((chapter,index) => {
        const option = document.createElement('option'); option.value = String(index);
        option.textContent = clock(chapter.start) + ' · ' + chapter.title;
        chapterSelect.append(option);
      });
      chapterPanel.hidden = !chapters.length; renderTimeline(); updateChapters();
    } catch (_) { /* Audio and the episode transcript remain usable if metadata cannot load. */ }
  }
  chapterSelect.addEventListener('change', () => {
    const chapter = chapters[Number(chapterSelect.value)];
    if (chapter) { seek(chapter.start); update(); persist(); }
  });
  previousChapter.addEventListener('click', () => {
    if (!chapters.length) return;
    const index = chapterIndex();
    seek(chapters[audio.currentTime > chapters[index].start + 3 ? index : Math.max(0,index - 1)].start);
    update(); persist();
  });
  nextChapter.addEventListener('click', () => {
    if (!chapters.length) return;
    seek(chapters[Math.min(chapterIndex() + 1,chapters.length - 1)].start); update(); persist();
  });
  function load(episode, position = 0) {
    audio.pause(); current = episode; desiredPosition = Math.max(0, Number(position) || 0);
    title.textContent = episode.title; title.href = episode.href;
    audio.src = episode.audio; audio.load(); applySpeed();
    announce(''); show(); loadChapters(episode);
  }
  function seek(position) {
    desiredPosition = Math.max(0, Number(position) || 0);
    if (audio.readyState >= 1) { audio.currentTime = Math.min(desiredPosition, audio.duration || desiredPosition); desiredPosition = 0; }
  }
  async function play() {
    try { await audio.play(); announce(''); }
    catch (_) { announce('Audio sa nepodarilo spustiť. Skúste to znova alebo otvorte epizódu.'); }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-episode-id]');
    if (!button) return;
    const episode = {id: button.dataset.episodeId, audio: button.dataset.audio, title: button.dataset.title, href: button.dataset.href};
    if (!current || current.id !== episode.id) load(episode, button.dataset.start || 0);
    else if (button.dataset.start !== undefined) seek(button.dataset.start);
    show(); play(); persist();
  });
  toggle.addEventListener('click', () => { if (audio.paused) play(); else audio.pause(); });
  audio.addEventListener('loadedmetadata', () => { if (desiredPosition) seek(desiredPosition); renderTimeline(); update(); });
  audio.addEventListener('durationchange', renderTimeline);
  function syncPlaybackControl() {
    const playing = !audio.paused && !audio.ended;
    const label = playing ? 'Pozastaviť podcast' : 'Prehrať podcast';
    toggle.dataset.playing = String(playing);
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
  }
  audio.addEventListener('play', () => { syncPlaybackControl(); persist(); });
  audio.addEventListener('pause', () => { syncPlaybackControl(); persist(); });
  audio.addEventListener('ended', () => { syncPlaybackControl(); persist(); });
  audio.addEventListener('error', () => { announce('Audio nie je dostupné. Mohlo uplynúť 14 dní jeho uchovávania. Prepis zostáva v epizóde.'); });
  function update() {
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    time.textContent = `${clock(audio.currentTime || 0)} / ${clock(duration)}`;
    progress.value = duration ? audio.currentTime / duration * 100 : 0;
    progress.setAttribute('aria-valuetext', time.textContent);
    updateChapters();
  }
  audio.addEventListener('timeupdate', () => { update(); if (Date.now() - lastSaved > 2000) { persist(); lastSaved = Date.now(); } });
  progress.addEventListener('input', () => { if (Number.isFinite(audio.duration)) { seek(Number(progress.value) / 100 * audio.duration); update(); persist(); } });
  speed.addEventListener('change', () => { applySpeed(); persist(); });
  document.getElementById('player-close').addEventListener('click', () => { audio.pause(); current = null; if (chapterController) chapterController.abort(); chapters = []; clearTimeline(); chapterPanel.hidden = true; audio.removeAttribute('src'); audio.load(); player.hidden = true; document.body.classList.remove('player-open'); try { localStorage.removeItem(key); } catch (_) {} });
  window.addEventListener('pagehide', persist);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') persist(); });
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved && typeof saved.id === 'string' && typeof saved.title === 'string' && saved.audio === '/audio/' + encodeURIComponent(saved.id) && saved.href === '/podcasty/' + encodeURIComponent(saved.id)) {
      if ([0.75, 1, 1.25, 1.5, 2].includes(Number(saved.speed))) speed.value = String(saved.speed);
      load(saved, saved.position); // Restoring never auto-plays or overrides a pause.
    }
  } catch (_) { /* Corrupt or unavailable storage must not affect reading. */ }
})();

/* Replace public page content without replacing the active audio element. */
(() => {
  'use strict';
  if (!window.fetch || !window.AbortController || !document.getElementById('main')) return;
  const publicPath = path => path === '/' || path === '/archiv' || path === '/ulozene' || path === '/o-projekte' || /^\/podcasty(?:\/[^/]+)?$/.test(path) || /^\/clanok\/[^/]+$/.test(path);
  const isPublic = url => url.origin === location.origin && publicPath(url.pathname);
  if (!isPublic(new URL(location.href))) return;
  let renderedURL = new URL(location.href);
  let sequence = 0;
  let pending = null;
  const status = document.createElement('p');
  status.className = 'sr-only';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');
  document.body.append(status);

  function saveScroll() {
    history.replaceState({...history.state, newsReader: {x: window.scrollX, y: window.scrollY}}, '', location.href);
  }
  function cancelPending() {
    sequence += 1;
    if (pending) pending.abort();
    pending = null;
    document.getElementById('main')?.removeAttribute('aria-busy');
    status.textContent = '';
  }
  saveScroll();
  let scrollFrame = null;
  window.addEventListener('scroll', () => {
    if (pending || scrollFrame !== null) return;
    scrollFrame = requestAnimationFrame(() => { scrollFrame = null; if (!pending) saveScroll(); });
  }, {passive: true});

  async function navigate(url, {back = false, state = null, form = false} = {}) {
    document.dispatchEvent(new CustomEvent('news:navigating'));
    if (!back) saveScroll();
    if (pending) pending.abort();
    const ticket = ++sequence;
    const controller = new AbortController();
    pending = controller;
    const main = document.getElementById('main');
    main.setAttribute('aria-busy', 'true');
    status.textContent = 'Načítava sa stránka.';
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.href, {signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'text/html', ...window.newsReaderHeaders?.(url)}});
      if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) throw new Error('navigation_failed');
      const finalURL = new URL(response.url || url.href);
      if (!isPublic(finalURL) || finalURL.hash) throw new Error('unexpected_destination');
      const markup = await response.text();
      if (ticket !== sequence) return;
      const page = new DOMParser().parseFromString(markup, 'text/html');
      const replacement = page.getElementById('main');
      if (!replacement || !page.title) throw new Error('missing_page');
      replacement.querySelectorAll('script').forEach(script => script.remove());
      const nextMain = document.importNode(replacement, true);
      nextMain.removeAttribute('aria-busy');
      if (!back) history.pushState({newsReader: {x: 0, y: 0}}, '', finalURL.href);
      main.replaceWith(nextMain);
      document.title = page.title;
      document.querySelectorAll('header nav a').forEach(link => {
        const corresponding = Array.from(page.querySelectorAll('header nav a')).find(candidate => candidate.getAttribute('href') === link.getAttribute('href'));
        if (corresponding?.hasAttribute('aria-current')) link.setAttribute('aria-current', corresponding.getAttribute('aria-current'));
        else link.removeAttribute('aria-current');
      });
      const changedMood = !back && !form && [['page_positive','positive'],['page_neutral','neutral'],['page_negative','negative']].find(([key]) => (finalURL.searchParams.get(key) || '1') !== (renderedURL.searchParams.get(key) || '1'));
      renderedURL = finalURL;
      pending = null;
      const focus = changedMood ? nextMain.querySelector('.mood-group.' + changedMood[1] + ' h2') || nextMain : form ? nextMain.querySelector('.list-heading') || nextMain : nextMain.querySelector('h1') || nextMain;
      focus.setAttribute('tabindex', '-1');
      focus.focus({preventScroll: true});
      if (back && state?.newsReader) window.scrollTo(state.newsReader.x || 0, state.newsReader.y || 0);
      else if ((form || changedMood) && focus !== nextMain) focus.scrollIntoView({block: 'start', behavior: 'instant'});
      else window.scrollTo({top: 0, left: 0, behavior: 'instant'});
      status.textContent = form ? `${nextMain.querySelector('.list-heading p')?.textContent || 'Výsledky vyhľadávania'}. ${page.title}` : page.title;
      document.dispatchEvent(new CustomEvent('news:navigated', {detail: {url: finalURL.href, main: nextMain}}));
      saveScroll();
    } catch (_) {
      if (ticket !== sequence) return;
      // The browser's ordinary navigation remains the recovery path.
      if (back) location.replace(url.href);
      else location.assign(url.href);
    } finally {
      clearTimeout(timeout);
      if (ticket === sequence) {
        pending = null;
        document.getElementById('main')?.removeAttribute('aria-busy');
      }
    }
  }

  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (!link || link.hasAttribute('download') || link.hasAttribute('data-native') || (link.target && link.target !== '_self') || link.relList.contains('external')) return;
    const url = new URL(link.href, location.href);
    if (url.hash) {
      if (url.origin === location.origin && url.pathname === location.pathname && url.search === location.search) cancelPending();
      return;
    }
    if (!isPublic(url)) return;
    event.preventDefault();
    navigate(url);
  });

  document.addEventListener('submit', event => {
    if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
    const form = event.target;
    const submitter = event.submitter;
    const method = (submitter?.getAttribute('formmethod') || form.method || 'get').toLowerCase();
    const target = submitter?.getAttribute('formtarget') || form.target;
    if (method !== 'get' || (target && target !== '_self') || form.hasAttribute('data-native')) return;
    const url = new URL(submitter?.getAttribute('formaction') || form.action || location.href, location.href);
    if (!isPublic(url) || url.hash || submitter?.type === 'image') return;
    const data = new FormData(form);
    if (Array.from(data.values()).some(value => typeof value !== 'string')) return;
    if (submitter?.name) data.append(submitter.name, submitter.value);
    url.search = new URLSearchParams(data).toString();
    event.preventDefault();
    navigate(url, {form: true});
  });

  window.addEventListener('popstate', event => {
    const url = new URL(location.href);
    if (url.pathname === renderedURL.pathname && url.search === renderedURL.search) {
      cancelPending();
      return; // Hash and same-page history retain the browser's behavior.
    }
    if (!isPublic(url) || url.hash) { cancelPending(); location.reload(); return; }
    navigate(url, {back: true, state: event.state});
  });
})();

/* A page-wide theme, shared by the reader and player, survives navigation. */
(() => {
  'use strict';
  const key = 'pozitivne-spravy-theme';
  const preference = window.matchMedia('(prefers-color-scheme: dark)');
  let selected = null;
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') selected = saved;
  } catch (_) { /* The system preference still works with storage disabled. */ }
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById('theme-toggle');
    const label = theme === 'dark' ? 'Prepnúť na svetlý režim' : 'Prepnúť na tmavý režim';
    if (button) {
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      button.dataset.theme = theme;
      const visibleLabel = button.querySelector('[data-theme-label]');
      if (visibleLabel) visibleLabel.textContent = theme === 'dark' ? 'Svetlý režim' : 'Tmavý režim';
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === 'dark' ? '#0B1220' : '#F0F3F8';
  }
  const systemTheme = () => preference.matches ? 'dark' : 'light';
  apply(selected || systemTheme());
  document.addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('#theme-toggle') : null;
    if (!button) return;
    selected = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    apply(selected);
    try { localStorage.setItem(key, selected); } catch (_) {}
  });
  preference.addEventListener('change', () => { if (!selected) apply(systemTheme()); });
  window.addEventListener('storage', event => {
    if (event.key !== key) return;
    selected = event.newValue === 'light' || event.newValue === 'dark' ? event.newValue : null;
    apply(selected || systemTheme());
  });
  document.addEventListener('news:navigated', () => apply(selected || systemTheme()));
})();
