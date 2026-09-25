"""Failed synthetic-spec validation preserves predecessor records across real reopen."""
import copy
from pathlib import Path
import tempfile
import unittest
import uuid
from test_v2_portability import runtime

class FailedPhaseResumeTests(unittest.TestCase):
    def test_synthetic_failure_reopen_preserves_all_predecessor_records_and_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            store=runtime.LocalStore()
            args=dict(registry_path=root+'/version_registry.yaml',domain='example',
                      output_root=root+'/outputs',created_by='genie_code',run_id=str(uuid.uuid4()),store=store)
            selection=runtime.resolve_version(**args)
            context={k:v for k,v in selection.items() if k not in ('is_new','version_suffix')}
            context.update(version={'number':selection['version'],'asset_suffix':selection['version_suffix']},
                           target={'catalog':'cat','schema':'sch'},checkpointing={},phases_completed=[])
            names=('parse_erd','build_semantic_model','generate_ddl','reconcile_schema')
            for name in names:
                context['phases_completed'].append({'step':'create_data_layer','phase':name,
                    'checkpoint_status':'VALID','completed_at':'2026-09-25T00:00:00Z',
                    'output_fingerprints':[]})
            output=selection['output_folder']
            context['phases_completed'][-1]['output_fingerprints']=[
                {'id':'schema_reconciliation_artifact','kind':'RAW_BYTES','locator':output+'/schema_reconciliation.yaml','sha256':'a'*64},
                {'id':'schema_reconciliation_catalog_readback','kind':'CATALOG_READBACK','locator':'table_spec:cat.sch:_v1','sha256':'b'*64}]
            # These records test preservation, not complete Resume Skip Gate acceptance.
            context['checkpointing']['frozen_run_contract_sha256']=runtime.frozen_context_sha256(context)
            store.write(selection['run_context_path'],runtime.encode(context))
            artifacts={}
            for name in ('erd_parsed.yaml','semantic_model.yaml','table_spec.yaml','schema_reconciliation.yaml'):
                artifacts[name]=('original '+name).encode()
                store.write(output+'/'+name,artifacts[name])
            before=copy.deepcopy(context['phases_completed'])
            runtime.commit_terminal(store=store,registry_path=args['registry_path'],run_context_path=selection['run_context_path'],
                manifest=dict(context,status='failed',error={'phase':'generate_synthetic_data','failure_code':'SYNTHETIC_SPEC_ERROR'}))
            resumed=runtime.resolve_version(**dict(args,mode='retry',run_id=str(uuid.uuid4())))
            current=runtime.authenticate_context(store,selection['run_context_path'])
            self.assertFalse(resumed['is_new'])
            self.assertEqual(resumed['run_id'],selection['run_id'])
            self.assertEqual(current['phases_completed'],before)
            self.assertEqual(current['retry_attempt'],1)
            for name,raw in artifacts.items(): self.assertEqual(store.read(output+'/'+name),raw)
            history=runtime.decode(store.read(output+'/.lifecycle/attempt_0_manifest.json'))
            self.assertEqual(history['error']['phase'],'generate_synthetic_data')
