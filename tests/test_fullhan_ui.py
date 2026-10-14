"""Fullhan browser behavior in Node with a small DOM fixture; no camera or npm."""
import shutil
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'SOURCE/src/fullhan/www/dashboard.js'
HTML = ROOT / 'SOURCE/src/fullhan/www/index.html'
NODE = shutil.which('node')

FIXTURE = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ui = require(process.argv[1]);
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.hidden = false; this.disabled = false; this.value = ''; this._text = ''; this.loads = 0; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  getAttribute(key) { return this.attributes[key] === undefined ? null : this.attributes[key]; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  async dispatch(name, extra = {}) { if (this.disabled) return; await Promise.all((this.listeners[name] || []).map(fn => fn(Object.assign({preventDefault() {}}, extra)))); await new Promise(resolve => setImmediate(resolve)); }
  pause() { this.paused = true; }
  load() { if (this.attributes.src) this.loads++; }
  focus() { this.focused = true; }
}
function fixture(queue = []) {
  const nodes = {};
  for (const [, id] of fs.readFileSync(process.argv[2], 'utf8').matchAll(/\bid="([^"]+)"/g)) nodes[id] = new Element();
  const doc = {hidden: false, getElementById: id => { assert.ok(nodes[id], 'Missing HTML id: ' + id); return nodes[id]; }, createElement: tag => new Element(tag)};
  const calls = [], intervals = [];
  const fetcher = async (url, options) => { calls.push({url, options}); assert.ok(queue.length, 'Unexpected request: ' + url); const value = queue.shift(); if (typeof value === 'function') return await value(); if (value instanceof Error) throw value; return {ok: !value.httpStatus, status: value.httpStatus || 200, json: async () => value}; };
  const timers = {setTimeout: () => 1, clearTimeout() {}, setInterval: fn => { intervals.push(fn); return 1; }, clearInterval() {}};
  return {nodes, doc, queue, calls, intervals, app: ui.createApp(doc, fetcher, timers)};
}
function status() { return {model: 'LSC SZB22705', firmware: 'FW7.6.23', ip: '192.0.2.44', backend: 'fullhan-stock', uptime_seconds: 90061, memory: {total_kB: 32768, available_kB: 8192, available_reported: true}, storage: {mounted: true, total_kB: 1048576, available_kB: 524288}, cpu: {load_1m: 1.25, load_5m: .75, load_15m: .5}, services: {stock_app: true, rtsp: true, onvif: false}, onvif: {available: false, authentication_required: true}, diagnostics: {management_rss_kB: 1024, stock_app_rss_kB: 8192}, streams: {main: 'rtsp://192.0.2.44:8554/main', sub: 'rtsp://192.0.2.44:8554/sub'}}; }
const day = '2026-10-14', filename = '20261014120000-20261014120200.mp4';
function days(values = [day], next = null) { return {kind: 'days', days: values.map(name => ({name})), offset: 0, limit: 100, next_offset: next, scan_truncated: false}; }
function files() { return {kind: 'files', day, files: [{name: filename, bytes: 1048576, download: 'recordings.cgi?action=download&day=' + day + '&file=' + filename}], offset: 0, limit: 100, next_offset: null, scan_truncated: false}; }
function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }
'''


@unittest.skipUnless(NODE, 'Node.js required for browser fixtures')
class FullhanUITests(unittest.TestCase):
    def run_js(self, body):
        result = subprocess.run([NODE, '-e', FIXTURE + '\n(async () => {\n' + body + '\n})().catch(error => { console.error(error); process.exitCode = 1; });', str(SCRIPT), str(HTML)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_memory_uses_available_and_reports_real_units(self):
        self.run_js(r'''
assert.equal(ui.mib(32768), '32.0 MiB');
assert.equal(ui.bytes(1048576), '1.0 MiB');
assert.equal(ui.bytes(NaN), 'Not reported');
assert.deepEqual(ui.memoryValues({total_kB: 32768, available_kB: 8192}), {total: 32768, available: 8192, used: 24576, percent: 75});
assert.equal(ui.memoryValues({total_kB: 0, available_kB: 1}), null);
assert.equal(ui.memoryValues({total_kB: 32, available_kB: '8'}), null);
assert.equal(ui.memoryValues({total_kB: 32, available_kB: 64}).used, 0);
assert.equal(ui.duration(90061), '1d 1h 1m');
''')

    def test_links_reject_external_schemes_traversal_and_invalid_dates(self):
        self.run_js(r'''
