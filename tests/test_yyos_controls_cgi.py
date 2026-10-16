"""CGI control fixtures execute only a synthetic helper and private temp files."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c'
CC = shutil.which('cc')
ARM_CC = shutil.which(os.environ.get('ARM_CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', os.environ.get('QEMU_ARM', 'qemu-arm')))
KEY = b'FixtureKey012345'
STATUS = {'ok': True, 'fixture': False, 'indicator': True, 'timestamp_osd': False, 'tracking': False}


class CGICases:
    arm = False

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='yyos-controls-cgi-')
        cls.base = Path(cls.temp.name)
        cls.root = cls.base / 'kit'
        cls.binary = cls.base / 'cgi'
        cls.reply = cls.base / 'reply'
        cls.calls = cls.base / 'calls'
        cls.mode = cls.base / 'mode'
        helper = cls.base / 'helper.c'
        helper.write_text(r'''
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv){
 char key[17]={0}; if(read(0,key,16)!=16 || memcmp(key,"FixtureKey012345",16))return 3;
 FILE *log=fopen(CALLS,"a");for(int i=1;i<argc;i++)fprintf(log,"%s%s",i==1?"":" ",argv[i]);fputs("\n",log);fclose(log);
 FILE *mode=fopen(MODE,"r");int m=mode?fgetc(mode):0;if(mode)fclose(mode);
 if(m=='h'){sleep(5);return 0;}
 if(m=='o'){for(int i=0;i<5000;i++)putchar('x');return 0;}
 FILE *f=fopen(REPLY,"r");int c;while((c=fgetc(f))!=EOF)putchar(c);fclose(f);
 return m=='e'?1:0;
}
''')
        subprocess.run([CC, '-std=c99', '-Wall', '-Wextra', '-Werror', '-DCALLS=' + json.dumps(str(cls.calls)),
                        '-DREPLY=' + json.dumps(str(cls.reply)), '-DMODE=' + json.dumps(str(cls.mode)),
                        str(helper), '-o', str(cls.base / 'synthetic-helper')], check=True, capture_output=True)
        command = [ARM_CC if cls.arm else CC, '-std=c99', '-Os', '-Wall', '-Wextra', '-Werror',
                   '-DYYOS_CONTROLS_CGI_FIXTURE_ROOT=' + json.dumps(str(cls.root)), '-DYYOS_CONTROLS_CGI_TEST_TIMEOUT_MS=300']
        if cls.arm: command += ['-static', '-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
        subprocess.run(command + [str(SOURCE), '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        if self.root.is_symlink(): self.root.unlink()
        elif self.root.exists(): shutil.rmtree(self.root)
        (self.root / 'bin').mkdir(parents=True)
        shutil.copyfile(self.base / 'synthetic-helper', self.root / 'bin/yyos-controls')
        (self.root / 'bin/yyos-controls').chmod(0o755)
        (self.root / 'native-control.key').write_bytes(KEY)
        self.calls.unlink(missing_ok=True)
        self.mode.write_bytes(b'')
        self.reply.write_text(json.dumps(STATUS))

    def call(self, body=None, method=None, **changes):
        method = method or ('POST' if body is not None else 'GET')
        if isinstance(body, dict): body = json.dumps(body).encode()
        if isinstance(body, str): body = body.encode()
        env = {'PATH': '/nonexistent', 'REQUEST_METHOD': method, 'REMOTE_USER': 'fixture-owner',
               'HTTP_HOST': '192.168.88.17:8080', 'QUERY_STRING': '', 'HTTP_ORIGIN': 'http://192.168.88.17:8080',
               'HTTP_X_LSCAMOFLASH_REQUEST': 'controls-v1', 'CONTENT_TYPE': 'application/json',
               'CONTENT_LENGTH': str(len(body or b'')), 'LD_PRELOAD': '/NO-SUCH-FOREIGN-PRELOAD'}
        for name, value in changes.items():
            if value is None: env.pop(name, None)
            else: env[name] = value
        command = ([QEMU, '-cpu', 'arm926'] if self.arm else []) + [str(self.binary)]
        result = subprocess.run(command, input=body or b'', env=env, capture_output=True, timeout=8)
        headers, raw = result.stdout.split(b'\r\n\r\n', 1)
        data = json.loads(raw)
        self.assertNotIn(KEY, result.stdout)
        self.assertNotIn(str(self.base).encode(), result.stdout)
        return result, dict(line.decode().split(': ', 1) for line in headers.split(b'\r\n')), data

    def refuse(self, result, code):
        self.assertNotEqual(result[0].returncode, 0)
        self.assertTrue(result[1]['Status'].startswith(str(code)))
        self.assertEqual(set(result[2]), {'ok', 'error'})
        self.assertFalse(self.calls.exists())

    def test_absent_key_get_is_unconfigured_and_post_refuses(self):
        (self.root / 'native-control.key').unlink()
        result = self.call()
        self.assertEqual(result[0].returncode, 0)
        self.assertEqual(result[2], {'ok': True, 'configured': False})
        self.refuse(self.call({'action': 'stop'}), 503)

    def test_authenticated_status_filters_only_three_booleans(self):
        self.reply.write_text(json.dumps({**STATUS, 'phase': 'PRIVATE-DO-NOT-ECHO'}))
        result = self.call()
        self.assertEqual(result[2], {'ok': True, 'configured': True, 'indicator': True, 'timestamp_osd': False, 'tracking': False})
        self.assertEqual(self.calls.read_text(), 'status\n')
        self.assertNotIn(b'PRIVATE', result[0].stdout)

    def test_auth_method_host_and_query_refuse_before_child(self):
        for change, code in [({'REMOTE_USER': None},401),({'REMOTE_USER':''},401),({'REMOTE_USER':'x\ny'},401),
                             ({'method':'OPTIONS'},405),({'method':'DELETE'},405),({'HTTP_HOST':'camera.local:8080'},400),
                             ({'HTTP_HOST':'192.168.88.17:80'},400),({'HTTP_HOST':'127.0.0.1:8080'},400),
                             ({'HTTP_HOST':'192.168.088.17:8080'},400),({'HTTP_HOST':'192.168.88.17:8080/evil'},400),
                             ({'QUERY_STRING':'action=stop'},400)]:
            with self.subTest(change=change): self.refuse(self.call(**change),code)

    def test_post_origin_custom_header_type_size_and_short_body_guards(self):
        for changes, code in [({'HTTP_ORIGIN':None},403),({'HTTP_ORIGIN':'http://evil'},403),
                              ({'HTTP_ORIGIN':'https://192.168.88.17:8080'},403),({'HTTP_X_LSCAMOFLASH_REQUEST':None},403),
                              ({'HTTP_X_LSCAMOFLASH_REQUEST':'other'},403),({'CONTENT_TYPE':'text/plain'},400),
                              ({'CONTENT_LENGTH':'257'},400),({'CONTENT_LENGTH':'-1'},400),({'CONTENT_LENGTH':'00'},400),
                              ({'CONTENT_LENGTH':'200'},400)]:
            with self.subTest(changes=changes): self.refuse(self.call({'action':'stop'},**changes),code)

    def test_json_duplicate_unknown_nested_and_arbitrary_actions_refused(self):
        for body in ['{"action":"stop","action":"jog"}', '{"action":"stop","extra":true}',
                     '{"action":"indicator","value":"true"}', '{"action":"indicator","value":1}',
                     '{"action":"jog","direction":"../up"}', '{"action":"jog","direction":"up","value":true}',
                     '{"action":"shell","command":"id"}', '{"action":"tracking","value":false}',
                     '{"action":"stop","value":{}}', '{"action":"stop"} garbage',
                     '{"act\\u0069on":"stop"}', '[]', '{}']:
            with self.subTest(body=body): self.refuse(self.call(body),400)

    def test_raw_nul_is_not_json_whitespace(self):
        for body in (b'\0{"action":"stop"}', b'{"action":"stop"}\0', b'{"action":\0"stop"}'):
            self.refuse(self.call(body),400)

    def test_fixed_boolean_actions_and_explicit_stop(self):
        for action in ('indicator','timestamp_osd'):
            for value in (True,False):
                self.reply.write_text(json.dumps({'ok':True,'fixture':False,'action':action,'value':value,'readback_verified':True}))
                result = self.call({'action':action,'value':value})
                self.assertEqual(result[0].returncode,0)
                self.assertEqual(result[2]['value'],value)
                self.assertTrue(self.calls.read_text().splitlines()[-1].endswith(str(value).lower()))
        self.reply.write_text('{"ok":true,"fixture":false,"action":"stop","stop_acknowledged":true}')
        self.assertEqual(self.call({'action':'stop'})[0].returncode,0)
        self.assertEqual(self.calls.read_text().splitlines()[-1],'stop')

    def test_fixed_cardinal_step_requires_complete_guardian_ack(self):
        reply={'ok':True,'fixture':False,'action':'jog','jog_ms':200,'armed':True,'move_acknowledged':True,
               'stop_acknowledged':True,'stop_attempts':1,'physical_hard_deadline_proven':False}
        self.reply.write_text(json.dumps(reply))
        for direction in ('up','right','down','left'):
            self.assertEqual(self.call({'action':'jog','direction':direction})[0].returncode,0)
            self.assertEqual(self.calls.read_text().splitlines()[-1],'jog '+direction)
        self.reply.write_text(json.dumps({**reply,'stop_acknowledged':False}))
        self.assertEqual(self.call({'action':'jog','direction':'up'})[2]['error'],'invalid_control_response')

    def test_key_symlink_hardlink_fifo_invalid_size_or_encoding_refused(self):
        key=self.root/'native-control.key'
        for value in (b'',b'x'*15,b'x'*18,b'bad\nkey012345678',b'x'*16+b'\r'):
            key.write_bytes(value);self.refuse(self.call(),503)
        key.unlink(); key.symlink_to(self.reply);self.refuse(self.call(),503)
        key.unlink();os.link(self.reply,key);self.refuse(self.call(),503)
        key.unlink();os.mkfifo(key);self.refuse(self.call(),503)
        key.unlink();key.write_bytes(KEY+b'\n');self.assertEqual(self.call()[0].returncode,0)

    def test_root_bin_and_helper_symlinks_refused(self):
        for path in (self.root,self.root/'bin',self.root/'bin/yyos-controls'):
            target=self.base/('saved-'+path.name);path.rename(target);path.symlink_to(target)
            try:self.refuse(self.call(),503)
            finally:path.unlink();target.rename(path)

    def test_child_failures_malformed_secret_output_and_hang_bounded(self):
        for text in ('{"ok":true,"fixture":false,"indicator":"secret"}', '{"ok":true,"ok":false}',
                     '{"ok":true,"secret":"PRIVATE-DO-NOT-ECHO"}', '{"ok":false,"phase":"PRIVATE-DO-NOT-ECHO"}',
                     json.dumps({**STATUS,'fixture':True}), json.dumps(STATUS)+'\0SECRET'):
            self.reply.write_text(text)
            result=self.call();self.assertEqual(result[1]['Status'],'503 Service Unavailable');self.assertNotIn(b'PRIVATE',result[0].stdout)
        self.mode.write_bytes(b'o');self.assertEqual(self.call()[1]['Status'],'503 Service Unavailable')
        self.mode.write_bytes(b'h');started=time.monotonic();self.assertEqual(self.call()[1]['Status'],'503 Service Unavailable');self.assertLess(time.monotonic()-started,2)


@unittest.skipUnless(CC,'Host C compiler required')
class HostCGITests(CGICases,unittest.TestCase):pass

@unittest.skipUnless(CC and ARM_CC and QEMU,'Host+ARM C compiler and QEMU required')
class ArmCGITests(CGICases,unittest.TestCase):arm=True

@unittest.skipUnless(shutil.which('node'), 'Node required for control UI fixtures')
class ControlsFrontendTests(unittest.TestCase):
    def node(self, program):
        result = subprocess.run(['node', '-e', program, str(REPO / 'SOURCE/src/yyos/www/dashboard.js')], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixed_schema_and_disabled_default(self):
        self.node(r"""
