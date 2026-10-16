'use strict';
(function (root) {
  const TABS = ['dashboard', 'streams', 'recordings', 'diagnostics'];
  function number(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER ? value : null; }
  function mib(value) { return number(value) === null ? 'Not reported' : (value / 1024).toFixed(1) + ' MiB'; }
  function duration(value) {
    if (number(value) === null) return 'Not reported';
    const days = Math.floor(value / 86400), hours = Math.floor(value % 86400 / 3600), minutes = Math.floor(value % 3600 / 60);
    return days ? days + 'd ' + hours + 'h' : hours ? hours + 'h ' + minutes + 'm' : minutes ? minutes + 'm' : Math.floor(value) + 's';
  }
  function memoryValues(value) {
    const total = number(value && value.total_kB), available = number(value && value.available_kB);
    if (total === null || total === 0 || available === null) return null;
    const bounded = Math.min(total, available);
    return {total: total, available: bounded, used: total - bounded, percent: (total - bounded) * 100 / total};
  }
  function ipv4(value) {
    if (typeof value !== 'string' || !/^\d{1,3}(\.\d{1,3}){3}$/.test(value)) return false;
    const parts = value.split('.').map(Number);
    return parts.every(part => part <= 255) && parts[0] > 0 && parts[0] !== 127 && parts[0] < 224;
  }
  function streamURL(value, ip, profile) {
    if (!ipv4(ip) || !['stream0', 'stream1'].includes(profile) || typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'rtsp:' && url.hostname === ip && url.port === '8554' && url.pathname === '/' + profile && !url.username && !url.password && !url.search && !url.hash ? url.href : null;
    } catch (_) { return null; }
  }
  function serviceURL(value, ip) {
    if (!ipv4(ip) || typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'http:' && url.hostname === ip && url.port === '5000' && url.pathname === '/onvif/device_service' && !url.username && !url.password && !url.search && !url.hash ? url.href : null;
    } catch (_) { return null; }
  }
  function recordingURL(value, day, session, file) {
    if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day) || typeof session !== 'string' || !/^\d{10}_\d{4}$/.test(session) || typeof file !== 'string' || !/^(?:\d{4}\.media|\.info)$/.test(file)) return null;
    const expected = 'recordings.cgi?action=download&day=' + day + '&session=' + session + '&file=' + file;
    return value === expected ? 'cgi-bin/' + expected : null;
  }
  function recordingPage(data, day, session, offset) {
    const kind = session ? 'segments' : day ? 'sessions' : 'days', key = session ? 'files' : day ? 'sessions' : 'days';
    if (!data || data.kind !== kind || !Array.isArray(data[key]) || data[key].length > 100 || data.offset !== offset || data.limit !== 100 || typeof data.scan_truncated !== 'boolean' || data.ranges_supported !== false || (data.next_offset !== null && data.next_offset !== offset + 100) || (day && data.day !== day) || (session && data.session !== session)) throw new Error('Invalid recording index.');
    data[key].forEach(entry => {
      if (kind === 'days') { if (typeof entry !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(entry)) throw new Error('Invalid recording day.'); }
      else if (kind === 'sessions') {
        if (!entry || typeof entry.session !== 'string' || !/^\d{10}_\d{4}$/.test(entry.session) || number(entry.start_epoch) === null || number(entry.duration_seconds) === null || entry.start_epoch !== Number(entry.session.slice(0, 10)) || entry.duration_seconds !== Number(entry.session.slice(11)) || (entry.info_download !== null && !recordingURL(entry.info_download, day, entry.session, '.info'))) throw new Error('Invalid recording session.');
      } else if (!entry || !/^\d{4}\.media$/.test(entry.name) || number(entry.bytes) === null || entry.bytes === 0 || !recordingURL(entry.download, day, session, entry.name)) throw new Error('Invalid recording segment.');
    });
    return {kind: kind, entries: data[key], next: data.next_offset, truncated: data.scan_truncated};
  }
  function createApp(doc, fetcher, timers) {
    timers = timers || root;
    const el = id => doc.getElementById(id), text = (id, value) => { el(id).textContent = value; };
    let busy = false, interval = null;
    let recordingsBusy = false, recordingsLoaded = false, recordingDay = '', recordingSession = '', recordingOffset = 0, recordingNext = null;
    function link(id, value) { text(id, value || 'Candidate address unavailable'); if (value) el(id).setAttribute('href', value); else el(id).removeAttribute('href'); }
    function meter(id, value) { el(id).hidden = value === null; el(id).value = value === null ? 0 : value; }
    function renderStatus(status) {
      if (!status || status.backend !== 'yyos-stock' || !status.memory || !status.streams) throw new Error('Incomplete camera status.');
      for (const field of ['model', 'firmware', 'ip', 'backend']) text(field, typeof status[field] === 'string' ? status[field] : 'Not reported');
      text('uptime', duration(status.uptime_seconds));
      const memory = memoryValues(status.memory), storage = status.storage || {}, disk = storage.mounted === true ? memoryValues({total_kB: storage.total_kB, available_kB: storage.available_kB}) : null;
      text('ram-used', memory ? mib(memory.used) : 'Not reported');
      text('memory', memory ? 'Available: ' + mib(memory.available) + ' of ' + mib(memory.total) : 'Available RAM: not reported');
      text('ram-total', memory ? mib(memory.total) : 'Not reported'); text('ram-available', memory ? mib(memory.available) : 'Not reported');
      text('ram-note', status.memory.available_reported === false ? 'Available RAM is estimated; cache is reclaimable.' : 'Uses the kernel’s available-memory estimate.');
      meter('ram-meter', memory ? memory.percent : null);
      text('storage-used', disk ? mib(disk.used) : 'Not available'); text('storage-available', disk ? 'Available: ' + mib(disk.available) + ' of ' + mib(disk.total) : 'Available space: not reported');
      meter('storage-meter', disk ? disk.percent : null);
      const cpu = status.cpu || {}, loads = [cpu.load_1m, cpu.load_5m, cpu.load_15m].map(value => number(value) === null ? '—' : value.toFixed(2));
      text('cpu-load', loads[0]); text('cpu-loads', loads.join(' / '));
      const services = status.services || {}, diagnostics = status.diagnostics || {};
      text('service-stock', services.stock_app === true ? 'Observed running' : 'Not observed');
      text('service-management', services.management === true ? 'Owned HTTP running' : 'Not observed');
      text('service-rtsp', services.native_rtsp_listening === true ? 'Listening; operation unverified' : 'No listener observed');
      text('service-onvif', services.native_onvif_listening === true ? 'Listening; operation unverified' : 'No listener observed');
      text('management-rss', mib(diagnostics.management_rss_kB)); text('stock-rss', mib(diagnostics.stock_app_rss_kB));
      link('main', streamURL(status.streams.main_candidate, status.ip, 'stream0')); link('sub', streamURL(status.streams.sub_candidate, status.ip, 'stream1'));
      link('onvif-url', serviceURL(status.onvif && status.onvif.candidate_url, status.ip));
    }
    async function refreshStatus() {
      if (busy) return;
      busy = true; el('refresh-status').disabled = true;
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const deadline = controller ? timers.setTimeout(() => controller.abort(), 15000) : null;
      try {
        const response = await fetcher('cgi-bin/status.cgi', {cache: 'no-store', credentials: 'same-origin', signal: controller ? controller.signal : undefined});
        if (!response.ok) throw new Error(response.status === 401 ? 'Authentication required. Reload to sign in.' : 'Status request failed (' + response.status + ').');
        renderStatus(await response.json());
        text('error', ''); el('error').hidden = true; text('connection', 'Connected'); el('connection').className = 'status-badge online'; text('last-updated', 'Updated ' + new Date().toLocaleTimeString());
      } catch (error) {
        text('error', error.name === 'AbortError' ? 'The status request timed out.' : error.message); el('error').hidden = false; text('connection', 'Status unavailable'); el('connection').className = 'status-badge offline'; text('last-updated', 'Status may be out of date');
      } finally { if (deadline !== null) timers.clearTimeout(deadline); busy = false; el('refresh-status').disabled = false; }
    }
    function recordingLink(label, url) {
      const anchor = doc.createElement('a'); anchor.textContent = label; anchor.className = 'button button-secondary'; anchor.setAttribute('href', url); anchor.setAttribute('download', ''); return anchor;
    }
    async function loadRecordings(day, session, offset) {
      if (recordingsBusy) return;
      recordingsBusy = true;
      ['refresh-recordings', 'recordings-up', 'recordings-root', 'recordings-previous', 'recordings-next'].forEach(id => { el(id).disabled = true; });
      text('recordings-state', 'Loading recordings…'); el('recordings-error').hidden = true;
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const deadline = controller ? timers.setTimeout(() => controller.abort(), 15000) : null;
      try {
        const query = new URLSearchParams({action: 'list', limit: '100', offset: String(offset)});
        if (day) query.set('day', day); if (session) query.set('session', session);
        const response = await fetcher('cgi-bin/recordings.cgi?' + query, {cache: 'no-store', credentials: 'same-origin', signal: controller ? controller.signal : undefined});
        if (!response.ok) throw new Error(response.status === 401 ? 'Authentication required. Reload to sign in.' : 'Recording request failed (' + response.status + ').');
        const page = recordingPage(await response.json(), day, session, offset);
        recordingDay = day; recordingSession = session; recordingOffset = offset; recordingNext = page.next; recordingsLoaded = true;
        const list = el('recordings-list'); list.replaceChildren();
        page.entries.forEach(entry => {
          const row = doc.createElement('li'), label = doc.createElement('div'), actions = doc.createElement('div'); label.className = 'recording-label'; actions.className = 'row-actions';
          if (page.kind === 'days') {
            label.textContent = entry;
            const button = doc.createElement('button'); button.type = 'button'; button.className = 'button button-secondary'; button.textContent = 'Open day'; button.addEventListener('click', () => loadRecordings(entry, '', 0)); actions.appendChild(button);
          } else if (page.kind === 'sessions') {
            label.textContent = entry.session;
            const detail = doc.createElement('small'); detail.textContent = new Date(entry.start_epoch * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC') + ' · ' + entry.duration_seconds + ' seconds'; label.appendChild(detail);
            const button = doc.createElement('button'); button.type = 'button'; button.className = 'button button-secondary'; button.textContent = 'Open session'; button.addEventListener('click', () => loadRecordings(day, entry.session, 0)); actions.appendChild(button);
            if (entry.info_download) actions.appendChild(recordingLink('Download private .info', recordingURL(entry.info_download, day, entry.session, '.info')));
          } else { label.textContent = entry.name + ' · ' + mib(entry.bytes / 1024); actions.appendChild(recordingLink('Download raw segment', recordingURL(entry.download, day, session, entry.name))); }
          row.appendChild(label); row.appendChild(actions); list.appendChild(row);
        });
        text('recordings-heading', session ? 'Raw recording segments' : day ? 'Recording sessions' : 'Recording days');
        text('recordings-context', session ? day + ' / ' + session : day || 'Open a day, then a session.');
        text('recordings-state', (page.entries.length ? '' : 'No entries on this page. ') + (page.truncated ? 'The scan limit was reached; this index is incomplete.' : 'Read-only index.'));
        text('recordings-page', page.entries.length ? 'Entries ' + (offset + 1) + '–' + (offset + page.entries.length) : 'No entries');
      } catch (error) { text('recordings-error', error.name === 'AbortError' ? 'The recording request timed out.' : error.message); el('recordings-error').hidden = false; text('recordings-state', 'Recording index unavailable.'); }
      finally {
        if (deadline !== null) timers.clearTimeout(deadline); recordingsBusy = false; el('refresh-recordings').disabled = false;
        el('recordings-up').hidden = !recordingDay; el('recordings-root').hidden = !recordingSession; text('recordings-up', recordingSession ? 'Back to sessions' : 'Back to days');
        el('recordings-up').disabled = false; el('recordings-root').disabled = false;
        el('recordings-previous').disabled = recordingOffset === 0; el('recordings-next').disabled = recordingNext === null;
      }
    }
    function showTab(name) {
      if (!TABS.includes(name)) return;
      if (name === 'recordings' && !recordingsLoaded) loadRecordings('', '', 0);
      TABS.forEach(tab => { const selected = tab === name; el('panel-' + tab).hidden = !selected; el('tab-' + tab).className = selected ? 'tab active' : 'tab'; el('tab-' + tab).setAttribute('aria-selected', String(selected)); el('tab-' + tab).tabIndex = selected ? 0 : -1; });
    }
    function initialize() {
      TABS.forEach((name, index) => {
        el('tab-' + name).addEventListener('click', () => showTab(name));
        el('tab-' + name).addEventListener('keydown', event => {
          const next = event.key === 'ArrowRight' ? TABS[(index + 1) % TABS.length] : event.key === 'ArrowLeft' ? TABS[(index + TABS.length - 1) % TABS.length] : event.key === 'Home' ? TABS[0] : event.key === 'End' ? TABS[TABS.length - 1] : null;
          if (next) { event.preventDefault(); showTab(next); el('tab-' + next).focus(); }
        });
      });
      el('refresh-status').addEventListener('click', refreshStatus);
      el('refresh-recordings').addEventListener('click', () => loadRecordings(recordingDay, recordingSession, recordingOffset));
      el('recordings-root').addEventListener('click', () => loadRecordings('', '', 0));
      el('recordings-up').addEventListener('click', () => loadRecordings(recordingSession ? recordingDay : '', '', 0));
      el('recordings-previous').addEventListener('click', () => loadRecordings(recordingDay, recordingSession, Math.max(0, recordingOffset - 100)));
      el('recordings-next').addEventListener('click', () => { if (recordingNext !== null) loadRecordings(recordingDay, recordingSession, recordingNext); });
      interval = timers.setInterval(() => { if (!doc.hidden) refreshStatus(); }, 15000);
      return refreshStatus();
    }
    return {initialize: initialize, refreshStatus: refreshStatus, renderStatus: renderStatus, showTab: showTab, loadRecordings: loadRecordings, destroy: () => { if (interval !== null) timers.clearInterval(interval); }};
  }
  const api = {mib: mib, memoryValues: memoryValues, streamURL: streamURL, serviceURL: serviceURL, recordingURL: recordingURL, recordingPage: recordingPage, createApp: createApp};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && typeof root.fetch === 'function') createApp(document, root.fetch.bind(root), root).initialize();
})(typeof globalThis !== 'undefined' ? globalThis : window);
