"""Execute the prompt's binding gate against the actual released data templates."""
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_deployment_admission import Executor, ROOT


class DataTemplateBindingTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / 'framework/agent_skills/v2/prompts/data_layer/validation.md').read_text()
        source = next(block for block in re.findall(r'```python\n(.*?)```', text, re.S)
                      if 'def bind_data_template(' in block)
        namespace = {}
        exec(compile(source, 'data_layer/validation.md', 'exec'), namespace)
        self.bind = namespace['bind_data_template']
        self.context = {'domain': {'name': 'sample'}, 'version': {'asset_suffix': '_trial_v23'}}
        self.handoff = {'output_folder': '/Workspace/output/v23', 'catalog': 'target',
                        'schema': 'sample', 'asset_suffix': '_trial_v23', 'short_name_suffix': ''}

    def template(self, name):
        return (ROOT / f'framework/templates/{name}_notebook.py.template').read_text()

    def test_each_real_template_binds_and_imports_without_reconstructing_suffix(self):
        for name in ('ddl', 'dbldatagen'):
            with self.subTest(template=name):
                template = self.template(name)
                bindings = self.bind(template, self.context, self.handoff)
                self.assertEqual(set(bindings), set(re.findall(r'\{\{([A-Z_][A-Z0-9_]*)\}\}', template)))
                if name == 'dbldatagen':
                    self.assertEqual(bindings['ASSET_SUFFIX'], '_trial_v23')
                else:
                    self.assertNotIn('ASSET_SUFFIX', bindings)
                ws = Mock()
                ws.read_file.return_value = template
                result = Executor(SimpleNamespace(), {'workspace': ws}).execute(
                    'deploy_from_template', dict(template_path='/template', output_path='/notebook',
                                                 placeholders=bindings))
                self.assertTrue(result.startswith('SUCCESS'), result)
                rendered = ws.import_notebook.call_args.args[1]
                self.assertNotRegex(rendered, r'\{\{[A-Z_][A-Z0-9_]*\}\}')

    def test_complete_request_retains_synthetic_suffix(self):
        text = (ROOT / 'framework/agent_skills/v2/prompts/data_layer/validation.md').read_text()
        source = next(block for block in re.findall(r'```python\n(.*?)```', text, re.S)
                      if 'def build_data_deployment_request(' in block)
        namespace = {'bind_data_template': self.bind}
        exec(compile(source, 'data_layer/validation.md', 'exec'), namespace)
        request = namespace['build_data_deployment_request'](
            self.template('dbldatagen'), self.context, self.handoff,
            '/template', '/Workspace/output/v23/notebooks/synthetic',
            '/Workspace/output/v23/run_context.yaml')
        self.assertEqual(request['placeholders']['ASSET_SUFFIX'], '_trial_v23')
        ws = Mock()
        ws.read_file.return_value = self.template('dbldatagen')
        result = Executor(SimpleNamespace(), {'workspace': ws}).execute('deploy_from_template', request)
        self.assertTrue(result.startswith('SUCCESS'), result)
        self.assertNotRegex(ws.import_notebook.call_args.args[1], r'\{\{[A-Z_][A-Z0-9_]*\}\}')

    def test_invalid_persisted_suffix_halts_binding_gate(self):
        for value in (None, '', ' ', '_different_v23'):
            with self.subTest(value=value):
                handoff = {**self.handoff, 'asset_suffix': value}
                with self.assertRaisesRegex(RuntimeError, 'HANDOFF_AUTHORITY_ERROR'):
                    self.bind(self.template('dbldatagen'), self.context, handoff)
        del self.handoff['asset_suffix']
        with self.assertRaisesRegex(RuntimeError, 'HANDOFF_AUTHORITY_ERROR'):
            self.bind(self.template('dbldatagen'), self.context, self.handoff)

    def test_unknown_interface_field_is_not_guessed(self):
        with self.assertRaisesRegex(RuntimeError, 'TEMPLATE_BINDING_ERROR.*NEW_FIELD'):
            self.bind(self.template('dbldatagen') + '\n{{NEW_FIELD}}', self.context, self.handoff)

    def test_ddl_bindings_cannot_be_reused_for_synthetic_deployment(self):
        bindings = self.bind(self.template('ddl'), self.context, self.handoff)
        ws = Mock()
        ws.read_file.return_value = self.template('dbldatagen')
        result = Executor(SimpleNamespace(), {'workspace': ws}).execute(
            'deploy_from_template', dict(template_path='/template', output_path='/notebook',
                                         placeholders=bindings))
        self.assertIn("missing or empty placeholders: ['ASSET_SUFFIX']", result)
        ws.import_notebook.assert_not_called()
