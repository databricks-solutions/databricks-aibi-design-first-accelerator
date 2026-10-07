"""Thin App transport for the same master prompt used by Genie Code.

No stage ordering, version allocation, asset generation, or lifecycle writes live
here. The master decides those. The host verifies its terminal files before UI success.
"""
import json
import hashlib
import posixpath
import time
import yaml

from llm.agent_loop import AgentLoop
from llm.prompt_loader import PromptLoader
from llm.tool_executor import ToolExecutor


def _mapping(raw):
    class UniqueLoader(yaml.SafeLoader):
        pass
    def construct(loader,node,deep=False):
        result={}
        for key,value in node.value:
            key=loader.construct_object(key,deep=deep)
            if key in result:
                raise ValueError(f'Duplicate contract key: {key}')
            result[key]=loader.construct_object(value,deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,construct)
    value=yaml.load(raw,Loader=UniqueLoader)
    if not isinstance(value,dict):
        raise ValueError('Terminal contract is not a mapping')
    return value


def _tuple(doc):
    domain,version=doc.get('domain'),doc.get('version')
    return (doc.get('lifecycle_contract_version'),domain.get('name') if isinstance(domain,dict) else domain,
            version.get('number') if isinstance(version,dict) else version,doc.get('run_id'),doc.get('created_by'),
            doc.get('output_folder'),doc.get('run_context_path'),doc.get('status'))


def verify_terminal(workspace, artifacts, *, example_dir, domain):
    paths=[p for p in artifacts if isinstance(p,str) and p.endswith('/run_manifest.json')]
    if len(paths) != 1:
        raise RuntimeError('MASTER_COMPLETION_ERROR: exactly one canonical manifest locator required')
    path=paths[0]
    if posixpath.normpath(path) != path or not path.startswith(example_dir.rstrip('/')+'/'):
        raise RuntimeError('MASTER_COMPLETION_ERROR: manifest outside domain output')
    manifest=_mapping(workspace.read_file(path))
    # Match the identity normalization used by lifecycle parity and the resolver.
    manifest_domain = _tuple(manifest)[1]
    mismatches = []
    if manifest_domain != domain:
        mismatches.append(f"domain expected={domain!r} observed={manifest.get('domain')!r}")
    if manifest.get('created_by') != 'app':
        mismatches.append(f"created_by expected='app' observed={manifest.get('created_by')!r}")
    if not isinstance(manifest.get('run_id'), str) or not manifest['run_id'].strip():
        mismatches.append(f"run_id must be a nonempty string; observed={manifest.get('run_id')!r}")
    if mismatches:
        raise RuntimeError('MASTER_COMPLETION_ERROR: manifest owner/domain/run mismatch: '
                           + '; '.join(mismatches) + f'; manifest={path}')
    output=posixpath.dirname(path)
    if manifest.get('output_folder') != output or manifest.get('run_context_path') != output+'/run_context.yaml':
        raise RuntimeError('MASTER_COMPLETION_ERROR: manifest/context path mismatch')
    context=_mapping(workspace.read_file(manifest['run_context_path']))
    registry_path=example_dir.rstrip('/')+'/version_registry.yaml'
    if context.get('registry_path') != registry_path:
        raise RuntimeError('MASTER_COMPLETION_ERROR: registry locator mismatch')
    registry=_mapping(workspace.read_file(registry_path))
    def unlocked():
        if any(item.path == registry_path+'.lock' for item in workspace.list_dir(example_dir)):
            raise RuntimeError('MASTER_COMPLETION_ERROR: active lifecycle lock')
        lifecycle=output+'/.lifecycle'
        if any(item.path == lifecycle for item in workspace.list_dir(output)):
            if any(item.path == lifecycle+'/retry_transition.yaml' for item in workspace.list_dir(lifecycle)):
                raise RuntimeError('MASTER_COMPLETION_ERROR: unresolved retry transition')
    unlocked()
    frozen=json.loads(json.dumps(context))
    for key in ('current_step','status','phases_completed','findings','completed_at','error','retry_attempt'):
        frozen.pop(key,None)
    recorded=frozen.get('checkpointing',{}).pop('frozen_run_contract_sha256',None)
    digest=hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if not recorded or digest != recorded:
        raise RuntimeError('MASTER_COMPLETION_ERROR: frozen context mismatch')
    entries=[entry for entry in registry.get('versions',[]) if entry.get('run_id') == manifest['run_id']]
    if len(entries) != 1 or not (_tuple(entries[0]) == _tuple(context) == _tuple(manifest)):
        raise RuntimeError('MASTER_COMPLETION_ERROR: lifecycle parity mismatch')
    if manifest.get('status') not in {'completed','partial_success','failed'}:
        raise RuntimeError('MASTER_COMPLETION_ERROR: run is not terminal')
    if manifest['status'] in {'completed','partial_success'}:
        cv=manifest.get('validation',{}).get('cross_validation',{})
        if cv.get('status') != 'PASS' or cv.get('source') != 'cross_validation_sweep':
            raise RuntimeError('MASTER_COMPLETION_ERROR: successful sweep missing')
        raw=workspace.read_file(output+'/ground_truth_validation.yaml')
        raw_bytes=raw.encode() if isinstance(raw,str) else raw
        report=_mapping(raw)
        if (hashlib.sha256(raw_bytes).hexdigest() != cv.get('ground_truth_validation_sha256')
                or report.get('overall_status') != 'PASS' or report.get('run_id') != manifest['run_id']
                or report.get('output_folder') != output or not any(report.get('expected_inventory',{}).values())
                or report.get('scope_input_binding') != 'PASS' or report.get('workspace_host_binding') != 'PASS'
                or report.get('expected_inventory') != report.get('observed_inventory')):
            raise RuntimeError('MASTER_COMPLETION_ERROR: sweep evidence mismatch')
    unlocked()
    if (_mapping(workspace.read_file(path)) != manifest
            or _mapping(workspace.read_file(manifest['run_context_path'])) != context
            or _mapping(workspace.read_file(registry_path)) != registry):
        raise RuntimeError('MASTER_COMPLETION_ERROR: lifecycle changed during readback')
    return manifest


