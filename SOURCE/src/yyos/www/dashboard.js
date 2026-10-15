'use strict';
(function (root) {
  const TABS = ['dashboard', 'streams', 'diagnostics'];
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
  function createApp(doc, fetcher, timers) {
    timers = timers || root;
    const el = id => doc.getElementById(id), text = (id, value) => { el(id).textContent = value; };
    let busy = false, interval = null;
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
    function showTab(name) {
      if (!TABS.includes(name)) return;
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
      interval = timers.setInterval(() => { if (!doc.hidden) refreshStatus(); }, 15000);
      return refreshStatus();
    }
    return {initialize: initialize, refreshStatus: refreshStatus, renderStatus: renderStatus, showTab: showTab, destroy: () => { if (interval !== null) timers.clearInterval(interval); }};
  }
  const api = {mib: mib, memoryValues: memoryValues, streamURL: streamURL, serviceURL: serviceURL, createApp: createApp};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && typeof root.fetch === 'function') createApp(document, root.fetch.bind(root), root).initialize();
})(typeof globalThis !== 'undefined' ? globalThis : window);
