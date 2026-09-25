import copy
import hashlib
import unittest
from unittest.mock import Mock
from test_v2_release_workflow import PROMPTS, prompt_functions
from test_v2_portability import runtime

class DDLTargetEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.admit = prompt_functions(PROMPTS/'data_layer/validation.md')['admit_ddl_target_envelope']
        self.context = {'target':{'catalog':'configured_catalog','schema':'configured_schema'},
                        'version':{'asset_suffix':'_v5'},'run_id':'run-5','output_folder':'/outputs/v5'}
        self.handoff = dict(self.context['target'],asset_suffix='_v5',run_id='run-5',output_folder='/outputs/v5')
        self.spec = dict(self.context['target'],asset_suffix='_v5',tables=[{'name':'entity','columns':[]}])

    def test_missing_null_wrong_and_unexpanded_coordinates_block_deployment(self):
        for field in ('catalog','schema','asset_suffix'):
            for value in (None,'','wrong','{{TARGET_CATALOG}}'):
                with self.subTest(field=field,value=value):
                    spec=copy.deepcopy(self.spec);spec[field]=value
                    deploy=Mock()
                    with self.assertRaisesRegex(RuntimeError,'DDL_INPUT_AUTHORITY_ERROR: spec.'):
                        self.admit(runtime.encode(spec),self.context,self.handoff,runtime.decode)
                        deploy()
                    deploy.assert_not_called()
            spec=copy.deepcopy(self.spec);del spec[field]
            with self.assertRaisesRegex(RuntimeError,'DDL_INPUT_AUTHORITY_ERROR'):
                self.admit(runtime.encode(spec),self.context,self.handoff,runtime.decode)

    def test_exact_persisted_bytes_are_admitted(self):
        raw=runtime.encode(self.spec)
        self.assertEqual(self.admit(raw,self.context,self.handoff,runtime.decode),
                         {'table_spec_sha256':hashlib.sha256(raw).hexdigest()})

    def test_handoff_mismatch_rejected(self):
        for field in self.handoff:
            handoff=dict(self.handoff);handoff[field]='different'
            with self.subTest(field=field),self.assertRaisesRegex(RuntimeError,'handoff.'):
                self.admit(runtime.encode(self.spec),self.context,handoff,runtime.decode)

    def test_legacy_suffix_conflict_rejected(self):
        self.spec['version_suffix']='_v4'
        with self.assertRaisesRegex(RuntimeError,'conflicting legacy'):
            self.admit(runtime.encode(self.spec),self.context,self.handoff,runtime.decode)

    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate YAML key'):
            self.admit(b'catalog: first\ncatalog: second\n',self.context,self.handoff,runtime.decode)
