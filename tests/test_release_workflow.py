"""Execute actual publish workflow blocks with synthetic assets and a fake gh."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
VERSION = '2.00.0000'
SHA = 'a' * 40
REPOSITORY = 'fixture-owner/LSCamoflash'
ASSETS = {f'LSCamoflash-{VERSION}-uclibc.tar.gz', f'update-{VERSION}-uclibc.tgz',
          f'LSCamoflash-{VERSION}-backup-kit.tar.gz', f'LSCamoflash-{VERSION}-source.tar.gz',
          f'LSCamoflash-{VERSION}-fullhan.tar.gz', f'LSCamoflash-{VERSION}-yyos.tar.gz', 'LICENSE.MIT', 'COPYING.BusyBox',
          'THIRD_PARTY_NOTICES.md', 'SHA256SUMS'}
NOTES = 'Current major release.\n\n### Fullhan\n\nExperimental manual management and ONVIF.\n'
FAKE_GH = '''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args=sys.argv[1:]
root=pathlib.Path(os.environ['FAKE_ROOT'])
with (root/'calls.jsonl').open('a') as stream:stream.write(json.dumps(args)+'\\n')
repo=os.environ['GH_REPO']; sha=os.environ['GITHUB_SHA']; version=os.environ['FAKE_VERSION']
if args==['api','repos/'+repo+'/actions/runs/'+os.environ['BUILD_RUN_ID']]:
    print((root/'build.json').read_text())
elif args==['run','download',os.environ['BUILD_RUN_ID'],'--name','LSCamoflash-release-'+sha,'--dir','release']:
    shutil.copytree(root/'fixture-assets','release',symlinks=True)
elif args==['api','repos/'+repo+'/git/matching-refs/tags/v'+version]:
    print((root/'tags.json').read_text())
elif args[:3]==['release','create','v'+version]:
    (root/'create.json').write_text(json.dumps(args))
    (root/'captured-notes.md').write_text(pathlib.Path(args[args.index('--notes-file')+1]).read_text())
elif args==['release','view','v'+version,'--json','apiUrl','--jq','.apiUrl']:
    print('https://api.github.com/repos/'+repo+'/releases/987')
elif args==['api','repos/'+repo+'/releases/987']:
    print((root/'draft.json').read_text())
elif args==['release','edit','v'+version,'--draft=false','--latest']:
    (root/'published.json').write_text(json.dumps(args))
else:
    raise SystemExit('Unexpected fake gh arguments')
'''


def workflow_blocks():
    """Read the workflow's literal run blocks without a YAML dependency."""
    text = (REPO / '.github/workflows/release.yml').read_text()
    matches = re.findall(r'^        run: \|\n((?:          .*\n|[ \t]*\n)*)', text, re.M)
    blocks = [''.join(line[10:] if line.startswith(' ' * 10) else '\n'
                      for line in match.splitlines(keepends=True)) for match in matches]
    if len(blocks) != 3 or any('${{' in block for block in blocks):
        raise AssertionError('Expected three literal publish shell blocks using environment variables')
    return blocks


