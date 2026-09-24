import ast
import hashlib
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class MetricCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT/'templates/metric_view_notebook.py.template').read_text()
        tree = ast.parse(self.source)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
                     ('validate_capability_inputs', 'verify_definition_readback')]
        ns = dict(yaml=yaml, hashlib=hashlib, json=json)
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'template', 'exec'), ns)
        self.gate = ns['validate_capability_inputs']
        self.readback = ns['verify_definition_readback']
        self.raw = (ROOT/'agent_skills/v2/contracts/metric_view_capabilities.yaml').read_bytes()
        self.contract = yaml.safe_load(self.raw)
        digest = hashlib.sha256(self.raw).hexdigest()
        self.context = {'run_id':'run', 'version':{'asset_suffix':'_v2'},
                        'inputs':{'metric_view_capabilities':{'sha256':digest}}}
        view = {'name':'mv_v2', 'sql_fqn':'cat.sch.mv_v2', 'source_fqn':'cat.sch.source', 'primary':True, 'kpis':['K1']}
        self.handoff = {'asset_suffix':'_v2','catalog':'cat','schema':'sch','metric_view_fqns':[view]}
        cap = self.contract['capabilities']['standard_aggregate_measures']
        decision = {**cap,'kpi':'K1','required_capability':'standard_aggregate_measures','native_outcome':'USED','final_status':'READY'}
        self.plan = {'run_id':'run','asset_suffix':'_v2','capability_contract_name':'metric_view_capabilities',
                     'capability_contract_version':self.contract['contract']['contract_version'],
                     'capability_contract_sha256':digest,
                     'metric_view_plan':{'metric_views':[view], 'capability_decisions':[decision]}}
        self.spec = {'metric_views':[{'name':'mv_v2','yaml':{'version':'1.1','source':'cat.sch.source','measures':[{'name':'Count','expr':'COUNT(*)'}]}}]}

    def check(self):
        return self.gate(self.context,self.handoff,self.plan,self.spec,self.raw,self.raw)

    def test_valid_contract_and_inventory(self):
        self.assertEqual(self.check()['capability_contract_sha256'], hashlib.sha256(self.raw).hexdigest())

    def test_contract_drift_blocks(self):
        self.context['inputs']['metric_view_capabilities']['sha256'] = '0'*64
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'): self.check()

    def test_plan_spec_inventory_drift_blocks(self):
        self.spec['metric_views'][0]['name']='wrong'
        with self.assertRaisesRegex(RuntimeError, 'inventory mismatch'): self.check()

    def test_disabled_native_construct_blocks(self):
        self.spec['metric_views'][0]['yaml']['filter']='amount > 0'
        with self.assertRaisesRegex(RuntimeError, 'disabled construct'): self.check()

    def test_fallback_requires_checks(self):
        cap = self.contract['capabilities']['metric_view_filter']
        d = {**cap,'kpi':'K1','required_capability':'metric_view_filter','native_outcome':'DISALLOWED',
             'final_status':'READY','fallback_considered':True,'fallback_strategy':cap['fallback']['strategy'],
             'fallback_outcome':'APPLIED_AND_VALIDATED'}
        self.plan['metric_view_plan']['capability_decisions']=[d]
        with self.assertRaisesRegex(RuntimeError, 'fallback check'): self.check()
        d['fallback_checks']={k:'PASS' for k in cap['fallback']['required_checks']}
        self.check()

    def test_definition_readback_detects_expression_drift(self):
        expected=self.spec['metric_views'][0]['yaml']
        statement='CREATE VIEW cat.sch.mv_v2 WITH METRICS LANGUAGE YAML AS $$\n'+yaml.safe_dump(expected)+'$$'
        self.assertEqual(self.readback(statement,expected),expected)
        with self.assertRaisesRegex(RuntimeError,'differs'):
            self.readback(statement.replace('COUNT(*)','SUM(amount)'), expected)

    def test_gate_precedes_deployment_and_manifest_has_catalog_evidence(self):
        self.assertLess(self.source.index('CAPABILITY_IDENTITY = validate_capability_inputs'), self.source.index('result = execute_sql(ddl'))
        self.assertIn('"validation_source": "catalog_readback"',self.source)
        self.assertIn('"deployed_readback_sha256": READBACK_HASH',self.source)
        self.assertIn('"metric_view_spec_sha256": SOURCE_HASH',self.source)
