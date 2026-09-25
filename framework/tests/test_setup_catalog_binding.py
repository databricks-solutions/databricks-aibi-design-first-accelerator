from pathlib import Path
import re
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[2]
class SetupCatalogBindingTests(unittest.TestCase):
    def setUp(self):
        text=(ROOT/'framework/agent_skills/v2/prompts/shared/agent_transport.md').read_text()
        code=next(b for b in re.findall(r'```python\n(.*?)```',text,re.S) if 'def resolve_catalog_coordinates(' in b)
        ns={};exec(compile(code,'agent_transport.md','exec'),ns)
        self.resolve=ns['resolve_catalog_coordinates'];self.build=ns['build_setup_schema_sql']
        self.admit=ns['admit_setup_schema_request']

    def test_actual_domain_config_produces_exact_setup_target(self):
        config=yaml.safe_load((ROOT/'kpi_domains/member_claims/accelerator.yaml').read_text())
        coordinates=self.resolve(config)
        target=config['catalog']['target']
        sql=self.build(coordinates,target)
        self.assertEqual(sql,'CREATE SCHEMA IF NOT EXISTS `'+target['catalog']+'`.`'+target['schema']+'`')

    def test_missing_config_never_defaults(self):
        with self.assertRaisesRegex(RuntimeError,'CONFIGURATION_ERROR'):
            self.resolve({'domain':{'name':'member_claims'}})

    def test_wrong_handoff_blocks_sql(self):
        with self.assertRaisesRegex(RuntimeError,'HANDOFF_AUTHORITY_ERROR'):
            self.build({'target':{'catalog':'approved','schema':'target'}},{'catalog':'main','schema':'target'})

    def test_identifier_quoting_is_segment_specific(self):
        target={'catalog':'catalog`name','schema':'schema name'}
        self.assertEqual(self.build({'target':target},target),'CREATE SCHEMA IF NOT EXISTS `catalog``name`.`schema name`')

    def test_wrong_sql_rejected_even_when_context_and_handoff_agree(self):
        target={'catalog':'approved_catalog','schema':'approved_schema'}
        with self.assertRaisesRegex(RuntimeError,'SETUP_TARGET_BINDING_ERROR'):
            self.admit({'target':target},target,'CREATE SCHEMA IF NOT EXISTS `main`.`member_claims`')

    def test_admitted_request_is_exact_builder_output(self):
        target={'catalog':'tenant_catalog','schema':'analytics'}
        context={'target':target}
        statement=self.build(context,target)
        self.assertEqual(self.admit(context,target,statement),{'statement':statement})
