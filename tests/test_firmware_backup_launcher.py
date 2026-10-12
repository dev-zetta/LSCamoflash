#!/usr/bin/env python3
"""Hermetic launcher regressions; fixture binaries never become package inputs."""
import hashlib, json, os, pathlib, resource, shlex, shutil, signal, subprocess, tempfile, time, unittest
REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / 'tools/firmware-backup/hostapd.c'
HOST_CC = os.environ.get('HOST_CC', 'cc')
HOST_BB = shutil.which(os.environ.get('HOST_BUSYBOX', 'busybox'))
CC = os.environ.get('BACKUP_ARM_CC')
QEMU = os.environ.get('BACKUP_QEMU')
ARM_BB = os.environ.get('BACKUP_ARM_BUSYBOX')
HOST_CASES = ['ok','stacked-tmpfs','stacked-tmpfs-reversed','stacked-ro-underlay','stacked-read-only','stacked-same-device-ro','wrong-fs','read-only','wrong-source','duplicate','root-symlink','log-symlink','log-fifo','log-too-large','busybox-symlink','busybox-fifo','dump-symlink','dump-fifo','exec-failure','exec-permission','closed-stdio','ignored-sigchld','quiet','log-cap','cancel']
ARM_CASES = ['ok','stacked-tmpfs','stacked-tmpfs-reversed','stacked-read-only','log-fifo','busybox-fifo','exec-failure','closed-stdio','ignored-sigchld','quiet','cancel']

