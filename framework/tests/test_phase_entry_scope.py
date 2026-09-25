"""Prompt gate regression: no generated-output I/O for new phases.

Controlled phase outputs, not an LLM or live Databricks execution.
"""
import unittest
from unittest.mock import Mock
from test_v2_release_workflow import PROMPTS, prompt_functions

PHASES = {
    'create_data_layer': ['parse_erd','build_semantic_model','generate_ddl','reconcile_schema','generate_synthetic_data','validate_data'],
    'create_metric_views': ['profile_schema','map_kpis','plan_metric_views','design_metric_views','create_intermediate_views','generate_metric_views','validate_metric_views'],
    'create_dashboards': ['profile_metrics','design_dashboard','build_datasets','create_dashboard','validate_publish'],
    'create_genie_space': ['profile_metrics','design_instructions','generate_sql','create_genie_space','validate_genie'],
    'generate_documentation': ['generate_documentation','validate_documentation'],
}

class PhaseEntryScopeTests(unittest.TestCase):
    def setUp(self):
        self.classify=prompt_functions(PROMPTS/'shared/state_contract.md')['classify_phase_entry']

    def test_new_pipeline_never_verifies_unproduced_outputs(self):
        records=[]
        persisted={}
        for step,phases in PHASES.items():
            for phase in phases:
                with self.subTest(step=step,phase=phase):
                    self.assertEqual(self.classify(records,step,phase),'EXECUTE_NEW')
                    # Reader deliberately fails on any output not yet produced.
                    read=Mock(side_effect=lambda identity: persisted[identity])
                    route=self.classify(records,step,phase)
                    if route == 'VERIFY_CHECKPOINT':
                        read((step,phase))
                    read.assert_not_called()
                    persisted[(step,phase)]=b'controlled producer output'
                    # Actual stages validate and persist full checkpoint records; this
                    # fixture tests entry routing only, not complete gate acceptance.
                    records.append({'step':step,'phase':phase,'checkpoint_status':'VALID'})
                    self.assertEqual(self.classify(records,step,phase),'VERIFY_CHECKPOINT')
                    self.assertEqual(read((step,phase)),b'controlled producer output')

    def test_missing_checkpoint_after_attempt_requires_recovery(self):
        self.assertEqual(self.classify([],'create_data_layer','generate_synthetic_data',True),'RECOVER_ATTEMPT')

    def test_stale_not_treated_as_fresh(self):
        records=[{'step':'create_data_layer','phase':'generate_ddl','checkpoint_status':'STALE'}]
        self.assertEqual(self.classify(records,'create_data_layer','generate_ddl'),'RECOVER_STALE')
        self.assertEqual(self.classify(records,'create_data_layer','parse_erd'),'EXECUTE_NEW')

    def test_same_phase_name_in_sibling_is_not_a_candidate(self):
        records=[{'step':'create_dashboards','phase':'profile_metrics','checkpoint_status':'VALID'}]
        self.assertEqual(self.classify(records,'create_genie_space','profile_metrics'),'EXECUTE_NEW')

    def test_malformed_and_duplicate_records_block(self):
        record={'step':'create_data_layer','phase':'parse_erd','checkpoint_status':'VALID'}
        for records in ([record,record],[None],[dict(record,checkpoint_status='completed')]):
            with self.subTest(records=records),self.assertRaisesRegex(RuntimeError,'PHASE_ENTRY_ERROR'):
                self.classify(records,'create_data_layer','parse_erd')

    def test_all_stage_instructions_route_phase_entry(self):
        for stage in ('data_layer','metric_views','dashboards','genie','documentation'):
            text=(PROMPTS/stage/'instructions.md').read_text()
            with self.subTest(stage=stage):
                self.assertIn('Phase entry and read scope',text)
                self.assertNotIn('**Before executing each reusable phase**, require the complete fingerprint Resume Skip Gate',text)
        shared=(PROMPTS/'shared/state_contract.md').read_text()
        self.assertNotIn('Steps are the **restart unit**',shared)