const assert=require('assert'),api=require(process.argv[1]),elements={};
function el(){return {textContent:'',disabled:false,hidden:false}}
const doc={getElementById(id){return elements[id]||(elements[id]=el())}};
const app=api.createApp(doc,()=>{throw Error('No request expected')},{});
app.renderControls({ok:true,configured:false});assert.equal(elements['control-up'].disabled,true);assert.equal(elements['control-indicator'].disabled,true);
app.renderControls({ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:true});assert.equal(elements['control-up'].disabled,true);assert.equal(elements['control-stop'].disabled,false);
assert.throws(()=>api.controlRequest('tracking',false));assert.throws(()=>api.controlRequest('indicator','true'));assert.throws(()=>api.controlRequest('jog','up;id'));assert.throws(()=>api.controlStatus({ok:true,configured:true,indicator:true}));
assert.deepEqual(api.controlRequest('jog','left'),{action:'jog',direction:'left'});
""")

    def test_post_has_same_origin_json_header_and_only_read_only_refresh(self):
        self.node(r"""
const assert=require('assert'),api=require(process.argv[1]),elements={},calls=[];
function el(){return {textContent:'',disabled:false,hidden:false}}
const doc={getElementById(id){return elements[id]||(elements[id]=el())}},timers={setTimeout(){return 1},clearTimeout(){}};
const app=api.createApp(doc,async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>options.method==='POST'?{ok:true,configured:true,action:'indicator',value:false,readback_verified:true}:{ok:true,configured:true,indicator:false,timestamp_osd:false,tracking:false}}},timers);
app.renderControls({ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:false});
(async()=>{await app.sendControl('indicator',false);assert.equal(calls.length,2);assert.equal(calls[0].url,'cgi-bin/controls.cgi');assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.headers['Content-Type'],'application/json');assert.equal(calls[0].options.headers['X-LSCamoflash-Request'],'controls-v1');assert.deepEqual(JSON.parse(calls[0].options.body),{action:'indicator',value:false});assert.equal(calls[1].options.method,undefined);assert.equal(elements['control-up'].disabled,false)})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_jog_double_click_and_held_keys_do_not_repeat_after_completion(self):
        self.node(r"""
const assert=require('assert'),api=require(process.argv[1]),elements={},calls=[];
function el(){return {textContent:'',disabled:false,hidden:false,events:{},setAttribute(){},addEventListener(name,fn){this.events[name]=fn}}}
const doc={hidden:false,getElementById(id){return elements[id]||(elements[id]=el())}},timers={setTimeout(){return 1},clearTimeout(){},setInterval(){return 1}};
const app=api.createApp(doc,async(url,options)=>{if(url.includes('status.cgi'))return {ok:false,status:503};calls.push(options);return {ok:true,json:async()=>options.method==='POST'?{ok:true,configured:true,action:'jog',jog_ms:200,stop_acknowledged:true,physical_hard_deadline_proven:false}:{ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:false}}},timers);
(async()=>{await app.initialize();app.renderControls({ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:false});elements['control-up'].events.click({detail:1});await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(elements['control-up'].disabled,false);elements['control-up'].events.click({detail:2});elements['control-up'].events.click({detail:3});await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.filter(c=>c.method==='POST').length,1);for(const key of ['Enter',' ']){let prevented=false;elements['control-up'].events.keydown({repeat:true,key,preventDefault(){prevented=true}});assert(prevented)}let initialPrevented=false;elements['control-up'].events.keydown({repeat:false,key:'Enter',preventDefault(){initialPrevented=true}});assert.equal(initialPrevented,false)})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_failed_or_ambiguous_write_is_not_replayed_and_tracking_refuses_step(self):
        self.node(r"""
const assert=require('assert'),api=require(process.argv[1]),elements={},calls=[];
const doc={getElementById(id){return elements[id]||(elements[id]={textContent:'',disabled:false,hidden:false})}},timers={setTimeout(){return 1},clearTimeout(){}};
const app=api.createApp(doc,async(url,options)=>{calls.push({url,options});return {ok:false,status:503,json:async()=>{throw Error('Private error must not render')}}},timers);
app.renderControls({ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:true});
(async()=>{await app.sendControl('jog','up');assert.equal(calls.length,0);app.renderControls({ok:true,configured:true,indicator:true,timestamp_osd:false,tracking:false});await app.sendControl('jog','up');assert.equal(calls.length,1);assert.match(elements['controls-error'].textContent,/No write will be retried/);assert.equal(elements['control-up'].disabled,true);await app.sendControl('jog','up');assert.equal(calls.length,1);assert.equal(elements['control-stop'].disabled,false);await app.sendControl('stop');assert.equal(calls.length,2);assert.deepEqual(JSON.parse(calls[1].options.body),{action:'stop'})})().catch(e=>{console.error(e);process.exit(1)});
""")


if __name__=='__main__':unittest.main()
