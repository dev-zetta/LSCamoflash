"""Isolated SSH lifecycle fixtures: fake native daemon, no sockets or hardware."""
import base64
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'SOURCE/src/yyos-ssh'
FAKE = r'''
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
static volatile sig_atomic_t done;
static void stop(int number) { (void)number; done=1; }
int main(int argc,char **argv) {
 const char *pid=NULL,*bind=NULL;
 for(int i=1;i<argc;i++){if(!strcmp(argv[i],"-P") && i+1<argc)pid=argv[++i];else if(!strcmp(argv[i],"-p") && i+1<argc)bind=argv[++i];}
 if(!pid || !bind || !access(FAIL_FILE,F_OK))return 17;
 signal(SIGTERM,stop); signal(SIGCHLD,SIG_IGN);
 FILE *f=fopen(pid,"w");if(!f)return 18;fprintf(f,"%ld\n",(long)getpid());fclose(f);
 f=fopen(PORT_FILE,"w");if(!f)return 19;fprintf(f,"tcp 0 0 %s 0.0.0.0:* LISTEN\n",bind);fclose(f);
 if(!access(FORK_FILE,F_OK)){pid_t child=fork();if(child==0){signal(SIGTERM,SIG_DFL);for(;;)pause();}
  f=fopen(CHILD_FILE,"w");if(f){fprintf(f,"%ld\n",(long)child);fclose(f);}}
 while(!done){pause();}
 unlink(PORT_FILE);unlink(pid);return 0;
}
'''


