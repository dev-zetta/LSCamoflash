#!/usr/bin/env python3
"""NOR dumper fixtures use regular files and never open physical MTD devices."""
import hashlib, json, os, pathlib, shlex, shutil, subprocess, tempfile, time, unittest
REPO = pathlib.Path(__file__).resolve().parents[1]
QEMU = os.environ.get('BACKUP_QEMU')
ARM_BB = os.environ.get('BACKUP_ARM_BUSYBOX')
HOST_BB = shutil.which(os.environ.get('HOST_BUSYBOX', 'busybox'))
SOURCE = (REPO / 'tools/firmware-backup/backup-nor.sh').read_text()
PROCESS_SNAPSHOT_CASES={'process-snapshot','process-comm-race','process-maps-race','process-maps-partial'}
YYOS_CASES={'yyos-userspace','yyos-process-snapshot','yyos-process-exit','yyos-process-maps-partial','yyos-process-exe-race','yyos-process-name-rejected','yyos-process-pid-rejected'}
SUCCESS_CASES={'ok','nor256','nor256-stacked','stacked-tmpfs','stacked-tmpfs-reversed','stacked-other-device','wide-device-number','run-collision'} | PROCESS_SNAPSHOT_CASES | YYOS_CASES
MOUNT_FAILURE_CASES={'not-sd','visible-non-fat','visible-wrong-device','visible-ro','stacked-rw-ro','duplicate-sd','sd-stat-error'}
NOR256_CASES=['nor256','nor256-stacked','nor256-nand','nor256-oob','nor256-zero','nor256-unsupported','nor256-erase-unaligned','nor256-size-unaligned','nor256-erase-division']
def fixture(case, target=False):
    with tempfile.TemporaryDirectory(prefix='backup-dumper-') as directory:
        root=pathlib.Path(directory)
        proc=root/'proc'; sys=root/'sys'; dev=root/'dev'; fs=root/'rootfs'; sd=root/'sd'
        for p in (proc,sys/'class/mtd',dev,fs/'bin',fs/'lib',fs/'usr/bin',fs/'etc',sd):p.mkdir(parents=True,exist_ok=True)
        (proc/'uptime').symlink_to('/proc/uptime')
        (dev/'mmcblk0p1').write_bytes(b'fixture SD source')
        (dev/'mmcblk1p1').write_bytes(b'fixture other SD source')
        (proc/'mounts').write_text(f'{dev}/mmcblk0p1 {sd} vfat rw,noatime 0 0\n')
        (proc/'mtd').write_text('dev: size erasesize name\nmtd0: 00001000 00001000 "UBOOT"\nmtd1: 00002000 00001000 "APP"\n')
        for n,size in ((0,4096),(1,8192)):
            p=sys/'class/mtd'/f'mtd{n}';p.mkdir()
            for key,val in {'type':'nor','size':size,'erasesize':4096,'writesize':1,'oobsize':0,'dev':'0:0','name':('UBOOT' if n==0 else 'APP'),'offset':n*4096}.items():(p/key).write_text(str(val)+'\n')
            (dev/f'mtd{n}').write_bytes(bytes(range(256))*(size//256))
        (fs/'usr/bin/anyka_ipc').write_bytes(b'FAKE-STOCK-APP\x00')
        (fs/'lib/libavssdkbeta.so').write_bytes(b'FAKE-MATCHING-LIB\x00')
        (fs/'lib/libalias.so').symlink_to('libavssdkbeta.so')
        (fs/'etc/fixture.conf').write_text('not-a-real-secret\n')
        if case in PROCESS_SNAPSHOT_CASES:
            process=proc/'2135';process.mkdir()
            (process/'comm').write_text('anyka_ipc\n')
            (process/'maps').write_text('fixture-process-mapping\n')
            (process/'exe').symlink_to(fs/'usr/bin/anyka_ipc')
        if case in YYOS_CASES:
            for directory in (fs/'appfs/bin',fs/'appfs/script',fs/'appfs/lib',fs/'config'):directory.mkdir(parents=True,exist_ok=True)
            (fs/'appfs/bin/yy_cam').write_bytes(b'FAKE-YYOS-APP\x00')
            (fs/'appfs/script/start.sh').write_text('#!/bin/sh\n# synthetic startup; never execute\nexit 99\n')
            (fs/'appfs/lib/libyy.so').write_bytes(b'FAKE-YYOS-MATCHING-LIB\x00')
            (fs/'appfs/lib/libalias.so').symlink_to('libyy.so')
            (fs/'config/param.conf').write_text('PRIVATE-SYNTHETIC-YYOS-FIXTURE\n')
            if case!='yyos-userspace':
                process=proc/('2135bad' if case=='yyos-process-pid-rejected' else '2135');process.mkdir()
                (process/'comm').write_text('yy_cam/../../invalid\n' if case=='yyos-process-name-rejected' else 'yy_cam\n')
                (process/'maps').write_text('fixture-yyos-process-mapping\n')
                (process/'exe').symlink_to(fs/'appfs/bin/yy_cam')
        s=SOURCE
        for key,val in [('PROC',proc),('SYS',sys),('DEV',dev),('FS_ROOT',fs)]:
            s=s.replace(key+'=/'+{'PROC':'proc','SYS':'sys','DEV':'dev','FS_ROOT':''}[key]+'\n',key+'='+str(val)+'\n',1)
        block_check='[ -b "$mount_source" ] || continue # FIXTURE_BLOCK_CHECK'
        assert block_check in s
        s=s.replace(block_check, '[ -f "$mount_source" ] || continue # FIXTURE_BLOCK_CHECK',1)
        s=s.replace('[ -c "$dev" ] && [ -r "$dev" ] || die', '[ -f "$dev" ] && [ -r "$dev" ] || die')
        if case=='type-missing':(sys/'class/mtd/mtd1/type').unlink()
        if case=='size-cap':(proc/'mtd').write_text('dev: size erasesize name\nmtd0: 10000000 00001000 "TOO_BIG"\n')
        if case=='nand':(sys/'class/mtd/mtd1/type').write_text('nand\n')
        if case=='geometry':(sys/'class/mtd/mtd1/size').write_text('4096\n')
        if case.startswith('nor256'):
            for n in (0,1):(sys/f'class/mtd/mtd{n}/writesize').write_text('256\n')
        if case=='nor256-nand':(sys/'class/mtd/mtd1/type').write_text('nand\n')
        if case=='nor256-oob':(sys/'class/mtd/mtd1/oobsize').write_text('16\n')
        if case=='nor256-zero':(sys/'class/mtd/mtd1/writesize').write_text('0\n')
        if case=='nor256-unsupported':(sys/'class/mtd/mtd1/writesize').write_text('128\n')
        if case in ('nor256-erase-unaligned','nor256-size-unaligned','nor256-erase-division'):
            size,erase={'nor256-erase-unaligned':(8192,4095),'nor256-size-unaligned':(8191,4096),'nor256-erase-division':(8192,3840)}[case]
            (sys/'class/mtd/mtd1/size').write_text(str(size)+'\n')
            (sys/'class/mtd/mtd1/erasesize').write_text(str(erase)+'\n')
            (proc/'mtd').write_text('dev: size erasesize name\nmtd0: 00001000 00001000 "UBOOT"\n'+f'mtd1: {size:08x} {erase:08x} "APP"\n')
        if case=='devnum':(sys/'class/mtd/mtd1/dev').write_text('90:2\n')
        if case=='short-read':(dev/'mtd1').write_bytes(b'x'*4096)
        if case=='extra-sysfs':
            p=sys/'class/mtd/mtd2';p.mkdir()
        if case=='not-sd':(proc/'mounts').write_text(f'{dev}/mtdblock0 {sd} jffs2 rw 0 0\n')
        sd_row=f'{dev}/mmcblk0p1 {sd} vfat rw,noatime 0 0\n'
        tmpfs_row=f'tmpfs {sd} tmpfs rw,nosuid 0 0\n'
        if case in ('stacked-tmpfs','nor256-stacked'):(proc/'mounts').write_text(tmpfs_row+sd_row)
        if case=='stacked-tmpfs-reversed':(proc/'mounts').write_text(sd_row+tmpfs_row)
        if case=='stacked-other-device':(proc/'mounts').write_text(f'{dev}/mmcblk1p1 {sd} vfat rw 0 0\n'+sd_row)
        if case=='visible-ro':(proc/'mounts').write_text(sd_row.replace('rw,noatime','ro,noatime'))
        if case=='stacked-rw-ro':(proc/'mounts').write_text(sd_row+sd_row.replace('rw,noatime','ro,noatime'))
        if case=='duplicate-sd':(proc/'mounts').write_text(sd_row+sd_row)
        if case=='deadline':
            s=s.replace('TOTAL_BUDGET_SECONDS=240','TOTAL_BUDGET_SECONDS=0')
        if case=='timeout':
            s=s.replace('dd) command_seconds=30','dd) command_seconds=1')
        existing_runs={}
        if case in ('run-collision','run-collision-exhausted'):
            prefix='run-fixture-collision'
            original='run_prefix=$BASE/run-$(tool date -u +%Y%m%dT%H%M%SZ)-$$'
            assert original in s
            s=s.replace(original,'run_prefix=$BASE/'+prefix,1)
            for number in range(64 if case=='run-collision-exhausted' else 1):
                prior=sd/'firmware-backup'/(prefix+('-'+str(number) if number else ''))
                prior.mkdir(parents=True)
                (prior/'status.txt').write_text('VERIFIED_NOR_BACKUP original-run\n')
                (prior/'preserved.bin').write_bytes(b'previous verified evidence\x00')
                existing_runs[prior.name]={p.name:p.read_bytes() for p in prior.iterdir()}
        script=root/'dump.sh';script.write_text(s)
        bb=sd/'busybox'
        prefix=f'{shlex.quote(str(QEMU))} -cpu arm926 {shlex.quote(str(ARM_BB))}' if target else shlex.quote(str(HOST_BB))
        # Fixtures use regular files, not real block devices or mounts. Only the SD
        # stat responses are substituted; production matching and arithmetic run.
        major,minor=(427,74565) if case=='wide-device-number' else (179,1)
        encoded=(minor&0xff)|((major&0xfff)<<8)|((minor&0xfff00)<<12)
        visible_encoded=encoded if case!='visible-wrong-device' else os.makedev(179,2)
        visible_type='ef53' if case=='visible-non-fat' else '4d44'
        stat_behavior=(
            'if [ "$1" = stat ]; then\n'
            f'  if [ "${{2-}}" = -f ] && [ "${{3-}}" = -c ] && [ "${{4-}}" = %t ] && [ "${{5-}}" = "{sd}" ]; then '
            + ('exit 7' if case=='sd-stat-error' else f'echo {visible_type}; exit 0')+'; fi\n'
            f'  if [ "${{2-}}" = -c ] && [ "${{3-}}" = %d ] && [ "${{4-}}" = "{sd}" ]; then echo {visible_encoded}; exit 0; fi\n'
            f'  if [ "${{2-}}" = -c ] && [ "${{3-}}" = %t:%T ] && [ "${{4-}}" = "{dev}/mmcblk0p1" ]; then echo {major:x}:{minor:x}; exit 0; fi\n'
            f'  if [ "${{2-}}" = -c ] && [ "${{3-}}" = %t:%T ] && [ "${{4-}}" = "{dev}/mmcblk1p1" ]; then echo b3:2; exit 0; fi\n'
            'fi\n')
        bb.write_text('#!/bin/sh\nif [ "$1" = id ] && [ "${2-}" = -u ]; then echo 0; exit 0; fi\n'+stat_behavior+'exec '+prefix+' "$@"\n');bb.chmod(0o755)
        command=([str(QEMU),'-cpu','arm926',str(ARM_BB),'ash'] if target else [str(HOST_BB),'ash'])+[str(script),str(sd)]
        # Intercept only dd in a copied helper dispatcher; all other commands are real applets.
        if case=='timeout':
            real=sd/'real-busybox';bb.rename(real)
            bb.write_text(f'#!/bin/sh\nif [ "$1" = dd ]; then exec /bin/sleep 5; fi\nexec "{real}" "$@"\n');bb.chmod(0o755)
            # timeout invokes this wrapper instead of the real BusyBox, so it times the actual hung reader.
        if case in ['wc-error','unstable']:
            real=sd/'real-busybox';bb.rename(real)
            if case=='wc-error':
                behavior='if [ "$1" = wc ]; then exit 7; fi\n'
            else:
                behavior='if [ "$1" = dd ]; then\n  out=\n  for arg do case "$arg" in of=*) out=${arg#of=};; esac; done\n  "'+str(real)+'" "$@" || exit $?\n  case "$out" in *read2.part) "'+str(real)+'" dd if=/dev/zero of="$out" bs=4096 count=1 2>/dev/null;; esac\n  exit 0\nfi\n'
            bb.write_text('#!/bin/sh\n'+behavior+'exec "'+str(real)+'" "$@"\n');bb.chmod(0o755)
        race_marker=root/'process-race-triggered'
        if case in ('process-comm-race','process-maps-race','process-maps-partial','yyos-process-exit','yyos-process-maps-partial','yyos-process-exe-race'):
            real=sd/'real-busybox';bb.rename(real)
            vanished=proc/'2135'/('comm' if case in ('process-comm-race','yyos-process-exit') else 'exe' if case=='yyos-process-exe-race' else 'maps')
            applet='readlink' if case=='yyos-process-exe-race' else 'cat'
            behavior=(
                f'if [ "$1" = {applet} ] && [ "${{2-}}" = "{vanished}" ]; then\n'
                + (f'  "{real}" rm -rf "{proc}/2135" || exit $?\n' if case=='yyos-process-exit' else f'  "{real}" rm -f "$2" || exit $?\n')
                + f'  printf "triggered\\n" > "{race_marker}"\n'
                + ('  printf "incomplete-process-mapping\\n"; exit 7\n' if case in ('process-maps-partial','yyos-process-maps-partial','yyos-process-exe-race') else '')
                + 'fi\n')
            bb.write_text('#!/bin/sh\n'+behavior+f'exec "{real}" "$@"\n');bb.chmod(0o755)
        before={str(p.relative_to(dev)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dev.iterdir() if p.is_file()}
        yyos_before={str(p.relative_to(fs)):hashlib.sha256(p.read_bytes()).hexdigest() for tree in ('appfs','config') for p in (fs/tree).rglob('*') if p.is_file() and not p.is_symlink()}
        t=time.monotonic();r=subprocess.run(command,cwd='/',stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=45)
        duration=time.monotonic()-t
        after={str(p.relative_to(dev)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dev.iterdir() if p.is_file()}
        yyos_after={str(p.relative_to(fs)):hashlib.sha256(p.read_bytes()).hexdigest() for tree in ('appfs','config') for p in (fs/tree).rglob('*') if p.is_file() and not p.is_symlink()}
        all_runs=list((sd/'firmware-backup').glob('run-*')) if (sd/'firmware-backup').exists() else []
        preserved=all({p.name:p.read_bytes() for p in (sd/'firmware-backup'/name).iterdir()}==files for name,files in existing_runs.items())
        runs=[p for p in all_runs if p.name not in existing_runs]
        run=runs[0] if runs else None
        log=(run/'run.log').read_text() if run and (run/'run.log').exists() else ''
        status=(run/'status.txt').read_text() if run and (run/'status.txt').exists() else ''
        ok=(r.returncode==0) if case in SUCCESS_CASES else (r.returncode!=0)
        ok=ok and before==after and yyos_before==yyos_after and preserved and not (sd/'.firmware-backup.lock').exists()
        ok=ok and 'PRIVATE-SYNTHETIC-YYOS-FIXTURE' not in r.stdout+r.stderr
        if case=='run-collision':
            ok=ok and len(runs)==1 and run.name=='run-fixture-collision-1'
        if case=='run-collision-exhausted':
            ok=ok and not runs and 'No unused backup run directory' in r.stderr
        if case in SUCCESS_CASES:
            ok=ok and status.startswith('VERIFIED_NOR_BACKUP')
            if case in PROCESS_SNAPSHOT_CASES:
                maps=run/'meta/anyka_ipc-2135-maps.txt'
                exe=run/'meta/anyka_ipc-2135-exe.txt'
                if case=='process-snapshot':
                    ok=ok and maps.read_text()=='fixture-process-mapping\n' and exe.read_text().strip()==str(fs/'usr/bin/anyka_ipc')
                else:
                    ok=ok and race_marker.read_text()=='triggered\n' and not maps.exists()
                    ok=ok and (not exe.exists() if case=='process-comm-race' else exe.read_text().strip()==str(fs/'usr/bin/anyka_ipc'))
            if case in YYOS_CASES:
                maps=run/'meta/yy_cam-2135-maps.txt';exe=run/'meta/yy_cam-2135-exe.txt'
                if case in ('yyos-userspace','yyos-process-exit','yyos-process-name-rejected','yyos-process-pid-rejected'):
                    ok=ok and not list((run/'meta').glob('yy_cam*'))
                else:
                    ok=ok and (not maps.exists() if case=='yyos-process-maps-partial' else maps.read_text()=='fixture-yyos-process-mapping\n')
                    ok=ok and (not exe.exists() if case=='yyos-process-exe-race' else exe.read_text().strip()==str(fs/'appfs/bin/yy_cam'))
                if case in ('yyos-process-exit','yyos-process-maps-partial','yyos-process-exe-race'):
                    ok=ok and race_marker.read_text()=='triggered\n'
            if case.startswith('nor256'):
                import csv
                with (run/'partitions.tsv').open() as stream:
                    ok=ok and all(row['type']=='nor' and row['write_bytes']=='256' and row['oob_bytes']=='0' for row in csv.DictReader(stream,delimiter='\t'))
                for n in (0,1):ok=ok and (run/f'meta/mtd{n}/writesize').read_text().strip()=='256'
            for n in [0,1]:
                for read in [1,2]:
                    ok=ok and (run/f'partitions/mtd{n}/read{read}.bin').read_bytes()==(dev/f'mtd{n}').read_bytes()
            import tarfile
            if run is None:
                print({'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode});raise AssertionError('No output run')
            with tarfile.open(run/'stock-userspace.tar') as a:
                ok=ok and a.extractfile('usr/bin/anyka_ipc').read()==(fs/'usr/bin/anyka_ipc').read_bytes()
                ok=ok and a.extractfile('lib/libavssdkbeta.so').read()==(fs/'lib/libavssdkbeta.so').read_bytes()
                ok=ok and a.getmember('lib/libalias.so').issym()
                if case in YYOS_CASES:
                    for path in ('appfs/bin/yy_cam','appfs/script/start.sh','appfs/lib/libyy.so','config/param.conf'):
                        ok=ok and a.extractfile(path).read()==(fs/path).read_bytes()
                    ok=ok and a.getmember('appfs/lib/libalias.so').issym()
        else:
            ok=ok and not status.startswith('VERIFIED_NOR_BACKUP')
            if case in MOUNT_FAILURE_CASES:
                ok=ok and run is None and not (sd/'firmware-backup').exists()
            if run and case not in ['timeout','deadline','not-sd']:
                ok=ok and (run/'stock-userspace.tar').exists()
            if case.startswith('nor256'):
                ok=ok and not (run/'read-attempts.tsv').exists()
        item={'case':case,'shell':'ARM BusyBox/QEMU' if target else 'host BusyBox','exit_code':r.returncode,'duration_seconds':round(duration,3),'pass':ok,'fixture':str(root),'status':status.strip(),'stdout':r.stdout.strip(),'stderr':r.stderr.strip(),'log_tail':log[-1200:] if not ok else ''}
        if not ok:raise AssertionError(item)

HOST_CASES = ['ok','nand','type-missing','geometry','devnum','size-cap','short-read','unstable','wc-error','extra-sysfs','not-sd','deadline','timeout','stacked-tmpfs','stacked-tmpfs-reversed','stacked-other-device','wide-device-number','visible-non-fat','visible-wrong-device','visible-ro','stacked-rw-ro','duplicate-sd','sd-stat-error','run-collision','run-collision-exhausted'] + NOR256_CASES + sorted(PROCESS_SNAPSHOT_CASES) + sorted(YYOS_CASES)
ARM_CASES = ['ok','nand','short-read','unstable','wc-error','timeout','stacked-tmpfs','wide-device-number','visible-non-fat','visible-wrong-device','visible-ro','stacked-rw-ro','duplicate-sd','run-collision','run-collision-exhausted'] + NOR256_CASES + sorted(PROCESS_SNAPSHOT_CASES) + sorted(YYOS_CASES)

class DumperTests(unittest.TestCase):
    pass


def add_case(name, arm):
    def test(self):
        if arm and not all((QEMU, ARM_BB)):
            self.skipTest('Set BACKUP_ARM_BUSYBOX and BACKUP_QEMU for ARM926 tests')
        if not arm and not HOST_BB:
            self.skipTest('Host BusyBox is required')
        fixture(name, arm)
    setattr(DumperTests, 'test_' + ('arm_' if arm else 'host_') + name.replace('-', '_'), test)


for name in HOST_CASES:
    add_case(name, False)
for name in ARM_CASES:
    add_case(name, True)

if __name__ == '__main__':
    unittest.main()
