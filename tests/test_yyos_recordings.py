"""Read-only recording fixtures use synthetic directories/bytes, never camera data."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'SOURCE/src/contrib/yyos-recordings/yyos_recordings.c'
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', os.environ.get('QEMU_ARM', 'qemu-arm')))
ARM_CC = shutil.which(os.environ.get('ARM_CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))
HOST_CC = shutil.which(os.environ.get('CC', 'cc'))
SESSION = '1791979200_0300'
DATA = bytes(range(256)) * 300
INFO = b'PRIVATE-ENCRYPTION-METADATA-DO-NOT-DISPLAY'


class RecordingCases:
    arm = False

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='yyos-recordings-')
        cls.fixture = Path(cls.temporary.name)
        cls.card = cls.fixture / 'card'
        cls.dcim = cls.card / 'DCIM/CHAN0'
        cls.binary = cls.fixture / 'yyos-recordings'
        command = [ARM_CC if cls.arm else HOST_CC, '-std=c99', '-Os', '-Wall', '-Wextra', '-Werror',
                   '-DYYOS_RECORDINGS_FIXTURE_ROOT=' + json.dumps(str(cls.dcim))]
        if cls.arm:
            command += ['-static', '-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
        subprocess.run(command + [str(SOURCE), '-o', str(cls.binary)], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        if self.card.is_symlink():
            self.card.unlink()
        elif self.card.exists():
            shutil.rmtree(self.card)
        self.day = self.dcim / '2026/10/14'
        self.session = self.day / SESSION
        self.session.mkdir(parents=True)
        (self.session / '0001.media').write_bytes(DATA)
        (self.session / '.info').write_bytes(INFO)
        self.private = self.fixture / 'private-config'
        self.private.write_bytes(b'PRIVATE-CONFIG-DO-NOT-EXPOSE')

    def call(self, query='', method='GET', byte_range=None, user='fixture-user', host='camera.local:8080'):
        env = {'PATH': '/nonexistent', 'REQUEST_METHOD': method, 'QUERY_STRING': query}
        if user is not None:
            env['REMOTE_USER'] = user
        if host is not None:
            env['HTTP_HOST'] = host
        if byte_range is not None:
            env['HTTP_RANGE'] = byte_range
        command = ([QEMU, '-cpu', 'arm926'] if self.arm else []) + [str(self.binary)]
        result = subprocess.run(command, env=env, capture_output=True, timeout=10)
        headers, body = result.stdout.split(b'\r\n\r\n', 1)
        header = dict(line.decode().split(': ', 1) for line in headers.split(b'\r\n'))
        return result, header, body

    def sessions(self, **extra):
        return self.call(urlencode({'day': '2026-10-14', **extra}))

    def segments(self, **extra):
        return self.call(urlencode({'day': '2026-10-14', 'session': SESSION, **extra}))

    def download(self, file='0001.media', **options):
        return self.call(urlencode({'action': 'download', 'day': '2026-10-14', 'session': SESSION, 'file': file}), **options)

    def assert_error(self, response, status):
        result, headers, body = response
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(headers['Status'].startswith(str(status)), response)
        if body:
            self.assertEqual(set(json.loads(body)), {'error'})
        self.assertNotIn(b'PRIVATE-CONFIG', result.stdout)
        self.assertNotIn(INFO, result.stdout)
        self.assertNotIn(str(self.fixture).encode(), result.stdout)

    def test_days_sessions_segments_contract_excludes_metadata_contents(self):
        (self.day / 'day_idx.bin').write_bytes(INFO)
        (self.dcim / 'session.log').write_bytes(INFO)
        (self.session / 'other.media').write_bytes(INFO)
        (self.session / '0002.media').write_bytes(b'')
        for call, kind in [(self.call, 'days'), (self.sessions, 'sessions'), (self.segments, 'segments')]:
            result, _, body = call()
            self.assertEqual(result.returncode, 0)
            value = json.loads(body)
            self.assertEqual(value['kind'], kind)
            self.assertFalse(value['ranges_supported'])
            self.assertFalse(value['scan_truncated'])
            self.assertNotIn(INFO, body)
            self.assertIsNone(value['next_offset'])
        self.assertEqual(json.loads(self.call()[2])['days'], ['2026-10-14'])
        session = json.loads(self.sessions()[2])['sessions'][0]
        self.assertEqual(session, {'session': SESSION, 'start_epoch': 1791979200, 'duration_seconds': 300,
                                  'info_download': 'recordings.cgi?action=download&day=2026-10-14&session=' + SESSION + '&file=.info'})
        self.assertEqual(json.loads(self.segments()[2])['files'], [{'name': '0001.media', 'bytes': len(DATA),
                         'download': 'recordings.cgi?action=download&day=2026-10-14&session=' + SESSION + '&file=0001.media'}])

    def test_raw_and_info_download_exact_bytes_and_headers(self):
        for file, expected in [('0001.media', DATA), ('.info', INFO)]:
            result, headers, body = self.download(file)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(body, expected)
            self.assertEqual(headers['Content-Type'], 'application/octet-stream')
            self.assertEqual(headers['Content-Length'], str(len(expected)))
            self.assertEqual(headers['Accept-Ranges'], 'none')
            self.assertEqual(headers['Content-Disposition'], 'attachment; filename="' + file + '"')

    def test_head_has_headers_without_file_or_inventory_body(self):
        for call in [lambda: self.download(method='HEAD'), lambda: self.call(method='HEAD'),
                     lambda: self.call('day=2026-10-14', method='HEAD')]:
            result, headers, body = call()
            self.assertEqual(result.returncode, 0)
            self.assertTrue(headers['Status'].startswith('200'))
            self.assertEqual(body, b'')

    def test_authentication_and_method_before_storage(self):
        for user in [None, '', 'x' * 33]:
            self.assert_error(self.download(user=user), 401)
        for method in ['POST', 'DELETE', 'PUT', 'OPTIONS', '']:
            self.assert_error(self.call(method=method), 405)
        self.assert_error(self.download('.info', user=None), 401)

    def test_host_header_strict_guard(self):
        for host in [None, '', 'evil/path', 'x\r\nHeader:x', 'user@host', 'x:0', 'x:65536', '[::1]', 'x..local', '-x.local', 'x:80:81', '999.1.2.3', '1.2.3']:
            self.assert_error(self.call(host=host), 400)
        self.assertEqual(self.call(host='192.168.88.17:8080')[0].returncode, 0)

    def test_ranges_explicitly_refused_and_never_partial_download(self):
        for value in ['bytes=0-31', 'bytes=-4', 'garbage']:
            self.assert_error(self.download(byte_range=value), 416)

    def test_query_allowlist_duplicates_size_and_percent_decoding(self):
        for query in ['cmd=x', 'day=2026-10-14&day=2026-10-14', 'action=list&action=list',
                      'limit=0', 'limit=101', 'offset=4097', 'offset=-1', 'limit=1x',
                      'day=%00', 'day=%', 'action=download', 'session=' + SESSION,
                      'file=0001.media', 'action=list&file=0001.media', 'action=list&',
                      'action=' + 'x' * 4096]:
            self.assert_error(self.call(query), 400)
        self.assertEqual(self.call('day=2026%2D10%2D14')[0].returncode, 0)

    def test_traversal_backup_config_and_noncanonical_names_refused(self):
        for key, values in {'day': ['../config', '2026-02-30', '2026/10/14'],
                            'session': ['../..', '1791979200_300', SESSION + '/x', 'x' * 15],
                            'file': ['../../param.conf', 'day_idx.bin', '001.media', '0001.media/x', '.info%00']}.items():
            for value in values:
                query = {'action': 'download', 'day': '2026-10-14', 'session': SESSION, 'file': '0001.media'}
                query[key] = value
                self.assert_error(self.call(urlencode(query)), 400)

    def test_missing_recording_paths(self):
        self.assert_error(self.call('day=2026-10-13'), 404)
        self.assert_error(self.call('day=2026-10-14&session=1791979201_0300'), 404)
        self.assert_error(self.download('9999.media'), 404)

    def test_root_and_each_directory_symlink_refused(self):
        for path in [self.card, self.dcim, self.dcim / '2026', self.dcim / '2026/10', self.day, self.session]:
            target = self.fixture / ('saved-' + path.name)
            path.rename(target)
            path.symlink_to(target, target_is_directory=True)
            try:
                result = self.download()
                self.assert_error(result, 403)
            finally:
                path.unlink(); target.rename(path)

    def test_file_symlink_hardlink_fifo_and_zero_size_excluded(self):
        file = self.session / '0001.media'
        for kind in ['symlink', 'hardlink', 'fifo', 'empty']:
            file.unlink()
            if kind == 'symlink': file.symlink_to(self.private)
            elif kind == 'hardlink': os.link(self.private, file)
            elif kind == 'fifo': os.mkfifo(file)
            else: file.touch()
            self.assert_error(self.download(), 404)
            self.assertEqual(json.loads(self.segments()[2])['files'], [])
        (self.session / '.info').unlink()
        (self.session / '.info').symlink_to(self.private)
        self.assert_error(self.download('.info'), 404)
        self.assertIsNone(json.loads(self.sessions()[2])['sessions'][0]['info_download'])

    def test_info_size_bound(self):
        (self.session / '.info').write_bytes(b'x' * 65537)
        self.assert_error(self.download('.info'), 404)
        self.assertIsNone(json.loads(self.sessions()[2])['sessions'][0]['info_download'])

    def test_segment_and_session_pagination_order_and_empty_offset(self):
        for index in range(105):
            (self.session / ('%04d.media' % index)).write_bytes(b'raw')
            (self.day / ('%010d_0300' % (1791979300 + index))).mkdir()
        for call, key, name in [(self.segments, 'files', 'name'), (self.sessions, 'sessions', 'session')]:
            a, b = json.loads(call(limit=100)[2]), json.loads(call(offset=100)[2])
            self.assertEqual(a['next_offset'], 100)
            self.assertIsNone(b['next_offset'])
            entries = a[key] + b[key]
            self.assertEqual([entry[name] for entry in entries], sorted([entry[name] for entry in entries], reverse=True))
            self.assertEqual(json.loads(call(offset=4096)[2])[key], [])

    def test_segment_count_cap_explicit(self):
        for index in range(4097):
            (self.session / ('%04d.media' % index)).write_bytes(b'raw')
        value = json.loads(self.segments(offset=4000)[2])
        self.assertEqual(len(value['files']), 96)
        self.assertTrue(value['scan_truncated'])
        self.assertIsNone(value['next_offset'])

    def test_scan_budget_explicit(self):
        for index in range(8200):
            (self.dcim / ('ignored-' + str(index))).touch()
        value = json.loads(self.call()[2])
        self.assertTrue(value['scan_truncated'])
        self.assertLess(len(json.dumps(value)), 16384)

    def test_day_calendar_and_cap(self):
        (self.dcim / '2026/02/30').mkdir(parents=True)
        (self.dcim / '2024/02/29').mkdir(parents=True)
        value = json.loads(self.call()[2])
        self.assertEqual(value['days'], ['2026-10-14', '2024-02-29'])
        start = datetime.date(2021, 1, 1)
        for index in range(1025):
            (self.dcim / (start + datetime.timedelta(days=index)).strftime('%Y/%m/%d')).mkdir(parents=True, exist_ok=True)
        value = json.loads(self.call('offset=1000')[2])
        self.assertEqual(len(value['days']), 24)
        self.assertTrue(value['scan_truncated'])


@unittest.skipUnless(HOST_CC, 'Host C compiler required')
class HostRecordingTests(RecordingCases, unittest.TestCase):
    pass


@unittest.skipUnless(QEMU and ARM_CC, 'ARM compiler and qemu-arm required')
class ArmRecordingTests(RecordingCases, unittest.TestCase):
    arm = True


@unittest.skipUnless(shutil.which('node'), 'Node.js required for frontend fixtures')
class RecordingFrontendTests(unittest.TestCase):
    def node(self, program):
        result = subprocess.run(['node', '-e', program, str(REPO / 'SOURCE/src/yyos/www/dashboard.js')], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_download_url_identity_and_page_schema_refuse_untrusted_links(self):
        self.node(r"""
