import copy
from pathlib import Path
import tempfile
import unittest
from test_v2_portability import runtime

class FrozenContextAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.context={'run_id':'run','target':{'catalog':'cat','schema':'sch'},'checkpointing':{},'phases_completed':[]}
        self.context['checkpointing']['frozen_run_contract_sha256']=runtime.frozen_context_sha256(self.context)

    def test_mutable_changes_keep_digest(self):
        candidate=copy.deepcopy(self.context)
        candidate.update(status='failed', findings=['diagnostic'], current_step='data',
                         retry_attempt=1, error='failure',completed_at='timestamp')
        runtime.verify_frozen_context(candidate,'/run_context.yaml')
        self.assertEqual(runtime.frozen_context_sha256(candidate),runtime.frozen_context_sha256(self.context))

    def test_immutable_changes_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'run_context.yaml')
            store=runtime.LocalStore()
            store.write(path,runtime.encode(self.context))
            before=store.read(path)
            candidate=copy.deepcopy(self.context)
            candidate['target']['schema']='changed'
            with self.assertRaisesRegex(RuntimeError,'recorded_sha256=.*actual_sha256='):
                store.write(path,runtime.encode(candidate))
            self.assertEqual(store.read(path),before)

    def test_unapproved_top_level_metadata_is_frozen(self):
        self.context['last_updated']='new'
        with self.assertRaisesRegex(RuntimeError,'frozen context mismatch'):
            runtime.verify_frozen_context(self.context,'/run_context.yaml')

    def test_digest_function_does_not_mutate(self):
        before=copy.deepcopy(self.context)
        runtime.frozen_context_sha256(self.context)
        self.assertEqual(self.context,before)
