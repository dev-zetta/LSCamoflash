'use strict';
(function (root) {
  const PAGE_SIZE = 100;
  const TABS = ['dashboard', 'recordings', 'streams', 'diagnostics'];
  function number(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER ? value : null;
  }
  function mib(kib) { return number(kib) === null ? 'Not reported' : (kib / 1024).toFixed(1) + ' MiB'; }
  function bytes(value) {
    if (number(value) === null) return 'Not reported';
    if (value < 1024) return value + ' B';
    if (value < 1048576) return (value / 1024).toFixed(1) + ' KiB';
    if (value < 1073741824) return (value / 1048576).toFixed(1) + ' MiB';
    return (value / 1073741824).toFixed(1) + ' GiB';
  }
  function duration(value) {
    if (number(value) === null) return 'Not reported';
    let seconds = Math.floor(value);
    const days = Math.floor(seconds / 86400); seconds %= 86400;
    const hours = Math.floor(seconds / 3600); seconds %= 3600;
    const minutes = Math.floor(seconds / 60); seconds %= 60;
    return (days ? days + 'd ' : '') + (hours || days ? hours + 'h ' : '') + (minutes || hours || days ? minutes + 'm' : seconds + 's');
  }
  function memoryValues(value) {
    const total = number(value && value.total_kB), available = number(value && value.available_kB);
    if (total === null || total <= 0 || available === null) return null;
    const bounded = Math.min(total, available);
    return {total: total, available: bounded, used: total - bounded, percent: (total - bounded) * 100 / total};
  }
  function ipv4(value) {
    if (typeof value !== 'string' || !/^\d{1,3}(\.\d{1,3}){3}$/.test(value)) return false;
    const parts = value.split('.').map(Number);
    return parts.every(part => part <= 255) && parts[0] > 0 && parts[0] !== 127 && parts[0] < 224;
  }
  function streamURL(value, ip, profile) {
    if (!ipv4(ip) || typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'rtsp:' && url.hostname === ip && url.port === '8554' && url.pathname === '/' + profile && !url.username && !url.password && !url.search && !url.hash ? url.href : null;
    } catch (_) { return null; }
  }
  function serviceURL(value, ip) {
    if (!ipv4(ip) || typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'http:' && url.hostname === ip && url.port && url.pathname === '/' && !url.username && !url.password && !url.search && !url.hash ? url.href : null;
    } catch (_) { return null; }
  }
  function validDay(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }
  function downloadURL(value) {
    if (typeof value !== 'string' || value.length > 1024 || /[\r\n]/.test(value)) return null;
    try {
      const base = 'http://fullhan.invalid/';
      const url = new URL(value, value.startsWith('cgi-bin/') ? base : base + 'cgi-bin/');
      const keys = Array.from(url.searchParams.keys());
      if (url.origin !== 'http://fullhan.invalid' || url.pathname !== '/cgi-bin/recordings.cgi' || url.username || url.password || url.hash || keys.length !== 3 || new Set(keys).size !== 3 || keys.some(key => !['action', 'day', 'file'].includes(key))) return null;
      const file = url.searchParams.get('file');
      if (url.searchParams.get('action') !== 'download' || !validDay(url.searchParams.get('day')) || !/^\d{14}-\d{14}\.mp4$/.test(file || '')) return null;
      return 'cgi-bin/recordings.cgi?' + url.searchParams.toString();
    } catch (_) { return null; }
  }
  function recordingLabel(name) {
    const match = /^(\d{8})(\d{2})(\d{2})(\d{2})-(\d{8})(\d{2})(\d{2})(\d{2})\.mp4$/.exec(name);
    return match ? match[2] + ':' + match[3] + ':' + match[4] + ' – ' + (match[1] === match[5] ? '' : match[5] + ' ') + match[6] + ':' + match[7] + ':' + match[8] : name;
  }
  function createApp(doc, fetcher, timers) {
    timers = timers || root;
    let interval = null, statusBusy = false, activeTab = 'dashboard', recordingRequest = 0, recordingsLoaded = false;
    let view = {kind: 'days', day: '', offset: 0, next: null, history: []}, recordingBusy = false;
    const el = id => doc.getElementById(id);
    const text = (id, value) => { el(id).textContent = value; };
    function message(id, value) { text(id, value); el(id).hidden = !value; }
    function link(id, value, placeholder) {
      const node = el(id); node.textContent = value || placeholder;
      if (value) node.setAttribute('href', value); else node.removeAttribute('href');
    }
    function meter(id, value) { el(id).hidden = value === null; el(id).value = value === null ? 0 : value; }
    function service(id, value) {
      text(id, value === true ? 'Running' : value === false ? 'Not running' : 'Not reported');
      el(id).className = value === true ? 'service-running' : value === false ? 'service-stopped' : 'muted';
    }
    async function json(url) {
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const timeout = controller ? timers.setTimeout(() => controller.abort(), 15000) : null;
      try {
        const response = await fetcher(url, {cache: 'no-store', credentials: 'same-origin', signal: controller ? controller.signal : undefined});
        if (!response.ok) throw new Error(response.status === 401 ? 'Authentication required. Reload this page to sign in.' : 'Request failed (' + response.status + ').');
        return await response.json();
      } catch (error) {
        if (error.name === 'AbortError') throw new Error('The camera did not respond in time. Try refreshing.');
        throw error;
      } finally { if (timeout !== null) timers.clearTimeout(timeout); }
    }
    function renderStatus(status) {
      if (!status || typeof status !== 'object' || !status.memory || !status.streams) throw new Error('The camera returned an incomplete status response.');
      for (const field of ['model', 'firmware', 'ip']) text(field, typeof status[field] === 'string' ? status[field] : 'Not reported');
      text('backend', typeof status.backend === 'string' ? status.backend : 'Not reported');
      text('uptime', duration(status.uptime_seconds));
      const memory = memoryValues(status.memory);
      text('ram-used', memory ? mib(memory.used) : 'Not reported');
      text('memory', memory ? 'Available: ' + mib(memory.available) + ' of ' + mib(memory.total) : 'Available RAM: not reported');
      text('ram-total', memory ? mib(memory.total) : 'Not reported');
      text('ram-available', memory ? mib(memory.available) : 'Not reported');
      text('ram-note', status.memory.available_reported === false ? 'Available RAM is estimated; cache is reclaimable.' : 'Uses the kernel’s available-memory estimate.');
      meter('ram-meter', memory ? memory.percent : null);
      const storage = status.storage || {};
      const storageValues = storage.mounted === true ? memoryValues({total_kB: storage.total_kB, available_kB: storage.available_kB}) : null;
      text('storage-used', storageValues ? mib(storageValues.used) : storage.mounted === false ? 'Not mounted' : 'Not reported');
      text('storage-available', storageValues ? 'Available: ' + mib(storageValues.available) + ' of ' + mib(storageValues.total) : 'Available space: not reported');
      text('storage-note', storage.mounted === false ? 'Recording storage is unavailable.' : 'SD card capacity');
      meter('storage-meter', storageValues ? storageValues.percent : null);
      const cpu = status.cpu || {}, loads = [cpu.load_1m, cpu.load_5m, cpu.load_15m].map(value => number(value) === null ? '—' : value.toFixed(2));
      text('cpu-load', loads[0]); text('cpu-loads', loads.join(' / '));
      const services = status.services || {}, onvif = status.onvif || {}, diagnostics = status.diagnostics || {};
      service('service-stock', services.stock_app); service('service-rtsp', services.rtsp);
      service('service-onvif', onvif.available === false ? undefined : services.onvif);
      if (onvif.available === false) text('service-onvif', 'Not available');
      const onvifLink = onvif.available === true ? serviceURL(onvif.url, status.ip) : null;
      link('onvif-url', onvifLink, 'Service address unavailable'); el('onvif-url').hidden = !onvifLink;
      let onvifNote = onvif.available === false ? 'ONVIF is not available in this payload.' : services.onvif === true ? 'The ONVIF service is running. Add the address below manually in your client.' : 'ONVIF is not running; a service address alone does not establish connectivity.';
      if (services.onvif === true && onvif.discovery_running === false) onvifNote += ' Discovery for this service is disabled; stock discovery may advertise a different endpoint.';
      if (services.onvif === true && onvif.discovery_running === true) onvifNote += ' The optional discovery helper is running; client discovery still depends on your local network.';
      text('onvif-note', onvifNote);
      text('management-rss', mib(diagnostics.management_rss_kB)); text('stock-rss', mib(diagnostics.stock_app_rss_kB));
      for (const profile of ['main', 'sub']) link(profile, streamURL(status.streams[profile], status.ip, profile), 'Stream address unavailable');
    }
    async function refreshStatus() {
      if (statusBusy) return;
      statusBusy = true; el('refresh-status').disabled = true;
      try {
        renderStatus(await json('cgi-bin/status.cgi'));
        message('error', ''); text('connection', 'Connected'); el('connection').className = 'status-badge online';
        text('last-updated', 'Updated ' + new Date().toLocaleTimeString());
      } catch (error) {
        message('error', error.message || 'Camera status is unavailable.'); text('connection', 'Status unavailable'); el('connection').className = 'status-badge offline';
        text('last-updated', 'Status may be out of date');
      } finally { statusBusy = false; el('refresh-status').disabled = false; }
    }
    function closePlayer() {
      const player = el('recording-player'); player.pause(); player.removeAttribute('src'); player.load();
      el('player-card').hidden = true;
    }
    function recordingButtons() {
      el('recordings-previous').disabled = recordingBusy || view.history.length === 0;
      el('recordings-next').disabled = recordingBusy || view.next === null;
      el('refresh-recordings').disabled = recordingBusy;
    }
    function appendRow(name, size, actions, subtitle) {
      const row = doc.createElement('tr'), label = doc.createElement('td'), amount = doc.createElement('td'), actionCell = doc.createElement('td');
      const title = doc.createElement('span'); title.textContent = name; label.appendChild(title);
      if (subtitle) { const detail = doc.createElement('div'); detail.className = 'small muted'; detail.textContent = subtitle; label.appendChild(detail); }
      amount.textContent = size;
      const actionGroup = doc.createElement('div'); actionGroup.className = 'row-actions';
      actions.forEach(action => actionGroup.appendChild(action)); actionCell.appendChild(actionGroup);
      row.appendChild(label); row.appendChild(amount); row.appendChild(actionCell); el('recording-rows').appendChild(row);
    }
    function button(label, callback) {
      const node = doc.createElement('button'); node.type = 'button'; node.className = 'button button-secondary'; node.textContent = label; node.addEventListener('click', callback); return node;
    }
    function renderRecordings(data, requested) {
      if (!data || data.kind !== requested.kind) throw new Error('The camera returned an unexpected recording list.');
      const entries = data.kind === 'days' ? data.days : data.files;
      if (!Array.isArray(entries) || entries.length > PAGE_SIZE || entries.some(entry => !entry || typeof entry.name !== 'string')) throw new Error('The camera returned an invalid recording list.');
      if (data.kind === 'files' && data.day !== requested.day) throw new Error('The camera returned recordings for another day.');
      const next = data.next_offset;
      if (next !== null && (!Number.isSafeInteger(next) || next <= requested.offset)) throw new Error('The camera returned an invalid page cursor.');
      view = Object.assign({}, requested, {next: next});
      el('recording-rows').replaceChildren();
      entries.forEach(entry => {
        if (data.kind === 'days') {
          const actions = validDay(entry.name) ? [button('Open day', () => loadRecordings({kind: 'files', day: entry.name, offset: 0, next: null, history: []}))] : [];
          appendRow(entry.name, '—', actions);
        } else {
          const url = downloadURL(entry.download), actions = [];
          if (url) {
            const download = doc.createElement('a'); download.className = 'button button-secondary'; download.textContent = 'Download'; download.href = url; download.setAttribute('download', entry.name); actions.push(download);
            actions.push(button('Play', () => { closePlayer(); text('player-title', entry.name); el('recording-player').setAttribute('src', url); el('player-card').hidden = false; el('recording-player').load(); }));
          }
          appendRow(recordingLabel(entry.name), bytes(entry.bytes), actions, recordingLabel(entry.name) === entry.name ? '' : entry.name);
        }
      });
      text('recording-location', view.kind === 'days' ? 'All days' : view.day);
      el('recording-day').value = view.kind === 'files' ? view.day : '';
      text('recording-summary', entries.length ? entries.length + (data.kind === 'days' ? ' day folders on this page' : ' recordings on this page') : data.kind === 'days' ? 'No days with finalized recordings were found.' : 'No finalized recordings were found for this day.');
      text('recording-page', entries.length ? 'Entries ' + (view.offset + 1) + '–' + (view.offset + entries.length) : 'No entries');
      message('recording-warning', data.scan_truncated ? 'The safety scan limit was reached. This list is incomplete; try opening a specific day.' : '');
      recordingsLoaded = true;
    }
    async function loadRecordings(requested) {
      requested = requested || Object.assign({}, view);
      if (requested.kind === 'files' && !validDay(requested.day)) { message('recording-error', 'Choose a valid recording day.'); return; }
      const ticket = ++recordingRequest;
      closePlayer(); recordingBusy = true; recordingButtons(); message('recording-error', ''); text('recording-summary', 'Loading recordings…');
      const params = new URLSearchParams({action: 'list', offset: String(requested.offset), limit: String(PAGE_SIZE)});
      if (requested.kind === 'files') params.set('day', requested.day);
      try {
        const data = await json('cgi-bin/recordings.cgi?' + params.toString());
        if (ticket !== recordingRequest) return;
        renderRecordings(data, requested);
      } catch (error) {
        if (ticket !== recordingRequest) return;
        message('recording-error', error.message || 'Recordings are unavailable.'); text('recording-summary', 'The list could not be refreshed. Any entries below are from the previous request.');
      } finally { if (ticket === recordingRequest) { recordingBusy = false; recordingButtons(); } }
    }
    function showTab(name) {
      if (!TABS.includes(name)) return;
      if (activeTab === 'recordings' && name !== 'recordings') closePlayer();
      activeTab = name;
      TABS.forEach(tab => { const selected = tab === name; el('panel-' + tab).hidden = !selected; el('tab-' + tab).className = selected ? 'tab active' : 'tab'; el('tab-' + tab).setAttribute('aria-selected', String(selected)); el('tab-' + tab).tabIndex = selected ? 0 : -1; });
      if (name === 'recordings' && !recordingsLoaded && !recordingBusy) return loadRecordings();
    }
    function initialize() {
      TABS.forEach((name, index) => {
        const tab = el('tab-' + name); tab.addEventListener('click', () => showTab(name));
        tab.addEventListener('keydown', event => { let target = null; if (event.key === 'ArrowRight') target = TABS[(index + 1) % TABS.length]; if (event.key === 'ArrowLeft') target = TABS[(index + TABS.length - 1) % TABS.length]; if (event.key === 'Home') target = TABS[0]; if (event.key === 'End') target = TABS[TABS.length - 1]; if (target) { event.preventDefault(); showTab(target); el('tab-' + target).focus(); } });
      });
      el('refresh-status').addEventListener('click', refreshStatus);
      el('refresh-recordings').addEventListener('click', () => loadRecordings());
      el('all-days').addEventListener('click', () => loadRecordings({kind: 'days', day: '', offset: 0, next: null, history: []}));
      el('recording-filter').addEventListener('submit', event => { event.preventDefault(); loadRecordings({kind: 'files', day: el('recording-day').value, offset: 0, next: null, history: []}); });
      el('recordings-next').addEventListener('click', () => { if (!recordingBusy && view.next !== null) return loadRecordings(Object.assign({}, view, {offset: view.next, next: null, history: view.history.concat(view.offset)})); });
      el('recordings-previous').addEventListener('click', () => { if (!recordingBusy && view.history.length) return loadRecordings(Object.assign({}, view, {offset: view.history[view.history.length - 1], next: null, history: view.history.slice(0, -1)})); });
      el('close-player').addEventListener('click', closePlayer);
      interval = timers.setInterval(() => { if (!doc.hidden) refreshStatus(); }, 15000);
      return refreshStatus();
    }
    return {initialize: initialize, refreshStatus: refreshStatus, renderStatus: renderStatus, showTab: showTab, loadRecordings: loadRecordings, closePlayer: closePlayer, destroy: () => { if (interval !== null) timers.clearInterval(interval); closePlayer(); }};
  }
  const api = {PAGE_SIZE: PAGE_SIZE, mib: mib, bytes: bytes, duration: duration, memoryValues: memoryValues, validDay: validDay, streamURL: streamURL, serviceURL: serviceURL, downloadURL: downloadURL, recordingLabel: recordingLabel, createApp: createApp};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && typeof root.fetch === 'function') createApp(document, root.fetch.bind(root), root).initialize();
})(typeof globalThis !== 'undefined' ? globalThis : window);
