from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from test_deployment_admission import Executor
from test_v2_master_host import AgentLoop

class SQLTimeoutIdentityTests(unittest.TestCase):
    def test_known_execution_retains_id_without_replaying(self):
        error=RuntimeError('Timeout after 120s waiting for statement')
        error.statement_id='statement-123'
        sql=Mock();sql.execute_and_wait.side_effect=error
        executor=Executor(SimpleNamespace(),{'sql':sql})
        result=executor.execute('execute_sql',{'statement':'CREATE SCHEMA IF NOT EXISTS cat.sch'})
        self.assertIn('SQL_EXECUTION_UNRESOLVED',result)
        self.assertIn('statement-123',result)
        self.assertEqual(executor._diagnostic_details['sql_statement_id'],'statement-123')
        sql.execute_and_wait.assert_called_once()
        self.assertEqual(AgentLoop.run.__globals__['classify_error'](result),'LLM_REPAIRABLE')

    def test_unknown_submission_is_not_retryable(self):
        sql=Mock();sql.execute_and_wait.side_effect=TimeoutError('Timed out')
        result=Executor(SimpleNamespace(),{'sql':sql}).execute('execute_sql',{'statement':'CREATE SCHEMA cat.sch'})
        self.assertIn('SQL_SUBMISSION_OUTCOME_UNKNOWN',result)
        self.assertEqual(AgentLoop.run.__globals__['classify_error'](result),'DETERMINISTIC_FAIL')
        sql.execute_and_wait.assert_called_once()

    def test_terminal_error_retains_id(self):
        error=RuntimeError('permission denied');error.statement_id='statement-456'
        sql=Mock();sql.execute_and_wait.side_effect=error
        result=Executor(SimpleNamespace(),{'sql':sql}).execute('execute_sql',{'statement':'CREATE SCHEMA cat.sch'})
        self.assertIn('statement-456',result)
        self.assertNotIn('SQL_EXECUTION_UNRESOLVED',result)

    def test_unresolved_sql_blocks_queued_consumer(self):
        executor=Mock()
        executor.execute.return_value='SQL ERROR: SQL_EXECUTION_UNRESOLVED: statement_id=known'
        calls=[{'id':str(i),'type':'function','function':{'name':name,'arguments':'{}'}}
               for i,name in enumerate(['execute_sql','execute_notebook'])]
        llm=Mock();llm.chat_with_tools.return_value={'content':'','tool_calls':calls}
        AgentLoop(llm,executor,SimpleNamespace()).run('master',{'STEP_NAME':'master'},max_iterations=1)
        self.assertEqual(executor.execute.call_count,1)