def case(name,arm=False):
 with tempfile.TemporaryDirectory(prefix='backup-launcher-') as directory:
  root=pathlib.Path(directory);sd=root/'sd';dev=root/'dev';proc=root/'proc'
  for p in [sd,dev,proc]:p.mkdir()
  (dev/'mmcblk0p1').write_bytes(b'FAKE-SD-MOUNT')
  mounts=f'{dev}/mmcblk0p1 {sd} vfat rw,noatime 0 0\n';(proc/'mounts').write_text(mounts)
  bb=sd/'busybox'
  if arm:
   bb.write_text(f'#!/bin/sh\nexec {shlex.quote(str(QEMU))} -cpu arm926 {shlex.quote(str(ARM_BB))} "$@"\n');bb.chmod(0o755)
  else:shutil.copy2(HOST_BB,bb)
  dump=sd/'dump.sh';dump.write_text('#!/bin/sh\nprintf "DUMPER_ENTERED\\n"\nprintf "called" > "$1/fixture-called"\nprintf "FINAL_CHILD_STDERR\\n" >&2\nexit 7\n')
  dump.chmod(0o644)
  outside=root/'outside';outside.write_bytes(b'unchanged')
  if name=='stacked-tmpfs':(proc/'mounts').write_text(f'tmpfs {sd} tmpfs rw,relatime 0 0\n'+mounts)
  if name=='stacked-tmpfs-reversed':(proc/'mounts').write_text(mounts+f'tmpfs {sd} tmpfs rw,relatime 0 0\n')
  if name=='stacked-ro-underlay':(proc/'mounts').write_text(f'/dev/mtdblock2 {sd} squashfs ro,relatime 0 0\n'+mounts)
  if name=='stacked-read-only':(proc/'mounts').write_text(f'tmpfs {sd} tmpfs rw,relatime 0 0\n'+mounts.replace(' rw,',' ro,'))
  if name=='stacked-same-device-ro':(proc/'mounts').write_text(mounts+mounts.replace(' rw,',' ro,'))
  if name=='wrong-fs':(proc/'mounts').write_text(mounts.replace(' vfat ',' ext4 '))
  if name=='read-only':(proc/'mounts').write_text(mounts.replace(' rw,',' ro,'))
  if name=='wrong-source':(proc/'mounts').write_text(mounts.replace('mmcblk0p1','mtdblock0'))
  if name=='duplicate':(proc/'mounts').write_text(mounts+mounts)
  if name=='root-symlink':sd.rename(root/'real-sd');sd.symlink_to(root/'real-sd')
  if name=='log-symlink':(sd/'backup-launcher.log').symlink_to(outside)
  if name=='log-fifo':os.mkfifo(sd/'backup-launcher.log')
  if name=='log-too-large':(sd/'backup-launcher.log').write_bytes(b'x'*65537)
  if name=='busybox-symlink':bb.unlink();bb.symlink_to(outside)
  if name=='busybox-fifo':bb.unlink();os.mkfifo(bb)
  if name=='dump-symlink':dump.unlink();dump.symlink_to(outside)
  if name=='dump-fifo':dump.unlink();os.mkfifo(dump)
  if name=='exec-failure':bb.write_text('invalid executable content\n');bb.chmod(0o755)
  if name=='exec-permission':bb.chmod(0o644)
  if name=='log-cap':dump.write_text('#!/bin/sh\nhead -c 100000 /dev/zero\nexit 0\n')
  if name=='quiet':dump.write_text('#!/bin/sh\nexec > "$1/quiet.log" 2>&1\nsleep 1\nexit 7\n')
  if name=='cancel':dump.write_text('#!/bin/sh\nprintf "DUMPER_ENTERED\\n"\necho $$ > "$1/child-pid"\nsleep 30 &\necho $! > "$1/grandchild-pid"\nwait\n')
  binary=root/'launcher'
  args=[str(CC) if arm else HOST_CC,'-Os','-std=c99','-Wall','-Wextra','-Werror',f'-DLAUNCHER_FIXTURE_ROOT="{root}"',str(SOURCE),'-o',str(binary)]
  if arm:args[1:1]=['-static','-march=armv5te','-mtune=arm926ej-s','-mfloat-abi=soft','-marm']
  subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  command=([str(QEMU),'-cpu','arm926'] if arm else [])+[str(binary),'-B','/etc/config/hostapd.conf']
  before=outside.read_bytes();t=time.monotonic();cpu_before=resource.getrusage(resource.RUSAGE_CHILDREN)
  def close_stdio():
   for fd in range(3):
    try:os.close(fd)
    except OSError:pass
  def ignored_sigchld():signal.signal(signal.SIGCHLD,signal.SIG_IGN)
  p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=close_stdio if name=='closed-stdio' else (ignored_sigchld if name=='ignored-sigchld' else None))
  if name=='cancel':
   deadline=time.monotonic()+5
   while time.monotonic()<deadline and not (sd/'grandchild-pid').exists():time.sleep(.02)
   p.send_signal(signal.SIGTERM)
  try:stdout,stderr=p.communicate(timeout=8)
  except subprocess.TimeoutExpired:
   p.terminate()
   try:p.communicate(timeout=3)
   except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=3)
   raise
  elapsed=time.monotonic()-t
  logp=sd/'backup-launcher.log';log=logp.read_text(errors='replace') if logp.exists() and logp.is_file() and not logp.is_symlink() else ''
  size=logp.stat().st_size if logp.exists() and logp.is_file() else 0
  cpu_after=resource.getrusage(resource.RUSAGE_CHILDREN);cpu_seconds=(cpu_after.ru_utime+cpu_after.ru_stime)-(cpu_before.ru_utime+cpu_before.ru_stime)
  if name in ['ok','stacked-tmpfs','stacked-tmpfs-reversed','stacked-ro-underlay','closed-stdio','ignored-sigchld']:
   ok=p.returncode==7 and all(x in log for x in ['NATIVE_ENTRY','EXEC_START','DUMPER_ENTERED','FINAL_CHILD_STDERR','CHILD_EXIT code=7']) and (sd/'fixture-called').exists()
  elif name=='quiet':ok=p.returncode==7 and 'CHILD_EXIT code=7' in log and elapsed>=.9 and cpu_seconds<.4
  elif name in ['exec-failure','exec-permission']:
   ok=p.returncode==126 and 'NATIVE_ENTRY' in log and 'EXEC_ERROR errno=' in log and 'CHILD_EXIT code=126' in log
  elif name=='log-cap':ok=p.returncode==0 and size<=65536 and 'CHILD_EXIT code=0' in log
  elif name=='cancel':
   ok=p.returncode==143 and 'CANCELLED signal=15 child-reaped=yes' in log and 'CHILD_SIGNAL signal=15' in log
   for file in ['child-pid','grandchild-pid']:
    pid=int((sd/file).read_text())
    try:
     os.kill(pid,0)
     state=pathlib.Path(f'/proc/{pid}/stat').read_text().split()[2]
     ok=ok and state=='Z' # A dead grandchild can await host init reaping.
    except ProcessLookupError:pass
  else:ok=p.returncode!=0 and not (sd/'fixture-called').exists()
  ok=ok and outside.read_bytes()==before
  item={'case':name,'architecture':'ARM926/QEMU' if arm else 'native host','exit_code':p.returncode,'seconds':round(elapsed,3),'cpu_seconds':round(cpu_seconds,3),'log_bytes':size,'pass':ok,'fixture':str(root),'stderr':stderr.strip(),'log_tail':log[-400:] if not ok else ''}
  if not ok:raise AssertionError(item)

class LauncherTests(unittest.TestCase):
    pass


def add_case(name, arm):
    def test(self):
        if arm and not all((CC, QEMU, ARM_BB)):
            self.skipTest('Set BACKUP_ARM_CC, BACKUP_ARM_BUSYBOX and BACKUP_QEMU for ARM926 tests')
        if not arm and (not HOST_BB or not shutil.which(HOST_CC)):
            self.skipTest('Host C compiler and BusyBox are required')
        case(name, arm)
    setattr(LauncherTests, 'test_' + ('arm_' if arm else 'host_') + name.replace('-', '_'), test)


for name in HOST_CASES:
    add_case(name, False)
for name in ARM_CASES:
    add_case(name, True)

if __name__ == '__main__':
    unittest.main()