@unittest.skipUnless(shutil.which('busybox') and shutil.which('cc'), 'Host BusyBox and C compiler required')
class YYOSSSHTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yyos-ssh-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.card = self.base / 'card'
        self.root = self.card / 'LSCamoflash-yyos-ssh'
        self.ram = self.base / 'run'
        self.state = self.ram / 'lscamoflash-yyos-ssh'
        (self.root / 'bin').mkdir(parents=True)
        self.ram.mkdir(mode=0o755)
        self.bb = self.root / 'bin/busybox'
        shutil.copyfile(shutil.which('busybox'), self.bb)
        self.bb.chmod(0o755)
        self.db = self.root / 'bin/dropbear'
        self.ports = self.base / 'ports'
        self.ports.write_text('')
        self.ip = self.base / 'ip'
        self.ip.write_text('inet 192.168.44.17/24\n')
        self.mounts = self.base / 'mounts'
        self.device = self.base / 'mmcblk0p1'
        self.device.touch()
        self.mounts.write_text(f'tmpfs {self.card} tmpfs rw 0 0\n{self.device} {self.card} vfat rw 0 0\ntmpfs {self.ram} tmpfs rw 0 0\n')
        self.cpu = self.base / 'cpuinfo'
        self.cpu.write_text('Hardware\t: AK3918AV130\n')
        self.stock = self.base / 'stock-app'
        self.stock.write_bytes(b'fixture stock identity; never execute')
        self.fail = self.base / 'daemon-fail'
        self.fork = self.base / 'daemon-fork'
        self.childfile = self.base / 'daemon-child'
        c = self.base / 'fake.c'
        c.write_text(FAKE)
        command = ['cc','-std=c99','-O1','-Wall','-Wextra','-Werror',str(c),'-o',str(self.db)]
        for name,path in (('PORT_FILE',self.ports),('FAIL_FILE',self.fail),('FORK_FILE',self.fork),('CHILD_FILE',self.childfile)):
            command.append('-D' + name + '="' + str(path) + '"')
        result = subprocess.run(command,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        for name in ('common.sh','start.sh','stop.sh'):
            text = (SOURCE / name).read_text().replace('/mnt/sdcard', str(self.card))
            if name == 'common.sh':
                text = text.replace('RAM="/run"','RAM="'+str(self.ram)+'"')
                text = text.replace('MMC="/dev/mmcblk0p1"','MMC="'+str(self.device)+'"')
                text = text.replace('CPUINFO="$PROC/cpuinfo"','CPUINFO="'+str(self.cpu)+'"')
                text = text.replace('MOUNTS="$PROC/mounts"','MOUNTS="'+str(self.mounts)+'"')
                text = text.replace('STOCK="/appfs/bin/yy_cam"','STOCK="'+str(self.stock)+'"')
                text = text.replace('d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7',hashlib.sha256(self.stock.read_bytes()).hexdigest())
                text = text.replace('[ -b "$source" ] && [ ! -L "$source" ] || continue # FIXTURE_BLOCK_CHECK',
                                    '[ -f "$source" ] && [ ! -L "$source" ] || continue # FIXTURE_BLOCK_CHECK')
                text = text.replace('WAIT_SECONDS=120','WAIT_SECONDS=2').replace('-le 256','-le 4096')
                text = text.replace('tool() {','real_tool() {',1)
                text += f'''\ntool() {{
 case "$1:$2:$3:$4:$5" in
  id:-u:::) printf '0\\n';;
  stat:-f:-c:%t:"$CARD_MOUNT") printf '4d44\\n';;
  stat:-f:-c:%t:"$RAM") printf '1021994\\n';;
  stat:-c:%d:"$CARD_MOUNT":) printf '45825\\n';;
  stat:-c:%t:%T:"$MMC":) printf 'b3:1\\n';;
  stat:-c:'%u %g %a':/:|stat:-c:'%u %g %a':"$RAM":) printf '0 0 755\\n';;
  ip:*) "$BB" cat '{self.ip}';;
  netstat:*) "$BB" cat '{self.ports}';;
  *) real_tool "$@";;
 esac
}}
'''
            (self.root / name).write_text(text)
        for name in ('README.md','LICENSE.MIT','COPYING.BusyBox','COPYING.Dropbear','manifest.json'):
            (self.root / name).write_text('synthetic public payload\n')
        blob = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))
        self.key = b'ssh-ed25519 ' + base64.b64encode(blob) + b' synthetic-owner\n'
        self.hostkey = b'\0\0\0\x0bssh-ed25519\0\0\0\x40' + bytes(range(64))
        (self.root / 'authorized_keys').write_bytes(self.key)
        (self.root / 'dropbear_ed25519_host_key').write_bytes(self.hostkey)
        (self.root / 'ssh.enabled').write_bytes(b'enabled\n')
        self.sums()
        self.addCleanup(self.cleanup_processes)

    def sums(self):
        names = ('common.sh','start.sh','stop.sh','README.md','bin/busybox','bin/dropbear',
                 'LICENSE.MIT','COPYING.BusyBox','COPYING.Dropbear','manifest.json')
        (self.root / 'SHA256SUMS').write_text(''.join(hashlib.sha256((self.root/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in names))

    def run_script(self,name):
        shell = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL','')) or [str(self.bb),'sh']
        return subprocess.run([*shell,str(self.root/name)],capture_output=True,text=True,timeout=25)

    def function(self,command):
        shell = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL','')) or [str(self.bb),'sh']
        return subprocess.run([*shell,'-c','. "$1"; '+command,'fixture',str(self.root/'common.sh')],capture_output=True,text=True,timeout=10)

    def cleanup_processes(self):
        for path in (self.childfile,self.state/'dropbear.pid'):
            if path.exists():
                try:
                    pid=int(path.read_text().strip())
                    if pid>1 and Path(f'/proc/{pid}/exe').resolve()==self.db:
                        os.kill(pid,signal.SIGCONT);os.kill(pid,signal.SIGTERM)
                except (OSError,ValueError):
                    pass
        time.sleep(0.03)

    def test_default_disabled_does_not_create_state(self):
        (self.root/'ssh.enabled').unlink()
        result=self.run_script('start.sh')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.state.exists())

    def test_owned_start_stop_and_private_ram_copies(self):
        result=self.run_script('start.sh')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.state.stat().st_mode&0o777,0o700)
        for name in ('authorized_keys','dropbear_ed25519_host_key'):
            self.assertEqual((self.state/name).stat().st_mode&0o777,0o600)
            self.assertEqual((self.state/name).read_bytes(),(self.root/name).read_bytes())
        owner=(self.state/'owner').read_bytes()
        pid=int((self.state/'dropbear.pid').read_text())
        argv=Path(f'/proc/{pid}/cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        self.assertEqual(argv,[str(self.db).encode(),b'-F',b'-s',b'-j',b'-k',b'-D',str(self.state).encode(),
                              b'-r',str(self.state/'dropbear_ed25519_host_key').encode(),
                              b'-P',str(self.state/'dropbear.pid').encode(),b'-p',b'192.168.44.17:2222',
                              b'-I',b'600',b'-K',b'30',b'-T',b'3'])
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.assertEqual((self.state/'owner').read_bytes(),owner)
        result=self.run_script('stop.sh')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.state.exists())

    def test_marker_key_options_multiple_keys_and_host_format_refuse(self):
        for name,data in (('ssh.enabled',b'yes\n'),('authorized_keys',b'command="id" '+self.key),
                          ('authorized_keys',self.key+self.key),('authorized_keys',self.key.replace(b'ssh-ed25519',b'ssh-rsa')),
                          ('dropbear_ed25519_host_key',self.hostkey+b'x')):
            original=(self.root/name).read_bytes()
            (self.root/name).write_bytes(data)
            result=self.run_script('start.sh')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(self.state.exists())
            (self.root/name).write_bytes(original)

    def test_private_address_allowlist_and_multiple_addresses(self):
        for ip in ('10.0.0.1','172.16.0.1','172.31.255.254','192.168.1.1'):
            self.assertEqual(self.function('private_ipv4 '+ip).returncode,0)
        for ip in ('8.8.8.8','172.15.0.1','172.32.0.1','127.0.0.1','192.168.999.1'):
            self.assertNotEqual(self.function('private_ipv4 '+ip).returncode,0)
        self.ip.write_text('inet 192.168.1.1/24\ninet 10.0.0.1/24\n')
        result=self.run_script('start.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.state.exists())

    def test_profile_mount_payload_unknown_files_and_symlinks_refuse(self):
        self.cpu.write_text('Hardware: different\n')
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.cpu.write_text('Hardware: AK3918AV130\n')
        saved=self.mounts.read_text();self.mounts.write_text(saved.replace('vfat rw','vfat ro'))
        self.assertNotEqual(self.run_script('start.sh').returncode,0);self.mounts.write_text(saved)
        (self.root/'README.md').write_text('tampered')
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.sums();(self.root/'unknown').write_text('unknown')
        self.assertNotEqual(self.run_script('start.sh').returncode,0);(self.root/'unknown').unlink()
        (self.root/'authorized_keys').unlink();(self.root/'authorized_keys').symlink_to(self.stock)
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.assertFalse(self.state.exists())

    def test_occupied_port_existing_state_and_daemon_failure_preserved(self):
        self.ports.write_text('tcp 0 0 192.168.44.17:2222 0.0.0.0:* LISTEN\n')
        self.assertNotEqual(self.run_script('start.sh').returncode,0);self.assertFalse(self.state.exists())
        self.ports.write_text('');self.state.mkdir();(self.state/'keep').write_text('keep')
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.assertEqual((self.state/'keep').read_text(),'keep');shutil.rmtree(self.state)
        self.fail.touch()
        self.assertNotEqual(self.run_script('start.sh').returncode,0)
        self.assertFalse(self.state.exists())

    def test_stop_wrong_pid_timestamp_preserves_unrelated_process(self):
        other=subprocess.Popen([str(self.bb),'sleep','20'])
        try:
            self.state.mkdir()
            for value in ('0 1 192.168.44.17\n','1 1 192.168.44.17\n',f'{other.pid} 1 192.168.44.17\n'):
                (self.state/'owner').write_text(value)
                self.assertNotEqual(self.run_script('stop.sh').returncode,0)
                self.assertIsNone(other.poll())
        finally:
            other.terminate();other.wait(timeout=3)

    def test_stop_timestamp_mismatch_does_not_signal_live_owned_daemon(self):
        result=self.run_script('start.sh');self.assertEqual(result.returncode,0,result.stderr)
        owner=(self.state/'owner').read_text()
        pid,stamp,address=owner.split()
        (self.state/'owner').write_text(f'{pid} {int(stamp)+1} {address}\n')
        self.assertNotEqual(self.run_script('stop.sh').returncode,0)
        self.assertTrue(Path(f'/proc/{pid}/exe').exists())
        self.assertNotEqual(Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[0],'T')
        (self.state/'owner').write_text(owner)
        result=self.run_script('stop.sh');self.assertEqual(result.returncode,0,result.stderr)

    def test_wrong_visible_filesystem_and_writable_ram_parent_refuse(self):
        common=self.root/'common.sh'
        original=common.read_text()
        for replacement in (original.replace("printf '4d44\\n'","printf 'ef53\\n'"),
                            original.replace("printf '0 0 755\\n'","printf '0 0 777\\n'")):
            common.write_text(replacement);self.sums()
            self.assertNotEqual(self.run_script('start.sh').returncode,0)
            self.assertFalse(self.state.exists())

    def test_active_child_refuses_stop_and_resumes_owned_master(self):
        self.fork.touch()
        result=self.run_script('start.sh');self.assertEqual(result.returncode,0,result.stderr)
        result=self.run_script('stop.sh');self.assertNotEqual(result.returncode,0)
        self.assertIn('sessions are active',result.stderr)
        pid=int((self.state/'dropbear.pid').read_text())
        self.assertNotEqual(Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[0],'T')
        child=int(self.childfile.read_text());os.kill(child,signal.SIGTERM);time.sleep(0.05)
        result=self.run_script('stop.sh');self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main()
