import copy
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generator', ROOT / 'tools/generate_board.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / '演示/项目进度.json').read_text())

    def reject(self, *, modify):
        modify(self.data)
        with self.assertRaises(ValueError):
            generator.validate(data=self.data)

    def test_empty_and_demo(self):
        generator.validate(data=json.loads((ROOT / '项目进度.json').read_text()))
        generator.validate(data=self.data)

    def test_duplicate_ids(self):
        self.reject(modify=lambda d: d['tasks'].append(copy.deepcopy(d['tasks'][0])))

    def test_unknown_requirement(self):
        self.reject(modify=lambda d: d['tasks'][0].update(requirement_ids=['missing']))

    def test_missing_dependency(self):
        self.reject(modify=lambda d: d['tasks'][0].update(dependencies=['missing']))

    def test_dependency_cycle(self):
        self.reject(modify=lambda d: d['tasks'][0].update(dependencies=['T-003']))

    def test_done_requires_implementation(self):
        self.reject(modify=lambda d: d['tasks'][0].update(implemented=False))

    def test_done_requires_acceptance(self):
        self.reject(modify=lambda d: d['tasks'][0].update(acceptance_result='待验证'))

    def test_done_requires_evidence(self):
        self.reject(modify=lambda d: d['tasks'][0].update(acceptance_evidence=' '))

    def test_done_requires_checks(self):
        self.reject(modify=lambda d: d['tasks'][0].update(verification=[]))

    def test_failed_check_rejects_done(self):
        self.reject(modify=lambda d: d['tasks'][0]['verification'][0].update(result='未通过'))

    def test_pending_check_rejects_done(self):
        self.reject(modify=lambda d: d['tasks'][0]['verification'][0].update(result='待验证'))

    def test_done_cannot_have_blocker(self):
        self.reject(modify=lambda d: d['tasks'][0].update(blocked_reason='等待确认'))

    def test_done_cannot_have_remaining_items(self):
        self.reject(modify=lambda d: d['tasks'][0].update(remaining_items=['未检查']))

    def test_invalid_change_reference(self):
        self.reject(modify=lambda d: d['changes'][0].update(task_ids=['missing']))

    def test_draft_cannot_complete(self):
        self.reject(modify=lambda d: d['requirements'][0].update(confirmation='待确认'))

    def test_generation_escape_and_offline_dependencies(self):
        attack = '</script><script>alert("x")</script>&中文'
        self.data['project']['name'] = attack
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.json'
            output = Path(directory) / 'board.html'
            source.write_text(json.dumps(self.data))
            generator.generate(source=source, output=output)
            html = output.read_text()
            self.assertNotIn(attack, html)
            payload = re.search(r'<script id="board-data" type="application/json">(.*?)</script>', html, re.S)[1]
            self.assertEqual(json.loads(payload)['project']['name'], attack)
            self.assertNotRegex(html, r'(?:src|href)=["\']https?://')
            self.assertNotIn('fetch(', html)
            self.assertNotIn('innerHTML', html)

    def test_failure_keeps_previous_html(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.json'
            output = Path(directory) / 'board.html'
            output.write_text('previous valid board')
            self.data['tasks'][0]['verification'] = []
            source.write_text(json.dumps(self.data))
            with self.assertRaises(ValueError):
                generator.generate(source=source, output=output)
            self.assertEqual(output.read_text(), 'previous valid board')
            source.write_text('{malformed')
            with self.assertRaises(ValueError):
                generator.generate(source=source, output=output)
            self.assertEqual(output.read_text(), 'previous valid board')

    def test_input_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.html'
            original = json.dumps(self.data)
            source.write_text(original)
            with self.assertRaises(ValueError):
                generator.generate(source=source, output=source)
            self.assertEqual(source.read_text(), original)


if __name__ == '__main__':
    unittest.main()
