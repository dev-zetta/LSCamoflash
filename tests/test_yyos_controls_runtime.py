#!/usr/bin/env python3
"""ARM controls tests use only a synthetic localhost Tuya server.

Set YYOS_CONTROLS_BUILD and YYOS_MUSL_BUILD to complete public builder outputs.
TinyTuya is an optional, independent test codec; production never imports it.
The 26 protocol/lifecycle cases plus 15 profile and 8 interface checks cover
49 meaningful controls. Fixture binaries live in a temporary test directory.
"""
from pathlib import Path
import hashlib
import hmac
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

try:
    from tinytuya.core.message_helper import TuyaMessage, pack_message, unpack_message
    from tinytuya.core.crypto_helper import AESCipher
except ImportError:
    TuyaMessage = None

REPO = Path(__file__).resolve().parents[1]
KEY = b"0123456789abcdef"  # Public synthetic test data, never a camera key.
QEMU = None
BIN = None


def build_module():
    path = REPO / "tools/yyos/build-controls.py"
    spec = importlib.util.spec_from_file_location("yyos_controls_builder_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receive(c,key):
 def exact(n):
  result=b''
  while len(result)<n:
   p=c.recv(n-len(result))
   if not p:raise EOFError()
   result+=p
  return result
 header=exact(18);n=struct.unpack_from('>I',header,14)[0]
 assert 28<=n<=8192-22
 message=unpack_message(header+exact(n+4),hmac_key=key,no_retcode=True)
 assert message.crc_good
 return message

def frame(cmd,data,key,seq):
 return pack_message(TuyaMessage(seq,cmd,0,data,0,True,0x6699,True),hmac_key=key)

def run(name,args,kind='normal',expected_exit=0,kill_owner=False,delayed=False):
 events=[];errors=[];threads=[];done=threading.Event();move_seen=threading.Event()
 state={'101':True,'104':True,'161':kind=='tracking_enabled'}
 listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',6668));listener.listen(8);listener.settimeout(.1)
 def client(c,index):
  try:
   with c:
    c.settimeout(2)
    local=receive(c,KEY);assert local.cmd==3 and len(local.payload)==16
    remote=bytes([65+index])*16
    proof=hmac.new(KEY,local.payload,hashlib.sha256).digest()
    if kind=='bad_handshake' or (kind=='bad_fresh_handshake' and index>=2):proof=bytes([proof[0]^1])+proof[1:]
    c.sendall(frame(4,remote+proof,KEY,1))
    if kind=='bad_handshake' or (kind=='bad_fresh_handshake' and index>=2):return
    finish=receive(c,KEY);assert finish.cmd==5 and finish.payload==hmac.new(KEY,remote,hashlib.sha256).digest()
    session=AESCipher(KEY).encrypt(bytes(a^b for a,b in zip(local.payload,remote)),use_base64=False,pad=False,iv=local.payload[:12])[12:28]
    seq=2
    while True:
     request=receive(c,session)
     if request.cmd==16:
      assert request.payload==b'{}'
      events.append({'kind':'query','connection':index,'at':time.monotonic()})
      if kind=='duplicate_tracking':payload=b'{"dps":{"101":true,"104":true,"161":false,"161":false}}'
      elif kind=='escaped_duplicate_tracking':payload=b'{"dps":{"101":true,"104":true,"161":false,"\\u0031\\u0036\\u0031":true}}'
      elif kind=='wrong_tracking_type':payload=b'{"dps":{"101":true,"104":true,"161":"false"}}'
      else:payload=json.dumps({'dps':{**state,'238':'DO_NOT_LOG_SYNTHETIC_PAYLOAD'}},separators=(',',':')).encode()
      reply=frame(16,b'3.5'+b'\0'*12+payload,session,seq)
      if kind=='bad_status_tag' or (kind=='bad_fresh_status' and index>=2):reply=reply[:-5]+bytes([reply[-5]^1])+reply[-4:]
      c.sendall(reply);seq+=1
     elif request.cmd==13:
      assert request.payload[:15]==b'3.5'+b'\0'*12
      data=json.loads(request.payload[15:]);assert set(data)=={'protocol','t','data'} and data['protocol']==5 and type(data['t']) is int
      assert set(data['data'])=={'dps'};dps=data['data']['dps'];assert len(dps)==1
      dp,value=next(iter(dps.items()))
      assert dp in ('101','104','116','119')
      assert (type(value) is bool) if dp!='119' else type(value) is str and value in ('0','2','4','6')
      if dp=='116':assert value is True
      events.append({'kind':'control','dp':dp,'value':value,'connection':index,'at':time.monotonic()})
      if dp=='119':move_seen.set()
      if dp in ('101','104') and kind!='readback_mismatch':state[dp]=value
      if (dp=='119' and kind=='ambiguous_move_ack') or (dp=='116' and kind=='retry_stops' and sum(e.get('dp')=='116' for e in events)<3):continue
      c.sendall(frame(13,b'{}',session,seq));seq+=1
     else:raise AssertionError('unexpected command')
  except (EOFError,ConnectionResetError,BrokenPipeError):pass
  except Exception as e:errors.append(type(e).__name__)
 def accept():
  index=0
  while not done.is_set():
   try:c,_=listener.accept()
   except socket.timeout:continue
   except OSError:break
   index+=1;t=threading.Thread(target=client,args=(c,index));threads.append(t);t.start()
 accept_thread=threading.Thread(target=accept);accept_thread.start()
 env=os.environ.copy()
 if delayed:env['YYOS_FIXTURE_DELAY_WORKER']='1'
 if kind=='deferred_reap':env['YYOS_FIXTURE_DEFER_REAP']='1'
 if kind=='stop_clock_failure':env['YYOS_FIXTURE_FAIL_STOP_CLOCK']='1'
 if kind=='new_lock_owner':env['YYOS_FIXTURE_NEW_LOCK_OWNER']='1'
 p=subprocess.Popen([str(QEMU),'-cpu','arm926',str(BIN),*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
 p.stdin.write(KEY);p.stdin.close();p.stdin=None
 if kill_owner:
  assert move_seen.wait(3);p.kill()
 stdout,stderr=p.communicate(timeout=12)
 done.set();listener.close();accept_thread.join(1)
 for t in threads:t.join(3)
 assert not any(t.is_alive() for t in threads)
 output=json.loads(stdout) if stdout else None
 controls=[e for e in events if e['kind']=='control'];moves=[e for e in controls if e['dp']=='119'];stops=[e for e in controls if e['dp']=='116']
 okay=p.returncode==expected_exit and not errors and not stderr and b'DO_NOT_LOG' not in stdout+stderr
 if args[0]=='jog':
  if kind in ('tracking_enabled','duplicate_tracking','wrong_tracking_type','bad_handshake','bad_status_tag','escaped_duplicate_tracking'):okay=okay and not controls
  elif delayed:okay=okay and not moves and len(stops)==1 and output['armed'] and not output['move_acknowledged']
  else:
   okay=okay and len(moves)==1 and len(stops)==(3 if kind=='retry_stops' else 1) and moves[0]['connection']!=stops[0]['connection'] and 0<=stops[0]['at']-moves[0]['at']<1.3
   if kill_owner:okay=okay and output is None and stops[0]['at']-moves[0]['at']<.5
   elif kind=='ambiguous_move_ack':okay=okay and not output['move_acknowledged'] and output['stop_acknowledged']
   elif kind=='deferred_reap':okay=okay and output['phase']=='move_reap_deferred' and output['stop_acknowledged']
   elif kind=='stop_clock_failure':okay=okay and not output['stop_acknowledged'] and output['stop_attempts']==1
   else:okay=okay and output['ok'] and output['stop_acknowledged']
 elif args[0]=='status':okay=okay and not controls and output['ok']
 elif args[0]=='stop':okay=okay and len(controls)==1 and controls[0]['dp']=='116'
 else:
  count=0 if args[1]=='true' else 1
  okay=okay and len(controls)==count and all(e['dp']==('101' if args[0]=='indicator' else '104') for e in controls)
  if kind in ('readback_mismatch','bad_fresh_status'):okay=okay and output['phase']=='setting_readback'
  elif kind=='bad_fresh_handshake':okay=okay and output['phase']=='setting_readback_connect'
  else:okay=okay and output['ok']
  if count and kind!='bad_fresh_handshake':
   queries=[e for e in events if e['kind']=='query']
   okay=okay and len(queries)==2 and queries[0]['connection']!=queries[1]['connection']
 if kind=='new_lock_owner':
  lock=Path('/tmp/yyos-controls-fixture.lock');preserved=lock.is_dir();okay=okay and preserved
  if preserved:lock.rmdir()
 return {'name':name,'ok':okay,'exit_code':p.returncode,'output':output,'controls':[{k:v for k,v in e.items() if k!='at'} for e in controls],'query_count':sum(e['kind']=='query' for e in events),'server_error_classes':errors,'camera_contacted':False,'raw_sensitive_payload_not_printed':b'DO_NOT_LOG' not in stdout+stderr}


CASES = [
    ("status", ["status"], {}),
    ("indicator_noop", ["indicator", "true"], {}),
    ("indicator_change", ["indicator", "false"], {}),
    ("timestamp_osd_noop", ["timestamp_osd", "true"], {}),
    ("timestamp_osd_change", ["timestamp_osd", "false"], {}),
    ("setting_readback_mismatch", ["indicator", "false"], {"kind": "readback_mismatch", "expected_exit": 1}),
    ("setting_fresh_read_status_failure", ["indicator", "false"], {"kind": "bad_fresh_status", "expected_exit": 1}),
    ("setting_fresh_read_handshake_failure", ["timestamp_osd", "false"], {"kind": "bad_fresh_handshake", "expected_exit": 1}),
    ("fixed_stop", ["stop"], {}),
    *[("jog_" + direction, ["jog", direction], {}) for direction in ("up", "right", "down", "left")],
    ("jog_owner_sigkill", ["jog", "up"], {"expected_exit": -9, "kill_owner": True}),
    ("jog_expired_worker_killed", ["jog", "up"], {"expected_exit": 1, "delayed": True}),
    ("jog_move_ack_ambiguous_still_stop", ["jog", "up"], {"kind": "ambiguous_move_ack", "expected_exit": 1}),
    ("jog_stop_retries_only", ["jog", "up"], {"kind": "retry_stops"}),
    ("jog_stop_before_deferred_reap", ["jog", "up"], {"kind": "deferred_reap", "expected_exit": 1}),
    ("jog_prepared_stop_even_clock_failure", ["jog", "up"], {"kind": "stop_clock_failure", "expected_exit": 1}),
    ("jog_preserves_next_owners_lock", ["jog", "up"], {"kind": "new_lock_owner"}),
    *[("jog_refuses_" + kind, ["jog", "up"], {"kind": kind, "expected_exit": 1})
      for kind in ("tracking_enabled", "duplicate_tracking", "wrong_tracking_type",
                   "bad_handshake", "bad_status_tag", "escaped_duplicate_tracking")],
]


class ControlsARMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global BIN, QEMU
        if TuyaMessage is None:
            raise unittest.SkipTest("install TinyTuya in a private test environment for the independent codec")
        build_path = os.environ.get("YYOS_CONTROLS_BUILD")
        musl_path = os.environ.get("YYOS_MUSL_BUILD")
        if not build_path or not musl_path:
            raise unittest.SkipTest("set YYOS_CONTROLS_BUILD and YYOS_MUSL_BUILD to public builder outputs")
        cls.build = Path(build_path).absolute()
        cls.musl = Path(musl_path).absolute()
        cls.module = build_module()
        cls.compiler, _ = cls.module.helpers().validate_musl(cls.musl)
        cls.proof = json.loads((cls.build / "provenance.json").read_text())
        if cls.proof.get("name") != "yyos-controls" or cls.proof.get("test_fixture_compiled") is not False:
            raise AssertionError("a production controls build is required")
        cls.module.helpers().verify_source(cls.build / "dropbear-2026.94.tar.bz2")
        cls.temporary = tempfile.TemporaryDirectory(prefix="yyos-controls-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        QEMU = Path(os.environ.get("QEMU_ARM", shutil.which("qemu-arm") or
                    str(REPO / ".local/tools/root/usr/bin/qemu-arm")))
        if not QEMU.is_file():
            raise unittest.SkipTest("qemu-arm is required")
        if Path("/tmp/yyos-controls-fixture.lock").exists():
            raise unittest.SkipTest("unknown existing fixture lock is preserved; stop its owner before testing")
        definitions = ["-D" + name for name in cls.module.DEFINITIONS]
        cls.flags = [*cls.module.CFLAGS, *definitions,
                     "-I" + str(cls.build / "dropbear-2026.94/libtomcrypt/src/headers")]
        cls.runtime = [str(REPO / "tools/yyos/yyos-clock-compat.c"),
                       str(cls.build / "objects/libyyoscrypto.a")]
        BIN = directory / "controls-fixture"
        cls.compile(REPO / "SOURCE/src/contrib/yyos-controls/yyos_controls.c", BIN,
                    ["-DYYOS_TEST_FIXTURE", '-DYYOS_FIXTURE_KEY="0123456789abcdef"'])
        cls.profile = directory / "profile-guards"
        cls.compile(REPO / "tests/fixtures/yyos-controls-profile.c", cls.profile, [])

    @classmethod
    def compile(cls, source, output, extra):
        command = [str(cls.compiler), *cls.flags, *extra, "-static", "-Wl,--gc-sections",
                   str(source), *cls.runtime, "-o", str(output)]
        run = subprocess.run(command, capture_output=True, timeout=60)
        if run.returncode or run.stderr:
            raise AssertionError("fixture compilation failed: " + run.stderr.decode(errors="replace"))

    def test_profile_guards_fifteen_checks(self):
        completed = subprocess.run([str(QEMU), "-cpu", "arm926", str(self.profile)],
                                   capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout),
                         {"ok": True, "checks": 15, "failures": 0, "metadata_synthetic": True})

    def test_interface_and_profile_eight_refusals(self):
        for args in (["jog", "diagonal"], ["jog", "up", "300"], ["dp", "119", "0"],
                     ["indicator", "1"], ["timestamp_osd", "false", "extra"],
                     ["status", "192.168.88.17"]):
            with self.subTest(args=args):
                completed = subprocess.run([str(QEMU), "-cpu", "arm926", str(BIN), *args],
                                           input=KEY, capture_output=True, timeout=3)
                self.assertEqual((completed.returncode, completed.stdout, completed.stderr), (2, b"", b""))
        completed = subprocess.run([str(QEMU), "-cpu", "arm926", str(self.build / "bin/yyos-controls"), "status"],
                                   input=KEY, capture_output=True, timeout=3)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)["phase"], "profile_or_clock_guard")
        completed = subprocess.run([str(QEMU), "-cpu", "arm926", str(BIN), "status"],
                                   input=b"wrongsynthetickey", capture_output=True, timeout=3)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)["phase"], "key_input")


def case_test(name, args, options):
    def test(self):
        result = run(name, args, **options)
        self.assertTrue(result["ok"], result)
    return test


for name, args, options in CASES:
    setattr(ControlsARMTests, "test_" + name, case_test(name, args, options))


if __name__ == "__main__":
    unittest.main()
