"""Fresh-process lifecycle in an isolated skill copy; no live rollback."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'skill'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'tests').mkdir()
        shutil.copy2(ROOT / 'scripts/evolve.py', self.root / 'scripts/evolve.py')
        (self.root / 'SKILL.md').write_text('---\nname: thesis-delivery-zh\ndescription: test\n---\n测试', encoding='utf-8')
        (self.root / 'tests/test_example.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_behavior(self): self.assertEqual(1+1,2)\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args, expect=0):
        proc = subprocess.run([sys.executable, '-X', 'utf8', str(self.root / 'scripts/evolve.py'), *args], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def issue(self):
        issue = {'trigger': '独立列表开始', 'failure': '编号起点不符合当前配置', 'root_cause': '边界未分开', 'scope': 'general',
                 'remedy': '独立选择范围', 'exceptions': '用户指定续号', 'check': '默认与续号分别符合配置', 'regression_test': 'tests/test_example.py'}
        path = self.root / 'issue.json'; path.write_text(json.dumps(issue, ensure_ascii=False), encoding='utf-8')
        return path

    def test_record_dedup_transition_reload_and_deprecate(self):
        path = self.issue()
        item = self.call('record', '--issue', str(path))
        self.assertEqual(item['status'], 'pending_analysis')
        self.assertEqual(self.call('record', '--issue', str(path))['duplicate'], item['id'])
        self.call('transition', '--id', item['id'], '--status', 'pending_validation', '--note', '已修复')
        self.call('transition', '--id', item['id'], '--status', 'active', '--note', '失败和正常对照已验证')
        loaded = self.call('list')
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]['status'], 'active')
        self.assertEqual(loaded[0]['validation']['status'], 'pass')
        self.assertEqual(loaded[0]['effective_status'], 'active')
        (self.root / 'SKILL.md').write_text('changed after validation', encoding='utf-8')
        self.assertEqual(self.call('list')[0]['effective_status'], 'pending_validation')
        self.call('transition', '--id', item['id'], '--status', 'deprecated', '--note', '规则合并')
        self.assertEqual(self.call('list')[0]['status'], 'deprecated')

    def test_release_failed_upgrade_and_restore(self):
        release = self.call('release', '--version', '1.0.0')
        self.assertEqual(release['status'], 'released')
        original = (self.root / 'SKILL.md').read_bytes()
        (self.root / 'tests/test_example.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_behavior(self): self.fail("bad upgrade")\n', encoding='utf-8')
        self.call('release', '--version', '1.0.1', expect=1)
        self.assertFalse((self.root / 'evolution/releases/1.0.1.zip').exists())
        (self.root / 'SKILL.md').write_text('broken candidate', encoding='utf-8')
        self.assertEqual(self.call('rollback', '--version', '1.0.0')['status'], 'restored')
        self.assertEqual((self.root / 'SKILL.md').read_bytes(), original)
        self.assertTrue(list((self.root / 'evolution/backups').glob('*.zip')))

    def test_no_tests_refuses_release(self):
        (self.root / 'tests/test_example.py').unlink()
        self.call('release', '--version', '1.0.0', expect=1)

    def test_secret_rejected(self):
        path = self.issue(); data = json.loads(path.read_text(encoding='utf-8'))
        data['failure'] = 'api_key=sk-notarealkey12345678'
        path.write_text(json.dumps(data), encoding='utf-8')
        self.call('record', '--issue', str(path), expect=1)

    def test_release_version_immutable(self):
        self.call('release', '--version', '1.0.0')
        self.call('release', '--version', '1.0.0', expect=1)

    def test_concurrent_writer_refused_without_deleting_lock(self):
        (self.root / 'evolution').mkdir()
        lock = self.root / 'evolution/.lock'; lock.write_text('test-held-lock')
        self.call('record', '--issue', str(self.issue()), expect=1)
        self.assertTrue(lock.exists())

    def test_fresh_process_uses_learned_rule_and_preserves_normal_case(self):
        for name in ('audit_common.py', 'inspect_docx.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        # The agent implements a demonstrated feedback in a persistent rule resource.
        rule = {'selectors': {'body': {'tables': [0]}}, 'text_rules': [{'id': 'learned_guidance', 'kind': 'review',
                'scope': 'body', 'pattern': '内部写作提醒', 'suggestion': '按句子用途复核'}]}
        path = self.root / 'learned.json'; path.write_text(json.dumps(rule), encoding='utf-8')
        from test_audits import fixture, tbl, p
        bad = self.root / 'bad.docx'; fixture(bad, tbl(p('内部写作提醒')))
        normal = self.root / 'normal.docx'; fixture(normal, tbl(p('公开数据仅覆盖本期，结论限于此范围。')))
        cmd = [sys.executable, '-X', 'utf8', str(self.root / 'scripts/inspect_docx.py')]
        proc = subprocess.run(cmd + [str(bad), '--config', str(path)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)['findings'][0]['code'], 'learned_guidance')
        proc = subprocess.run(cmd + [str(normal), '--config', str(path)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
