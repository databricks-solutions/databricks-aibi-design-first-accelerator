"""Execute the template's verifier without Spark to check domain classification."""
import ast
from pathlib import Path
import unittest

class Frame:
    def __init__(self, values): self.values = values
    def count(self): return len(self.values)
    def select(self, column): return self
    def distinct(self): return Frame(list(dict.fromkeys(self.values)))
    def limit(self, count): return Frame(self.values[:count])
    def collect(self): return [(v,) for v in self.values]

class DomainVerifierTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'templates/dbldatagen_notebook.py.template'
        tree = ast.parse('\n'.join('# ' + line if line.startswith('%') else line for line in path.read_text().splitlines()))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_before_write')
        scope = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
        self.verify = scope['verify_before_write']

    def check(self, actual, declared):
        self.verify(Frame(actual), 'arbitrary_entity', [], [], ['external_code'],
                    domain_values={'external_code': declared})

    def test_declared_long_numeric_string_is_not_generic(self):
        self.check(['0123456789', '1234567890'], ['0123456789', '1234567890'])

    def test_undeclared_value_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'outside its declared domain'):
            self.check(['9999999999'], ['0123456789'])

    def test_truncated_domain_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'outside its declared domain'):
            self.check(['01234567'], ['0123456789'])

    def test_placeholder_is_rejected_even_if_declared(self):
        for value in ['PLACEHOLDER', 'val_1', 'ID-123']:
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, 'generic values'):
                self.check([value], [value])
