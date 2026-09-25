import hashlib
from pathlib import Path
import re
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
class ReferenceInventoryTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'framework/agent_skills/v2/prompts/shared/agent_transport.md').read_text()
        code=next(b for b in re.findall(r'```python\n(.*?)```',source,re.S) if 'def build_release_executable_references(' in b)
        ns={}
        exec(compile(code,'agent_transport.md','exec'),ns)
        self.build=ns['build_release_executable_references']
        self.verify=ns['verify_release_executable_references']
        self.release=yaml.safe_load((ROOT/'framework/agent_skills/v2/contracts/release.yaml').read_text())
        self.refs=self.build(self.release,str(ROOT),lambda p:Path(p).read_bytes())

    def test_real_release_has_all_helpers_and_templates(self):
        self.assertEqual(set(self.refs),set(self.release['helpers'])|set(self.release['templates']))
        ref=self.refs['erd_validation_utils']
        self.assertEqual(ref['sha256'],hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest())
        self.verify({'templates':self.refs},self.refs)

    def test_v17_omission_rejected_before_freeze(self):
        partial={k:v for k,v in self.refs.items() if k in self.release['templates']}
        with self.assertRaisesRegex(RuntimeError,'erd_validation_utils'):
            self.verify({'templates':partial,'helpers':self.refs},self.refs)

    def test_missing_helper_bytes_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'missing/empty executable'):
            self.build(self.release,str(ROOT),lambda p:None)

    def test_conflicting_reference_rejected(self):
        actual=dict(self.refs,erd_validation_utils={'path':'/wrong','sha256':'0'*64})
        with self.assertRaisesRegex(RuntimeError,'erd_validation_utils'):
            self.verify({'templates':actual},self.refs)

    def test_release_key_collision_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'duplicate executable key'):
            self.build({'helpers':{'x':'a'},'templates':{'x':'b'}},'/repo',lambda p:b'code')