class MasterAgentHost:
    def __init__(self,config,services,llm_client):
        self.config,self.services=config,services
        self.loader=PromptLoader(services['workspace'],config.framework_root,'v2')
        self.agent=AgentLoop(llm_client,ToolExecutor(config,services,llm_client=llm_client),config)
        self.cancelled=False

    def cancel(self):
        self.cancelled=True

    def _build_resume_hint(self,example_dir,version_override):
        """Scan filesystem to build a structured resume hint for the LLM.

        Returns a dict summarizing completed phases and the exact failure point
        so the LLM can skip lifecycle ceremony and jump to the failed phase.
        """
        try:
            ws=self.services['workspace']
            output_folder=example_dir+'/generated_outputs/v'+str(version_override)
            rc_raw=ws.read_file(output_folder+'/run_context.yaml')
            rc=yaml.safe_load(rc_raw)
            phases=rc.get('phases_completed',[])
            completed_phases=[]
            for p in phases:
                if isinstance(p,dict):
                    completed_phases.append(f"{p.get('step','?')}/{p.get('phase','?')}")
            # Determine which artifacts exist to identify completed steps
            step_markers=[
                ('create_data_layer','data_layer_validation.yaml'),
                ('create_metric_views','metric_views/metric_view_spec.yaml'),
                ('create_dashboards','dashboards/dashboard_validation.yaml'),
                ('create_genie_space','genie/genie_semantic_inventory.yaml'),
                ('generate_documentation','readme.md'),
            ]
            completed_steps=[]
            first_incomplete=None
            for step_name,marker in step_markers:
                try:
                    content=ws.read_file(output_folder+'/'+marker)
                    if content and len(str(content).strip())>0:
                        completed_steps.append(step_name)
                    else:
                        if not first_incomplete:
                            first_incomplete=step_name
                except Exception:
                    if not first_incomplete:
                        first_incomplete=step_name
            return {
                'version': version_override,
                'output_folder': output_folder,
                'run_id': rc.get('run_id',''),
                'prior_status': rc.get('status','unknown'),
                'prior_error': str(rc.get('error',''))[:500] if rc.get('error') else None,
                'prior_step': rc.get('current_step',''),
                'completed_phases': completed_phases,
                'completed_steps': completed_steps,
                'resume_at_step': first_incomplete or 'unknown',
                'instruction': (
                    f"This is a RETRY of version {version_override}. "
                    f"Steps already completed: {completed_steps}. "
                    f"Resume from step '{first_incomplete or 'next incomplete'}'. "
                    f"Do NOT re-execute completed steps or their phases. "
                    f"The prior run failed at step '{rc.get('current_step','')}'. "
                    f"Skip lifecycle ceremony for completed phases — they are already persisted."
                ),
            }
        except Exception:
            return None

    def run(self,*,domain,run_id,version_mode='auto',version_override=None,steps=None,run_mode='versioned',callback=None):
        config=self.config
        example_dir=config.example_dir
        context=dict(STEP_NAME='master',REPO_ROOT=config.deploy_root,EXAMPLE_DIR=example_dir,
            AGENT_SKILLS_DIR=config.framework_root+'/agent_skills/v2',
            execution_owner='app',candidate_uuid=run_id,requested_mode=version_mode,
            requested_version=version_override,sql_warehouse_id=config.sql_warehouse_id,
            workspace_host=self.services['workspace']._client.config.host,
            requested_steps=steps,requested_run_mode=run_mode)
        # For retry/resume: scan output artifacts to tell the LLM exactly which
        # phases are already completed so it can skip ahead instead of re-reading
        # the error and getting stuck in lifecycle ceremony.
        if version_mode=='retry' and version_override:
            resume_hint=self._build_resume_hint(example_dir,version_override)
            if resume_hint:
                context['resume_hint']=resume_hint
        def event(name,data):
            if self.cancelled:
                raise RuntimeError('Master execution interrupted; resume through the master checkpoint gates')
            if callback:
                callback(name,data)
        start=time.monotonic()
        result=self.agent.run(self.loader.load_step_prompt('master'),context,
            system_supplement=self.loader.load_supplements('master'),callback=event,max_iterations=800)
        if result.error and not result.artifacts:
            raise RuntimeError('Master interrupted before terminal commit: ' + result.error)
        # Even a textual success cannot override the persisted master lifecycle outcome.
        manifest=verify_terminal(self.services['workspace'],result.artifacts,example_dir=example_dir,domain=domain)
        return dict(status=manifest['status'],manifest=manifest,duration_s=time.monotonic()-start,
                    error=result.error if manifest['status']=='failed' else None)
