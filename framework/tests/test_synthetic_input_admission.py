import hashlib
from unittest.mock import Mock
import unittest
from test_v2_release_workflow import ROOT, PROMPTS, prompt_functions
from test_v2_portability import runtime

class SyntheticInputAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.admit=prompt_functions(PROMPTS/'data_layer/validation.md')['admit_synthetic_inputs']
        self.template=(ROOT/'framework/templates/dbldatagen_notebook.py.template').read_bytes()
        self.digest=hashlib.sha256(self.template).hexdigest()
        self.tables=runtime.encode({'tables':[{'name':'entity','columns':[{'name':'id'}]}]})
        self.valid={'tables':[{'name':'entity','rows':10,'pk_columns':['id'],'domain_columns':{},'fk_columns':{}}]}

    def test_persisted_spec_shapes_rejected_before_deploy(self):
        for doc in ({},{'tables':None},{'tables':[]},{'tables':{}},
                    {'tables':{'entity':{'rows':10}}},{'synthetic_data':self.valid}):
            with self.subTest(doc=doc):
                deploy=Mock()
                with self.assertRaisesRegex(RuntimeError,'tables: expected a nonempty list'):
                    self.admit(self.template,self.digest,runtime.encode(doc),self.tables,runtime.decode)
                    deploy()
                deploy.assert_not_called()

    def test_valid_readback_returns_exact_hashes(self):
        raw=runtime.encode(self.valid)
        result=self.admit(self.template,self.digest,raw,self.tables,runtime.decode)
        self.assertEqual(result['synthetic_spec_sha256'],hashlib.sha256(raw).hexdigest())

    def test_template_drift_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'template digest mismatch'):
            self.admit(self.template,'0'*64,runtime.encode(self.valid),self.tables,runtime.decode)

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate YAML key'):
            self.admit(self.template,self.digest,b'tables: []\ntables: []\n',self.tables,runtime.decode)
