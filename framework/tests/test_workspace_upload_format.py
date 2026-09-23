"""Regression coverage for plain-file uploads entering archive/source import."""
import io
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from test_v2_portability import load, runtime
from test_v2_master_host import AgentLoop

ToolExecutor=load('upload_format_executor','app/llm/tool_executor.py').ToolExecutor


class UploadFormatTests(unittest.TestCase):
    def test_missing_format_is_rejected_before_python_runs(self):
        executor=ToolExecutor(SimpleNamespace(),{})
        for method in ('upload','import_'):
            with self.subTest(method=method), patch('subprocess.run') as run:
                result=executor.execute('execute_python',{'code':f"w.workspace.{method}('/Workspace/run.yaml', b'hello')"})
                self.assertIn('WORKSPACE_UPLOAD_FORMAT_REQUIRED',result)
                run.assert_not_called()
    def test_explicit_plain_file_format_allowed(self):
        executor=ToolExecutor(SimpleNamespace(),{})
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='ok')) as run:
            result=executor.execute('execute_python',{'code':"w.workspace.upload('/Workspace/run.yaml', b'hello', format=ImportFormat.RAW)"})
            self.assertEqual(result,'ok')
            run.assert_called_once()
    def test_archive_failure_retains_original_error_and_guidance(self):
        executor=ToolExecutor(SimpleNamespace(),{})
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='BadRequest: The zip archive contains no items.')):
            result=executor.execute('execute_python',{'code':'put(path, raw)'})
        self.assertIn('zip archive contains no items',result)
        self.assertIn('Inspect earlier writes',result)
    def test_preflight_error_is_repairable(self):
        classify=AgentLoop.run.__globals__['classify_error']
        self.assertEqual(classify('ERROR: WORKSPACE_UPLOAD_FORMAT_REQUIRED'), 'LLM_REPAIRABLE')
    def test_notebook_upload_without_format_never_submits(self):
        from unittest.mock import Mock
        for method in ('upload', 'import_'):
            with self.subTest(method=method):
                source = "# Databricks notebook source\n# COMMAND ----------\ndef put(path, raw):\n    w.workspace." + method + "(path, raw)\n"
                jobs = SimpleNamespace(run_notebook=Mock())
                executor = ToolExecutor(SimpleNamespace(), {
                    'workspace': SimpleNamespace(read_file=lambda path: source), 'jobs': jobs})
                result = executor.execute('execute_notebook', {'path': '/Workspace/inspection'})
                self.assertIn('WORKSPACE_UPLOAD_FORMAT_REQUIRED', result)
                self.assertIn('cell 2', result)
                jobs.run_notebook.assert_not_called()

    def test_explicit_notebook_format_passes_preflight(self):
        source = "w.workspace.import_(path=p, content=payload, format=ImportFormat.SOURCE, language=Language.PYTHON)"
        executor = ToolExecutor(SimpleNamespace(), {
            'workspace': SimpleNamespace(read_file=lambda path: source)})
        self.assertIsNone(executor._py_compile_check('/Workspace/inspection'))

    def test_unreadable_notebook_never_submits(self):
        from unittest.mock import Mock
        jobs = SimpleNamespace(run_notebook=Mock())
        executor = ToolExecutor(SimpleNamespace(), {
            'workspace': SimpleNamespace(read_file=Mock(side_effect=PermissionError('denied'))),
            'jobs': jobs})
        result = executor.execute('execute_notebook', {'path': '/Workspace/inspection'})
        self.assertIn('NOTEBOOK_PREFLIGHT_ERROR', result)
        self.assertIn('denied', result)
        jobs.run_notebook.assert_not_called()

    def test_workspace_store_preserves_raw_bytes_and_create_only_flag(self):
        module=ModuleType('databricks.sdk.service.workspace')
        module.ImportFormat=SimpleNamespace(RAW='RAW')
        errors=ModuleType('databricks.sdk.errors'); errors.NotFound=FileNotFoundError
        recorded=[]; files={}
        def upload(path,raw,*,format,overwrite):
            self.assertEqual(format,'RAW')
            if path in files and not overwrite: raise FileExistsError(path)
            recorded.append((path,raw,overwrite));files[path]=raw
        api=SimpleNamespace(mkdirs=lambda path:None, upload=upload,
                            download=lambda path:io.BytesIO(files[path]))
        with patch.dict(sys.modules,{'databricks.sdk.service.workspace':module,'databricks.sdk.errors':errors}):
            store=runtime.WorkspaceStore(SimpleNamespace(workspace=api))
            raw=b'# Databricks notebook source\n# stored as an ordinary helper\n'
            store.write('/Workspace/helper.py',raw,overwrite=False)
            self.assertEqual(store.read('/Workspace/helper.py'),raw)
            self.assertFalse(recorded[0][2])
            with self.assertRaises(FileExistsError): store.write('/Workspace/helper.py',raw,overwrite=False)


if __name__=='__main__': unittest.main()
