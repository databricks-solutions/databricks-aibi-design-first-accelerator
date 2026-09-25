"""Cross-stage release integration, using real contracts and simulated remote readbacks.

No LLM, Spark, or live API is exercised; this is not a live deployment acceptance test.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
import uuid
import yaml
from test_v2_portability import ROOT, runtime, gates, Client, dashboard_policy, genie_policy

PROMPTS = ROOT/'framework/agent_skills/v2/prompts'


def prompt_functions(path):
    ns = {}
    for block in re.findall(r'```python\n(.*?)```', path.read_text(), re.S):
        tree = ast.parse(block)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if functions:
            exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),ns)
    return ns


class ReleaseWorkflowTests(unittest.TestCase):
    def exercise_workflow(self, fail_dashboard=False):
        transport = prompt_functions(PROMPTS/'shared/agent_transport.md')
        config = yaml.safe_load((ROOT/'kpi_domains/member_claims/accelerator.yaml').read_text())
        release = yaml.safe_load((ROOT/'framework/agent_skills/v2/contracts/release.yaml').read_text())
        refs = transport['build_release_executable_references'](release,str(ROOT),lambda p:Path(p).read_bytes())
        coordinates = transport['resolve_catalog_coordinates'](config)
        with tempfile.TemporaryDirectory() as folder:
            store=runtime.LocalStore()
            selected=runtime.resolve_version(registry_path=folder+'/version_registry.yaml',
                domain=config['domain']['name'],output_root=folder+'/generated_outputs',
                created_by='portable_test',run_id=str(uuid.uuid4()),store=store)
            context={k:v for k,v in selected.items() if k not in ('is_new','version_suffix')}
            context.update(coordinates,templates=refs,checkpointing={},phases_completed=[],
                           version={"number": selected["version"], "asset_suffix": selected["version_suffix"]})
            transport['verify_release_executable_references'](context,refs)
            context['checkpointing']['frozen_run_contract_sha256']=runtime.frozen_context_sha256(context)
            store.write(selected['run_context_path'],runtime.encode(context))
            handoff=dict(coordinates['target'],run_id=selected['run_id'],output_folder=selected['output_folder'],asset_suffix=selected['version_suffix'])
            store.write(selected['output_folder']+'/step_handoff.yaml',runtime.encode(handoff))
            authenticated=runtime.authenticate_context(store,selected['run_context_path'])
            statement=transport['build_setup_schema_sql'](authenticated,handoff)
            self.assertEqual(transport['admit_setup_schema_request'](authenticated,handoff,statement),{'statement':statement})
            target=coordinates['target']
            self.assertIn('`'+target['catalog']+'`.`'+target['schema']+'`',statement)
            values=dict(DOMAIN_NAME=config['domain']['name'],OUTPUT_FOLDER=selected['output_folder'],
                TARGET_CATALOG=target['catalog'],TARGET_SCHEMA=target['schema'],ASSET_SUFFIX=selected['version_suffix'],
                CATALOG=target['catalog'],SCHEMA=target['schema'],VERSION_SUFFIX=selected['version_suffix'],
                WAREHOUSE_ID='wh',DEPLOY_ROOT=str(ROOT),PARENT_PATH=selected['output_folder'],
                RUN_CONTEXT_PATH=selected['run_context_path'],RUN_CONTRACT_PATH=refs['run_contract']['path'],
                RUN_CONTRACT_SHA256=refs['run_contract']['sha256'],GATE_CHECKS_PATH=refs['gate_checks']['path'],
                GATE_CHECKS_SHA256=refs['gate_checks']['sha256'],METRIC_VIEW_FQNS=['cat.sch.mv'],
                QUALITY_GATES={'enabled':True,'optional':None},TABLE_IDENTIFIERS=['cat.sch.mv'],
                SPACE_TITLE='Analytics "quoted"',SPACE_DESCRIPTION='Description with \\ and newline\nnext',
                GENERAL_INSTRUCTIONS='Use "approved" views.\nExplain results.',METRIC_VIEW_DESCRIPTIONS={'cat.sch.mv':'Measures'},
                SAMPLE_QUESTIONS=['Total?'],EXAMPLE_SQLS=[{'sql':'SELECT 1','enabled':True}],BENCHMARK_QUESTIONS=['Total?'])
            data_gates=prompt_functions(PROMPTS/'data_layer/validation.md')
            table_bytes=runtime.encode(dict(target,asset_suffix=selected['version_suffix'],
                tables=[{'name':'entity','columns':[{'name':'id','type':'BIGINT'}]}]))
            spec_bytes=runtime.encode({'tables':[{'name':'entity','rows':10,'pk_columns':['id'],
                                                'domain_columns':{},'fk_columns':{}}]})
            store.write(selected['output_folder']+'/table_spec.yaml',table_bytes)
            store.write(selected['output_folder']+'/synthetic_data_spec.yaml',spec_bytes)
            ddl_admission=data_gates['admit_ddl_target_envelope'](
                store.read(selected['output_folder']+'/table_spec.yaml'),authenticated,handoff,runtime.decode)
            self.assertEqual(ddl_admission['table_spec_sha256'],hashlib.sha256(table_bytes).hexdigest())
            admission=data_gates['admit_synthetic_inputs'](
                Path(refs['dbldatagen_notebook']['path']).read_bytes(),refs['dbldatagen_notebook']['sha256'],
                store.read(selected['output_folder']+'/synthetic_data_spec.yaml'),
                store.read(selected['output_folder']+'/table_spec.yaml'),runtime.decode)
            self.assertEqual(admission['synthetic_spec_sha256'],hashlib.sha256(spec_bytes).hexdigest())
            rendered_names=[]
            for name in ('ddl_notebook','dbldatagen_notebook','metric_view_notebook','dashboard_notebook','genie_notebook'):
                text=Path(refs[name]['path']).read_text()
                keys=set(re.findall(r'\{\{([A-Z_][A-Z0-9_]*)\}\}',text))
                bindings=transport['prepare_template_bindings'](text,{k:values[k] for k in keys})
                rendered=text
                for key,value in bindings.items():
                    self.assertIsInstance(value,str)
                    rendered=rendered.replace('{{'+key+'}}',value)
                self.assertNotRegex(rendered,r'\{\{[A-Z_]+\}\}')
                store.write(selected['output_folder']+'/'+name+'.py',rendered.encode())
                rendered_names.append(name)
            self.assertEqual(len(rendered_names),5)
            # Exercise actual downstream API validators and the entire terminal sweep.
            client=Client()
            expected=dict(workspace_host=client.config.host.rstrip('/'),warehouse_id='wh',
                serialized_dashboard=copy.deepcopy(client.sd),primary_kpi_contexts={'KPI_1':['total']})
            genie_expected=dict(workspace_host=expected['workspace_host'],warehouse_id='wh',
                serialized_space=copy.deepcopy(client.ss),metric_view_fqns=['`cat`.`sch`.`mv`'])
            if fail_dashboard:
                # Drift occurs only at Dashboard readback; all previous files remain intact.
                before={name:store.read(selected['output_folder']+'/'+name+'.py') for name in rendered_names[:3]}
                client.sd['datasets'][0]['queryLines']=['SELECT 999']
                with self.assertRaises(gates.GateCheckError):
                    gates.validate_dashboard_from_api(client,'dash','Dashboard',quality_gates=dashboard_policy(),expected=expected)
                failed=dict(context,status='failed',error={'failure_owner':'DASHBOARD_STAGE'})
                runtime.commit_terminal(store=store,registry_path=selected['registry_path'],run_context_path=selected['run_context_path'],manifest=failed)
                self.assertFalse(any('/genie/' in call[1] for call in client.calls))
                reopened=runtime.resolve_version(registry_path=selected['registry_path'],domain=config['domain']['name'],
                    output_root=folder+'/generated_outputs',created_by='portable_test',run_id=str(uuid.uuid4()),store=store,mode='retry')
                self.assertEqual(reopened['run_id'],selected['run_id'])
                for name,raw in before.items():
                    self.assertEqual(store.read(selected['output_folder']+'/'+name+'.py'),raw)
                self.assertEqual(runtime.authenticate_context(store,selected['run_context_path'])['status'],'running')
                return
            dash=gates.validate_dashboard_from_api(client,'dash','Dashboard',quality_gates=dashboard_policy(),expected=expected)
            genie=gates.validate_genie_from_api(client,'space','Genie',validation=genie_policy(),expected=genie_expected)
            self.assertEqual(dash['status'], 'PASS');self.assertEqual(genie['status'],'PASS')
            table={'sql_fqn':'`cat`.`sch`.`tbl`','columns':[['id','int']],
                'definition':'CREATE TABLE cat.sch.tbl (id INT) USING DELTA',
                'validation_queries':[{'sql':'SELECT COUNT(*) FROM cat.sch.tbl','check':'positive_count'}]}
            scope=dict(run_id=selected['run_id'],output_folder=selected['output_folder'],workspace_host=client.config.host,
                warehouse_id='wh',frozen_run_contract_sha256=context['checkpointing']['frozen_run_contract_sha256'],
                producer_bundles={key:'b'*64 for key in config['pipeline']['steps']},
                enabled_asset_classes=['tables','metric_views','dashboards','genie_spaces'],expected_inventory={
                    'tables':[table],'metric_views':[dict(table,sql_fqn='`cat`.`sch`.`mv`')],
                    'dashboards':[{'id':'dash','name':'Dashboard','expected':expected}],
                    'genie_spaces':[{'id':'space','name':'Genie','expected':genie_expected,'benchmark_evidence':{
                        'run_id':selected['run_id'],'space_id':'space','readback_sha256':genie['readback_sha256'],'passed':1,'total':1}}]})
            sweep=gates.run_cross_validation(client,scope=scope,quality_gates=dashboard_policy(),validation=genie_policy())
            self.assertEqual(sweep['overall_status'],'PASS',sweep)
            digest=gates.write_ground_truth_validation(selected['output_folder']+'/ground_truth_validation.yaml',sweep,store=store)
            # Documentation produces a draft; only commit_terminal writes canonical lifecycle.
            draft=dict(context,status='completed',validation={'cross_validation':{'status':'PASS','ground_truth_validation_sha256':digest}})
            store.write(selected['output_folder']+'/documentation/run_manifest_draft.json',runtime.encode(draft))
            self.assertIsNone(store.read(selected['output_folder']+'/run_manifest.json'))
            runtime.commit_terminal(store=store,registry_path=selected['registry_path'],run_context_path=selected['run_context_path'],manifest=draft)
            self.assertEqual(runtime.authenticate_context(store,selected['run_context_path'])['status'],'completed')
            self.assertEqual(runtime.decode(store.read(selected['registry_path']))['versions'][0]['status'],'completed')
            self.assertEqual(runtime.decode(store.read(selected['output_folder']+'/run_manifest.json'))['run_id'],selected['run_id'])

    def test_config_to_all_templates_readbacks_sweep_and_terminal_commit(self):
        self.exercise_workflow()

    def test_dashboard_failure_and_reopen_preserve_predecessor_artifacts(self):
        self.exercise_workflow(fail_dashboard=True)

    def test_cross_stage_binding_rejects_omitted_suffix(self):
        transport=prompt_functions(PROMPTS/'shared/agent_transport.md')
        text=(ROOT/'framework/templates/dbldatagen_notebook.py.template').read_text()
        keys=set(re.findall(r'\{\{([A-Z_][A-Z0-9_]*)\}\}',text))
        with self.assertRaisesRegex(RuntimeError,'ASSET_SUFFIX'):
            transport['prepare_template_bindings'](text,{k:'value' for k in keys if k!='ASSET_SUFFIX'})

    def test_quoted_and_python_literal_values_survive_render(self):
        transport=prompt_functions(PROMPTS/'shared/agent_transport.md')
        template='title = "{{TITLE}}"\noptions = {{OPTIONS}}\nnotes = """{{NOTES}}"""'
        values={'TITLE':'A "quote" and \\ slash','OPTIONS':{'enabled':True,'missing':None},'NOTES':'first\nsecond """ quoted'}
        bindings=transport['prepare_template_bindings'](template,values)
        rendered=template
        for k,v in bindings.items(): rendered=rendered.replace('{{'+k+'}}',v)
        ns={};exec(compile(rendered,'render-test','exec'),ns)
        self.assertEqual(ns['title'],values['TITLE'])
        self.assertEqual(ns['options'],values['OPTIONS'])
        self.assertEqual(ns['notes'],values['NOTES'])

    def test_every_stage_instruction_validation_guardrail_and_runbook_exists(self):
        for stage in ('data_layer','metric_views','dashboards','genie','cross_validation','documentation'):
            for role in ('instructions','validation','guardrails','runbook'):
                self.assertTrue((PROMPTS/stage/(role+'.md')).is_file())

    def test_no_active_stage_selects_legacy_deployment_template(self):
        for stage,stem in [('dashboards','dashboard_notebook.py.template'),('genie','genie_space_notebook.py.template')]:
            for role in ('instructions','validation'):
                self.assertNotRegex((PROMPTS/stage/(role+'.md')).read_text(),r'(?<!v2_)'+re.escape(stem))
