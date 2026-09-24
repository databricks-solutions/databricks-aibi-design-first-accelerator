"""Exercise the actual tool-call client with simulated endpoint timeouts."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class ModelTimeoutTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / 'app/llm/client.py'
        tree = ast.parse(path.read_text())
        definitions = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith('LLM')]
        scope = dict(Optional=__import__('typing').Optional, Type=__import__('typing').Type,
                     WorkspaceClient=object, BaseModel=object, time=SimpleNamespace(sleep=Mock()),
                     logger=logging.getLogger('timeout-test'))
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), 'exec'), scope)
        self.scope = scope
        self.do = Mock()
        self.client = scope['LLMClient'](client=SimpleNamespace(api_client=SimpleNamespace(do=self.do)))
        self.messages = [{'role': 'tool', 'content': 'prior notebook completed', 'tool_call_id': 'prior'}]

    def test_timeout_then_success_reuses_request(self):
        self.do.side_effect = [TimeoutError('Timed out after 0:05:00'),
                               {'choices': [{'message': {'content': 'continue', 'tool_calls': []}}]}]
        result = self.client.chat_with_tools(self.messages, [])
        self.assertEqual(result['content'], 'continue')
        self.assertEqual(self.do.call_count, 2)
        self.assertEqual(self.do.call_args_list[0], self.do.call_args_list[1])
        self.assertEqual(len(self.messages), 1)

    def test_timeout_budget_is_bounded_and_typed(self):
        self.do.side_effect = RuntimeError('Timed out after 0:05:00')
        with self.assertRaisesRegex(self.scope['LLMTimeoutError'], 'no tools from this request executed'):
            self.client.chat_with_tools(self.messages, [])
        self.assertEqual(self.do.call_count, 2)

    def test_permission_error_not_retried(self):
        self.do.side_effect = PermissionError('denied')
        with self.assertRaises(self.scope['LLMError']):
            self.client.chat_with_tools(self.messages, [])
        self.assertEqual(self.do.call_count, 1)