assert.equal(ui.streamURL('javascript:alert(1)', '192.0.2.44', 'main'), null);
assert.equal(ui.streamURL('rtsp://evil.example:8554/main', '192.0.2.44', 'main'), null);
assert.equal(ui.streamURL('rtsp://192.0.2.44:8554/main', '192.0.2.44', 'main'), 'rtsp://192.0.2.44:8554/main');
assert.equal(ui.serviceURL('http://evil.example:5000/', '192.0.2.44'), null);
assert.equal(ui.validDay('2026-02-29'), false);
assert.equal(ui.validDay('2024-02-29'), true);
const good = files().files[0].download;
assert.equal(ui.downloadURL(good), 'cgi-bin/' + good);
for (const bad of ['https://evil.example/' + good, '//evil.example/' + good, 'javascript:alert(1)', good + '&file=extra', good.replace(filename, '..%2Fprivate.db'), good.replace(day, '2026-02-31'), good.replace('action=download', 'action=delete'), good + '#secret']) assert.equal(ui.downloadURL(bad), null, bad);
''')

    def test_status_renders_literal_text_units_services_and_missing_fields(self):
        self.run_js(r'''
const f = fixture(), data = status(); data.model = '<img src=x onerror=alert(1)>';
f.app.renderStatus(data);
assert.equal(f.nodes.model.textContent, data.model);
assert.equal(f.nodes.model.children.length, 0);
assert.equal(f.nodes['ram-used'].textContent, '24.0 MiB');
assert.equal(f.nodes.memory.textContent, 'Available: 8.0 MiB of 32.0 MiB');
assert.equal(f.nodes['ram-meter'].value, 75);
assert.equal(f.nodes['storage-used'].textContent, '512.0 MiB');
assert.equal(f.nodes['cpu-load'].textContent, '1.25');
assert.equal(f.nodes['service-stock'].textContent, 'Running');
assert.equal(f.nodes['service-onvif'].textContent, 'Not available');
assert.equal(f.nodes['onvif-url'].hidden, true);
data.onvif = {available: true, url: 'http://192.0.2.44:5000/', discovery_running: false}; data.services.onvif = true;
f.app.renderStatus(data);
assert.equal(f.nodes['onvif-url'].getAttribute('href'), data.onvif.url);
assert.equal(f.nodes['onvif-url'].hidden, false);
assert.match(f.nodes['onvif-note'].textContent, /Add the address below manually/);
assert.match(f.nodes['onvif-note'].textContent, /Discovery for this service is disabled/);
data.onvif.discovery_running = true; f.app.renderStatus(data);
assert.match(f.nodes['onvif-note'].textContent, /optional discovery helper is running/);
assert.doesNotMatch(f.nodes['onvif-note'].textContent, /service is disabled/);
delete data.storage; delete data.cpu; delete data.diagnostics; f.app.renderStatus(data);
assert.equal(f.nodes['storage-used'].textContent, 'Not reported');
assert.equal(f.nodes['management-rss'].textContent, 'Not reported');
''')

    def test_initial_load_fetches_only_status_and_hidden_page_does_not_poll(self):
        self.run_js(r'''
const f = fixture([status()]); await f.app.initialize();
assert.deepEqual(f.calls.map(call => call.url), ['cgi-bin/status.cgi']);
assert.equal(f.calls[0].options.credentials, 'same-origin');
assert.equal(f.nodes['recording-player'].loads, 0);
f.doc.hidden = true; f.intervals[0]();
assert.equal(f.calls.length, 1);
await f.app.showTab('streams');
assert.equal(f.calls.length, 1);
assert.equal(f.nodes['panel-streams'].hidden, false);
assert.equal(f.nodes['panel-dashboard'].hidden, true);
f.app.destroy();
''')

    def test_day_filter_uses_bounded_api_and_open_day(self):
        self.run_js(r'''