const assert=require('assert'), api=require(process.argv[1]);
const day='2026-10-14', session='1791979200_0300';
const u='recordings.cgi?action=download&day='+day+'&session='+session+'&file=0001.media';
assert.equal(api.recordingURL(u,day,session,'0001.media'),'cgi-bin/'+u);
for(const bad of ['https://evil/'+u,'javascript:alert(1)',u+'&key=private',u.replace('0001','0002')])assert.equal(api.recordingURL(bad,day,session,'0001.media'),null);
const page={kind:'segments',day,session,files:[{name:'0001.media',bytes:100,download:u}],offset:0,limit:100,next_offset:null,scan_truncated:false,ranges_supported:false};
assert.equal(api.recordingPage(page,day,session,0).entries.length,1);
for(const patch of [{files:[{name:'../config',bytes:100,download:u}]},{files:[{name:'0001.media',bytes:0,download:u}]},{next_offset:1},{ranges_supported:true},{limit:101},{session:'other'}])assert.throws(()=>api.recordingPage({...page,...patch},day,session,0));
""")

    def test_lazy_read_only_navigation_raw_links_and_private_info_not_loaded(self):
        self.node(r"""
const assert=require('assert'), api=require(process.argv[1]);
function element(){return {textContent:'',hidden:false,disabled:false,children:[],attrs:{},events:{},appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},addEventListener(k,v){this.events[k]=v},set innerHTML(v){throw Error('HTML rendering forbidden')}}}
const els={},doc={getElementById(id){return els[id]||(els[id]=element())},createElement:element};
const day='2026-10-14',session='1791979200_0300',base='recordings.cgi?action=download&day='+day+'&session='+session+'&file=';
const pages=[{kind:'days',days:[day]},{kind:'sessions',day,sessions:[{session,start_epoch:1791979200,duration_seconds:300,info_download:base+'.info'}]},{kind:'segments',day,session,files:[{name:'0001.media',bytes:4096,download:base+'0001.media'}]}];
const calls=[],timers={setTimeout(){return 1},clearTimeout(){}};
const app=api.createApp(doc,async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>({...pages.shift(),offset:0,limit:100,next_offset:null,scan_truncated:false,ranges_supported:false})}},timers);
assert.equal(calls.length,0);
(async()=>{
await app.loadRecordings('','',0);assert.equal(els['recordings-list'].children.length,1);
await app.loadRecordings(day,'',0);let row=els['recordings-list'].children[0];assert.equal(row.children[1].children[1].attrs.href,'cgi-bin/'+base+'.info');assert.match(row.children[1].children[1].textContent,/private/);
await app.loadRecordings(day,session,0);row=els['recordings-list'].children[0];assert.equal(row.children[1].children[0].attrs.href,'cgi-bin/'+base+'0001.media');assert.equal(row.children[1].children[0].attrs.download,'');
assert.equal(calls.length,3);for(const c of calls){assert.match(c.url,/^cgi-bin\/recordings.cgi\?action=list&limit=100/);assert.equal(c.opts.credentials,'same-origin');assert.equal(c.opts.cache,'no-store');assert.equal(c.opts.method,undefined);assert(!c.url.includes('action=download'))}
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_recording_fetch_error_retains_fixed_message_without_rendering_body(self):
        self.node(r"""
const assert=require('assert'),api=require(process.argv[1]),els={};
function el(){return {textContent:'',hidden:false,disabled:false,set innerHTML(v){throw Error('no HTML')}}}
const doc={getElementById(id){return els[id]||(els[id]=el())}};
const app=api.createApp(doc,async()=>({ok:false,status:401,json:async()=>{throw Error('must not parse private body')}}),{setTimeout(){return 1},clearTimeout(){}});
(async()=>{await app.loadRecordings('','',0);assert.match(els['recordings-error'].textContent,/Authentication required/);assert.equal(els['recordings-error'].hidden,false);assert.equal(els['refresh-recordings'].disabled,false)})().catch(e=>{console.error(e);process.exit(1)});
""")


if __name__ == '__main__':
    unittest.main()
