import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class SyntheticManifestLocatorTests(unittest.TestCase):
    def test_runtime_manifest_locator_matches_phase_and_stage_contracts(self):
        source=(ROOT/'templates/dbldatagen_notebook.py.template').read_text()
        tree=ast.parse('\n'.join('# '+line if line.lstrip().startswith('%') else line for line in source.splitlines()))
        paths=[n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='_manifest_path' for t in n.targets)
               and isinstance(n.value,ast.Constant)]
        self.assertEqual(paths,['{{OUTPUT_FOLDER}}/synthetic_data_manifest.json'])
        state=(ROOT/'agent_skills/v2/prompts/shared/state_contract.md').read_text()
        row=next(line for line in state.splitlines() if line.startswith('| generate_synthetic_data |'))
        self.assertIn('{OUTPUT_FOLDER}/synthetic_data_manifest.json',row)
        instructions=(ROOT/'agent_skills/v2/prompts/data_layer/instructions.md').read_text()
        self.assertIn('| synthetic_data_manifest.json |',instructions)
        self.assertLess(source.index('df.write.format("delta")'),source.index('_manifest_path ='))