@unittest.skipUnless(shutil.which('bash') and shutil.which('sha256sum'), 'Bash and SHA256 tools required')
class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='release-workflow-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.blocks = workflow_blocks()

    def run_case(self, name, *, build=None, mutation=None, existing_tag=False):
        work = self.root / name
        work.mkdir()
        (work / 'SOURCE').mkdir()
        (work / 'SOURCE/version.txt').write_text(VERSION + '\n')
        (work / 'CHANGELOG.md').write_text('# Changelog\n\n## [' + VERSION + '] - 2026-10-14\n\n' + NOTES + '\n## [1.03.2413]\n\nOld release history must not publish.\n')
        tools = work / 'tools'
        tools.mkdir()
        (tools / 'gh').write_text(FAKE_GH)
        (tools / 'gh').chmod(0o755)
        assets = work / 'fixture-assets'
        assets.mkdir()
        for asset in ASSETS - {'SHA256SUMS'}:
            (assets / asset).write_bytes(('synthetic ' + asset + '\n').encode())
        (assets / 'SHA256SUMS').write_text(''.join(hashlib.sha256((assets / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                                                for name in sorted(ASSETS - {'SHA256SUMS'})))
        if mutation == 'missing-fullhan':
            (assets / f'LSCamoflash-{VERSION}-fullhan.tar.gz').unlink()
        elif mutation == 'missing-yyos':
            (assets / f'LSCamoflash-{VERSION}-yyos.tar.gz').unlink()
        elif mutation == 'unexpected-asset':
            (assets / 'private.bin').write_bytes(b'must never publish\n')
        elif mutation == 'corrupt-checksum':
            (assets / f'LSCamoflash-{VERSION}-uclibc.tar.gz').write_bytes(b'corrupted\n')
        elif mutation == 'incomplete-checksums':
            lines = (assets / 'SHA256SUMS').read_text().splitlines(keepends=True)
            (assets / 'SHA256SUMS').write_text(''.join(lines[:-1]))
        run = {'head_sha': SHA, 'head_repository': {'full_name': REPOSITORY}, 'head_branch': 'main',
               'path': '.github/workflows/makefile.yml', 'status': 'completed', 'conclusion': 'success', 'event': 'push'}
        run.update(build or {})
        (work / 'build.json').write_text(json.dumps(run))
        (work / 'tags.json').write_text(json.dumps([{'ref': 'refs/tags/v' + VERSION}] if existing_tag else []))
        draft = {'tag_name': 'v' + VERSION, 'target_commitish': SHA, 'draft': True, 'prerelease': False,
                 'assets': [{'name': path.name, 'state': 'uploaded', 'size': path.stat().st_size,
                             'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}
                            for path in sorted(assets.iterdir())]}
        if mutation == 'wrong-target':
            draft['target_commitish'] = 'b' * 40
        elif mutation == 'wrong-digest':
            draft['assets'][0]['digest'] = 'sha256:' + '0' * 64
        elif mutation == 'missing-digest':
            del draft['assets'][0]['digest']
        elif mutation == 'wrong-size':
            draft['assets'][0]['size'] += 1
        elif mutation == 'missing-remote-asset':
            draft['assets'].pop()
        elif mutation == 'unfinished-upload':
            draft['assets'][0]['state'] = 'new'
        (work / 'draft.json').write_text(json.dumps(draft))
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.defpath,
                   GH_TOKEN='synthetic-not-a-real-token', GH_REPO=REPOSITORY, GITHUB_SHA=SHA,
                   GITHUB_API_URL='https://api.github.com', BUILD_RUN_ID='12345', FAKE_ROOT=str(work), FAKE_VERSION=VERSION)
        exits = []
        for block in self.blocks:
            result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', block],
                                    cwd=work, env=env, capture_output=True, text=True, timeout=10)
            exits.append(result.returncode)
            if result.returncode:
                break
        calls = [json.loads(line) for line in (work / 'calls.jsonl').read_text().splitlines()]
        return work, exits, calls

    def test_only_exact_successful_trusted_main_build_can_reach_asset_download(self):
        controls = {'wrong-commit': {'head_sha': 'b' * 40},
                    'foreign-repository': {'head_repository': {'full_name': 'foreign/LSCamoflash'}},
                    'wrong-workflow': {'path': '.github/workflows/release.yml'},
                    'wrong-branch': {'head_branch': 'feature'}, 'failed-build': {'conclusion': 'failure'},
                    'pending-build': {'status': 'in_progress'}, 'untrusted-event': {'event': 'pull_request'}}
        for name, build in controls.items():
            with self.subTest(case=name):
                work, exits, calls = self.run_case(name, build=build)
                self.assertNotEqual(exits[-1], 0)
                self.assertFalse(any(call[:2] == ['run', 'download'] for call in calls))
                self.assertFalse((work / 'create.json').exists())

    def test_complete_public_inventory_and_checksums_gate_all_release_writes(self):
        for mutation in ('missing-fullhan', 'missing-yyos', 'unexpected-asset', 'corrupt-checksum', 'incomplete-checksums'):
            with self.subTest(case=mutation):
                work, exits, calls = self.run_case(mutation, mutation=mutation)
                self.assertNotEqual(exits[-1], 0)
                self.assertFalse((work / 'create.json').exists())
                self.assertFalse(any('/git/matching-refs/' in argument for call in calls for argument in call))

    def test_existing_exact_tag_is_never_overwritten(self):
        work, exits, _ = self.run_case('existing-tag', existing_tag=True)
        self.assertNotEqual(exits[-1], 0)
        self.assertFalse((work / 'create.json').exists())

    def test_wrong_draft_target_digest_size_or_upload_inventory_never_publishes(self):
        for mutation in ('wrong-target', 'wrong-digest', 'missing-digest', 'wrong-size', 'missing-remote-asset', 'unfinished-upload'):
            with self.subTest(case=mutation):
                work, exits, calls = self.run_case(mutation, mutation=mutation)
                self.assertNotEqual(exits[-1], 0)
                self.assertTrue((work / 'create.json').exists())
                self.assertFalse((work / 'published.json').exists())
                self.assertFalse(any(call[:2] == ['release', 'edit'] for call in calls))

    def test_valid_release_has_current_notes_ten_assets_exact_target_and_verified_draft(self):
        work, exits, calls = self.run_case('valid')
        self.assertEqual(exits, [0, 0, 0])
        expected = ['release', 'create', 'v' + VERSION] + ['release/' + name for name in sorted(ASSETS)] + [
            '--target', SHA, '--title', 'LSCamoflash ' + VERSION, '--notes-file', 'release-notes.md', '--draft']
        self.assertEqual(json.loads((work / 'create.json').read_text()), expected)
        self.assertEqual((work / 'captured-notes.md').read_text(), NOTES)
        self.assertEqual(json.loads((work / 'published.json').read_text()), ['release', 'edit', 'v' + VERSION, '--draft=false', '--latest'])
        create = next(i for i, call in enumerate(calls) if call[:2] == ['release', 'create'])
        verify = calls.index(['api', 'repos/' + REPOSITORY + '/releases/987'])
        publish = next(i for i, call in enumerate(calls) if call[:2] == ['release', 'edit'])
        self.assertLess(create, verify)
        self.assertLess(verify, publish)


if __name__ == '__main__':
    unittest.main()
