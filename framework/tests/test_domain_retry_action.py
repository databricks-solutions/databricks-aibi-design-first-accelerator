"""Exercise the actual browser retry handler with controlled HTTP responses."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]

@unittest.skipUnless(shutil.which('node'), 'Node required for browser handler test')
class DomainRetryActionTests(unittest.TestCase):
    def run_handler(self, response=None, network_error=False):
        source = (ROOT/'app/templates/domains.html').read_text()
        handler = source.split('async function resumeLastRun() {', 1)[1].split('async function launchPipeline()', 1)[0]
        script = '''
const calls=[], alerts=[], btn={};
const lastResumableRun={run_id:'selected-v5-run',version:5};
const selectedDomain='example';
const document={getElementById:()=>btn};
const window={location:{href:''}};
const alert=message=>alerts.push(message);
console.warn=()=>{};
''' + 'const response='+json.dumps(response)+';\n' + 'const networkError='+json.dumps(network_error)+';\n' + '''
const fetch=async(url,options)=>{
 calls.push({url,options});
 if(networkError) throw new Error('Connection lost');
 return {ok:response.ok,json:async()=>response.body};
};
async function resumeLastRun() {''' + handler + '''
resumeLastRun().then(()=>console.log(JSON.stringify({calls,alerts,btn,href:window.location.href})));
'''
        result = subprocess.run(['node','-e',script],capture_output=True,text=True,check=True)
        return json.loads(result.stdout)

    def test_success_targets_selected_run(self):
        result=self.run_handler({'ok':True,'body':{'run_id':'selected-v5-run'}})
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(result['calls'][0]['url'],'/api/pipeline/rerun/selected-v5-run')
        self.assertEqual(result['href'],'/domains/example/run/selected-v5-run')

    def test_rejection_does_not_launch_another_run(self):
        result=self.run_handler({'ok':False,'body':{'error':{'message':'Checkpoint recovery unavailable'}}})
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(result['href'],'')
        self.assertEqual(result['alerts'],['Checkpoint recovery unavailable'])
        self.assertFalse(result['btn']['disabled'])

    def test_unknown_submission_does_not_launch_another_run(self):
        result=self.run_handler(network_error=True)
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(result['href'],'')
        self.assertEqual(result['alerts'],['Connection lost'])
