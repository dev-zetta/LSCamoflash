"""Synthetic vendor callback ABI/lifecycle state, never executable firmware."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/rtsp_callback_fixture.c'
CASES = ('abi', 'bad-buffer-length', 'callsite', 'unarmed', 'fork-owner',
         'not-initialized', 'missing-handles', 'busy-start', 'foreign-callback',
         'deadline', 'attempt-budget', 'clock-failure', 'join-teardown',
         'stop-teardown', 'other-lifecycle-calls', 'drain-inflight', 'wrong-elf-env', 'identity')


class RTSPCallbackTests(unittest.TestCase):
    def run_fixture(self, arm):
        cc = (os.environ.get('RTSP_ARM_CC') or os.environ.get('BACKUP_ARM_CC')) if arm else shutil.which('cc')
        qemu = (os.environ.get('RTSP_QEMU') or os.environ.get('BACKUP_QEMU')) if arm else None
        if not cc or (arm and not qemu):
            self.skipTest('Set RTSP_ARM_CC and RTSP_QEMU for ARM926 fixtures' if arm else 'Host C compiler required')
        with tempfile.TemporaryDirectory(prefix='camoflash-rtsp-') as temporary:
            binary = Path(temporary) / 'fixture'
            command = [cc, '-std=c99', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror', '-O2']
            if arm:
                command += ['-static', '-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
            subprocess.run(command + [str(FIXTURE), '-ldl', '-pthread', '-o', str(binary)], check=True,
                           capture_output=True, text=True)
            prefix = [qemu, '-cpu', 'arm926'] if arm else []
            for case in CASES:
                with self.subTest(architecture='ARM926' if arm else 'host', case=case):
                    result = subprocess.run(prefix + [str(binary), case], capture_output=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'PASS')

    def run_preload_smoke(self, arm):
        cc = (os.environ.get('RTSP_ARM_CC') or os.environ.get('BACKUP_ARM_CC')) if arm else shutil.which('cc')
        qemu = (os.environ.get('RTSP_QEMU') or os.environ.get('BACKUP_QEMU')) if arm else None
        if not cc or (arm and not qemu):
            self.skipTest('Set RTSP_ARM_CC and RTSP_QEMU for ARM926 preload smoke' if arm else 'Host C compiler required')
        flags = ['-std=c99', '-Wall', '-Wextra', '-Werror', '-O2']
        if arm:
            flags += ['-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
        with tempfile.TemporaryDirectory(prefix='camoflash-preload-') as temporary:
            library = Path(temporary) / 'libcamoflash_rtsp.so'
            binary = Path(temporary) / 'passthrough'
            production = ROOT / 'SOURCE/src/contrib/rtsp-callback/rtsp_callback.c'
            smoke = ROOT / 'tests/fixtures/rtsp_preload_fixture.c'
            subprocess.run([cc] + flags + ['-fPIC', '-shared', str(production), '-ldl', '-pthread', '-o', str(library)],
                           check=True, capture_output=True, text=True)
            subprocess.run([cc] + flags + [str(smoke), '-pthread', '-o', str(binary)],
                           check=True, capture_output=True, text=True)
            env = dict(os.environ)
            env.pop('LD_PRELOAD', None)
            env.pop('LSCAMOFLASH_RTSP_PROFILE', None)
            for profile in ('3007325.5', 'wrong-profile'):
                with self.subTest(architecture='ARM926' if arm else 'host', profile=profile):
                    if arm:
                        sysroot = subprocess.check_output([cc, '-print-sysroot'], text=True).strip()
                        command = [qemu, '-cpu', 'arm926', '-L', sysroot, '-E', 'LD_PRELOAD=' + str(library),
                                   '-E', 'LSCAMOFLASH_RTSP_PROFILE=' + profile, str(binary)]
                        # QEMU user-mode cannot exec an ARM child on hosts without
                        # binfmt registration; this fixture supplies its own QEMU
                        # prefix through an environment value for the child exec.
                        env['RTSP_FIXTURE_QEMU'] = str(qemu)
                        env['RTSP_FIXTURE_SYSROOT'] = sysroot
                    else:
                        command = [str(binary)]
                        env.update(LD_PRELOAD=str(library), LSCAMOFLASH_RTSP_PROFILE=profile)
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), ['CHILD-PASS', 'PASS'])
                    self.assertEqual(result.stderr, '')

    def run_early_dependency(self, arm):
        cc = (os.environ.get('RTSP_ARM_CC') or os.environ.get('BACKUP_ARM_CC')) if arm else shutil.which('cc')
        qemu = (os.environ.get('RTSP_QEMU') or os.environ.get('BACKUP_QEMU')) if arm else None
        if not cc or (arm and not qemu):
            self.skipTest('Set RTSP_ARM_CC and RTSP_QEMU for ARM926 dependency constructors' if arm else 'Host C compiler required')
        flags = ['-std=c99', '-Wall', '-Wextra', '-Werror', '-O2']
        if arm:
            flags += ['-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
        with tempfile.TemporaryDirectory(prefix='camoflash-early-dependency-') as temporary:
            root = Path(temporary)
            library = root / 'libcamoflash_rtsp.so'
            dependency = root / 'libearly-dependency.so'
            binary = root / 'early-main'
            production = ROOT / 'SOURCE/src/contrib/rtsp-callback/rtsp_callback.c'
            dependency_source = ROOT / 'tests/fixtures/rtsp_early_dependency.c'
            main_source = ROOT / 'tests/fixtures/rtsp_early_dependency_main.c'
            subprocess.run([cc] + flags + ['-fPIC', '-shared', str(production), '-ldl', '-pthread', '-o', str(library)],
                           check=True, capture_output=True, text=True)
            subprocess.run([cc] + flags + ['-fPIC', '-shared', '-Wl,-soname,libearly-dependency.so',
                                          str(dependency_source), '-pthread', '-o', str(dependency)],
                           check=True, capture_output=True, text=True)
            subprocess.run([cc] + flags + ['-fno-pic', '-no-pie', '-Wl,--export-dynamic',
                                          str(main_source), '-L' + str(root), '-Wl,-rpath,$ORIGIN',
                                          '-learly-dependency', '-pthread', '-o', str(binary)],
                           check=True, capture_output=True, text=True)
            clean_env = dict(os.environ)
            clean_env.pop('LD_PRELOAD', None)
            clean_env.pop('LSCAMOFLASH_RTSP_PROFILE', None)
            clean_env.pop('LD_LIBRARY_PATH', None)
            for profile in ('', 'wrong-profile', '3007325.5'):
                with self.subTest(architecture='ARM926' if arm else 'host', profile=profile or 'absent'):
                    env = dict(clean_env, RTSP_FIXTURE_EXPECT_PROFILE=profile)
                    if arm:
                        sysroot = subprocess.check_output([cc, '-print-sysroot'], text=True).strip()
                        command = [qemu, '-cpu', 'arm926', '-L', sysroot,
                                   '-E', 'LD_PRELOAD=' + str(library), str(binary)]
                        if profile:
                            command[5:5] = ['-E', 'LSCAMOFLASH_RTSP_PROFILE=' + profile]
                    else:
                        command = [str(binary)]
                        env['LD_PRELOAD'] = str(library)
                        if profile:
                            env['LSCAMOFLASH_RTSP_PROFILE'] = profile
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), ['EARLY-DEPENDENCY PASS', 'SYNTHETIC-MAIN PASS'])
                    self.assertEqual(result.stderr, '')

    def test_host_early_dependency_constructor_mutual_exclusion(self):
        self.run_early_dependency(False)

    def test_arm926_early_dependency_constructor_mutual_exclusion(self):
        self.run_early_dependency(True)

    def test_host_shared_preload_passthrough(self):
        self.run_preload_smoke(False)

    def test_arm926_shared_preload_passthrough(self):
        self.run_preload_smoke(True)

    def test_host_callback_abi_and_lifecycle(self):
        self.run_fixture(False)

    def test_arm926_callback_abi_and_lifecycle(self):
        self.run_fixture(True)


if __name__ == '__main__':
    unittest.main()