const f = fixture([status(), days(), files()]); await f.app.initialize(); await f.app.showTab('recordings');
assert.equal(f.calls.length, 2);
const list = new URL(f.calls[1].url, 'http://camera/');
assert.equal(list.searchParams.get('limit'), '100'); assert.equal(list.searchParams.has('day'), false);
const open = descendants(f.nodes['recording-rows']).find(node => node.tagName === 'button');
await open.dispatch('click');
assert.equal(new URL(f.calls[2].url, 'http://camera/').searchParams.get('day'), day);
assert.equal(f.nodes['recording-location'].textContent, day);
assert.equal(f.nodes['recording-player'].getAttribute('src'), null);
assert.equal(f.nodes['recording-player'].loads, 0);
assert.equal(f.calls.length, 3);
''')

    def test_recording_play_requires_user_action_and_close_releases_media(self):
        self.run_js(r'''
const f = fixture([status(), days(), files()]); await f.app.initialize(); await f.app.showTab('recordings');
await f.app.loadRecordings({kind: 'files', day, offset: 0, next: null, history: []});
const actions = descendants(f.nodes['recording-rows']);
const download = actions.find(node => node.tagName === 'a');
assert.equal(download.href, 'cgi-bin/' + files().files[0].download);
assert.equal(download.getAttribute('download'), filename);
assert.equal(f.nodes['recording-player'].loads, 0);
await actions.find(node => node.textContent === 'Play').dispatch('click');
assert.equal(f.nodes['recording-player'].getAttribute('src'), download.href);
assert.equal(f.nodes['recording-player'].loads, 1);
assert.equal(f.nodes['player-card'].hidden, false);
await f.app.showTab('dashboard');
assert.equal(f.nodes['player-card'].hidden, true);
assert.equal(f.nodes['recording-player'].getAttribute('src'), null);
assert.equal(f.calls.length, 3);
''')

    def test_recording_pagination_returns_to_previous_cursor(self):
        self.run_js(r'''
const f = fixture([status(), days([day], 100), days(['2026-10-13']), days([day], 100)]);
await f.app.initialize(); await f.app.showTab('recordings');
assert.equal(f.nodes['recordings-next'].disabled, false);
await f.nodes['recordings-next'].dispatch('click');
assert.equal(new URL(f.calls[2].url, 'http://camera/').searchParams.get('offset'), '100');
assert.equal(f.nodes['recordings-previous'].disabled, false);
await f.nodes['recordings-previous'].dispatch('click');
assert.equal(new URL(f.calls[3].url, 'http://camera/').searchParams.get('offset'), '0');
assert.equal(f.nodes['recordings-previous'].disabled, true);
''')

    def test_latest_recording_request_wins_and_truncated_inventory_is_visible(self):
        self.run_js(r'''
let release;
const delayed = new Promise(resolve => release = resolve);
const latest = files(); latest.scan_truncated = true;
const f = fixture([() => delayed, latest]);
const old = f.app.loadRecordings({kind: 'days', day: '', offset: 0, next: null, history: []});
await f.app.loadRecordings({kind: 'files', day, offset: 0, next: null, history: []});
release({ok: true, status: 200, json: async () => days()}); await old;
assert.equal(f.nodes['recording-location'].textContent, day);
assert.equal(f.nodes['recording-warning'].hidden, false);
assert.match(f.nodes['recording-warning'].textContent, /incomplete/);
''')

    def test_auth_failure_bad_cursor_and_oversized_page_show_actionable_errors(self):
        self.run_js(r'''
const f = fixture([{httpStatus: 401}, days([day], 0), days(Array(101).fill(day))]);
await f.app.refreshStatus(); assert.match(f.nodes.error.textContent, /Authentication required/);
await f.app.loadRecordings(); assert.match(f.nodes['recording-error'].textContent, /page cursor/);
await f.app.loadRecordings(); assert.match(f.nodes['recording-error'].textContent, /invalid recording list/);
assert.equal(f.nodes['recording-rows'].children.length, 0);
assert.equal(f.nodes['recording-player'].loads, 0);
''')

    def test_untrusted_recording_names_are_text_and_bad_download_has_no_action(self):
        self.run_js(r'''
const data = files(); data.files[0].name = '<script>alert(1)</script>'; data.files[0].download = 'javascript:alert(1)';
const f = fixture([data]); await f.app.loadRecordings({kind: 'files', day, offset: 0, next: null, history: []});
assert.match(f.nodes['recording-rows'].textContent, /<script>/);
assert.equal(descendants(f.nodes['recording-rows']).some(node => node.tagName === 'a' || node.tagName === 'button'), false);
''')


if __name__ == '__main__':
    unittest.main()
