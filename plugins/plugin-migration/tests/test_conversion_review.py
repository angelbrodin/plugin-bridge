"""Conversion candidates, bounded accounting and selected package generation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import audit_repo as audit
import migration_plan as planner
from apply_plan import apply_migration, PlanError


class ConversionReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()

    def put(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value) if isinstance(value, dict) else value)
        return p

    def scan(self, route='plugin-install', version='unknown'):
        return audit.Auditor(self.root, version, route).run()

    def test_metadata_is_conditional_not_a_verified_conversion(self):
        self.put('skills/review/SKILL.md', '---\nname: review\ndescription: Review\ndisable-model-invocation: true\nallowed-tools: Read\n---\nReview files.')
        r = self.scan(version=audit.PINNED_VERSION)
        f = next(f for f in r['findings'] if f['rule_id'] == 'REVIEW003')
        self.assertEqual(f['line'], 4)
        self.assertEqual(f['status'], 'review_required')
        self.assertIsNone(f['applicability']['verified_version'])
        self.assertEqual(r['file_accounting'][0]['disposition'], 'not_assessed')

    def test_metadata_in_body_is_not_frontmatter(self):
        self.put('skills/a/SKILL.md', '---\nname: a\ndescription: a\n---\nExample:\nmodel: some-model\n')
        self.assertFalse(any(f['rule_id'] == 'REVIEW003' for f in self.scan()['findings']))

    def test_packaging_agents_and_user_inputs_have_review_ids(self):
        self.put('plugins/a/.claude-plugin/plugin.json', {'name': 'a', 'userConfig': {'token': {'default': 'DO_NOT_REPORT'}}})
        self.put('plugins/a/agents/review.md', '---\nname: review\n---\nReview files.')
        r = self.scan()
        rules = {f['rule_id'] for f in r['findings']}
        self.assertTrue({'REVIEW001', 'REVIEW002', 'REVIEW004'} <= rules)
        self.assertNotIn('DO_NOT_REPORT', json.dumps(r))
        self.assertTrue(all(f['status'] == 'review_required' for f in r['findings']))

    def test_native_mcp_wrapped_and_flat_configs_require_context(self):
        server = {'command': 'python', 'args': ['server.py'], 'env': {'MCP_TOKEN': 'DO_NOT_REPORT'}}
        self.put('plugins/a/.mcp.json', {'mcpServers': {'a': server}})
        self.put('plugins/b/.mcp.json', {'b': server})
        r = self.scan()
        candidates = [f for f in r['findings'] if f['rule_id'] == 'REVIEW005']
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(f['status'] == 'review_required' for f in candidates))
        self.assertNotIn('DO_NOT_REPORT', json.dumps(r))
        self.assertFalse(any(f['rule_id'] == 'REVIEW005' for f in self.scan('standalone-import')['findings']))

    def test_accounting_includes_support_files_and_exclusions(self):
        self.put('skills/a/SKILL.md', 'Do a task.')
        self.put('scripts/helper.py', 'pass')
        self.put('node_modules/dependency/index.js', 'not inspected')
        self.put('invalid.json', '{')
        (self.root/'alias').symlink_to(self.root/'scripts/helper.py')
        r = self.scan()
        rows = {f['path']: f for f in r['file_accounting']}
        self.assertEqual(rows['skills/a/SKILL.md']['scan_status'], 'no_matches')
        self.assertEqual(rows['scripts/helper.py']['scan_status'], 'not_checked')
        self.assertEqual(rows['invalid.json']['scan_status'], 'needs_review')
        self.assertEqual(rows['alias']['scan_status'], 'not_checked')
        self.assertIn('node_modules', rows)
        self.assertNotIn('node_modules/dependency/index.js', rows)
        self.assertTrue(all(f['disposition'] == 'not_assessed' for f in rows.values()))
        self.assertTrue(all(f['runtime_validation'] == 'not_run' for f in rows.values()))

    def test_accounting_markdown_does_not_render_html_in_paths(self):
        self.put('<img src=x>|notes.txt', 'hello')
        rendered = audit.markdown(self.scan())
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;img', rendered)
        self.assertIn('&#124;', rendered)

    def package_plan(self):
        for name in ('a', 'b'):
            self.put('plugins/'+name+'/.claude-plugin/plugin.json', {'name': name})
            self.put('plugins/'+name+'/skills/review/SKILL.md', '---\nname: review\ndescription: Review files\n---\nReview the requested files.')
        r = self.scan()
        raw = (json.dumps(r)+'\n').encode()
        audit_path = self.base/'audit.json'
        audit_path.write_bytes(raw)
        catalog = {'schema_version': 1, 'audit_sha256': hashlib.sha256(raw).hexdigest(),
                   'plugins': [{'id': n, 'name': n, 'path': 'plugins/'+n} for n in ('a','b')], 'items': []}
        for i,n in enumerate(('a','b'), 1):
            finding = next(f for f in r['findings'] if f['path'] == 'plugins/'+n+'/.claude-plugin/plugin.json')
            contents = {
                'codex-packages/'+n+'/.codex-plugin/plugin.json': json.dumps({'name': n, 'skills': './skills/'}),
                'codex-packages/'+n+'/skills/review/SKILL.md': (self.root/'plugins'/n/'skills/review/SKILL.md').read_text()}
            catalog['items'].append({'id':'M00'+str(i), 'plugin_id':n, 'title':'Generate selected package',
                'status':'ready', 'problem':'Review separate target layout', 'solution':'Generate a separate package',
                'claude_impact':'Original files retained; runtime tests pending', 'next_step':'Validate target loader',
                'changes':[{'path':path, 'expected_sha256':None, 'finding_ids':[finding['id']],
                            'rationale':'Selected separate output with retained source', 'content':content} for path,content in contents.items()]})
        plan = planner.select(catalog,r,raw,plugin_names=['a'])
        plan_path = self.base/'plan.json'
        plan_path.write_text(json.dumps(plan))
        return r, audit_path, plan_path

    def test_generated_package_selection_preserves_every_source_file(self):
        r, a, p = self.package_plan()
        source = {f['path']:(self.root/f['path']).read_bytes() for f in r['inventory']}
        apply_migration(self.root,a,p)
        self.assertFalse((self.root/'codex-packages').exists())
        apply_migration(self.root,a,p,write=True,receipt_path=self.base/'receipt.json')
        self.assertTrue((self.root/'codex-packages/a/.codex-plugin/plugin.json').is_file())
        self.assertFalse((self.root/'codex-packages/b').exists())
        for path, data in source.items():
            self.assertEqual((self.root/path).read_bytes(),data)

    def test_generated_package_refuses_stale_source(self):
        r,a,p = self.package_plan()
        self.put('plugins/a/skills/review/SKILL.md','New user changes')
        with self.assertRaises(PlanError):
            apply_migration(self.root,a,p,write=True,receipt_path=self.base/'receipt.json')
        self.assertFalse((self.root/'codex-packages').exists())
        self.assertEqual((self.root/'plugins/a/skills/review/SKILL.md').read_text(),'New user changes')


if __name__ == '__main__':
    unittest.main()
