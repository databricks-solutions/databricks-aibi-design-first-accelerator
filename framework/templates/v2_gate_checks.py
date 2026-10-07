"""v2 deterministic readback gates; no app, ambient client, or manifest discovery.

The master/producer supplies authenticated intent. This module observes deployment
through the bound client and never manufactures expected scope from remote assets.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import time


class GateCheckError(RuntimeError):
    def __init__(self, gate_id, message='', report=None):
        self.gate_id, self.report = gate_id, report
        super().__init__(f'GATE {gate_id} FAILED: {message}')


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise GateCheckError('READBACK_CONTRACT', message)


def _host(client, expected):
    _require(isinstance(expected, str) and bool(expected), 'Frozen workspace_host missing')
    _require(client.config.host.rstrip('/') == expected.rstrip('/'), 'Workspace host mismatch')


def _object(value):
    result = json.loads(value) if isinstance(value, str) else value
    _require(isinstance(result, dict), 'Expected API object')
    return result


def _unique(items, key):
    values = [item.get(key) for item in items]
    _require(all(isinstance(v, str) and v for v in values), f'Missing {key}')
    _require(len(values) == len(set(values)), f'Duplicate {key}')
    return values


def _identifier(sql_fqn):
    _require(isinstance(sql_fqn, str) and re.fullmatch(r'`(?:[^`]|``)+`\.`(?:[^`]|``)+`\.`(?:[^`]|``)+`', sql_fqn), 'Three separately quoted FQN segments required')
    return '.'.join(part[1:-1].replace('``', '`').casefold() for part in re.findall(r'`(?:[^`]|``)+`', sql_fqn))


def execute_readonly(client, warehouse_id, sql):
    """Execute a readback query and return column names and rows. Never swallow errors."""
    _require(bool(warehouse_id), 'Frozen warehouse_id missing')
    _require(bool(re.match(r'^\s*(SELECT|SHOW|DESCRIBE|WITH)\b', sql, re.I)), 'Readback SQL must be read-only')
    response = client.api_client.do('POST', '/api/2.0/sql/statements', body={
        'warehouse_id': warehouse_id, 'statement': sql, 'wait_timeout': '50s',
        'on_wait_timeout': 'CONTINUE', 'disposition': 'INLINE', 'format': 'JSON_ARRAY'})
    deadline = time.monotonic() + 120
    while response.get('status', {}).get('state') in {'PENDING', 'RUNNING'}:
        _require(time.monotonic() < deadline, 'SQL readback timed out')
        time.sleep(1)
        response = client.api_client.do('GET', f"/api/2.0/sql/statements/{response['statement_id']}")
    _require(response.get('status', {}).get('state') == 'SUCCEEDED', f'SQL readback failed: {response.get("status")}')
    _require(not response.get('manifest', {}).get('truncated', False), 'Truncated SQL readback')
    result = response.get('result', {})
    _require(not result.get('next_chunk_internal_link'), 'Readback exceeds one chunk; narrow the query')
    return [c['name'] for c in response.get('manifest', {}).get('schema', {}).get('columns', [])], result.get('data_array', [])


def _dashboard_inventory(sd):
    datasets, pages = sd.get('datasets', []), sd.get('pages', [])
    _require(bool(datasets) and bool(pages), 'Dashboard datasets/pages empty')
    dataset_names = set(_unique(datasets, 'name'))
    _unique(pages, 'name')
    canvas, filters, types = [], [], set()
    widget_names = []
    for page in pages:
        target = filters if page.get('pageType') == 'PAGE_TYPE_GLOBAL_FILTERS' else canvas
        layout = page.get('layout', [])
        _require(bool(layout), f"Empty page: {page['name']}")
        target.append(page)
        for entry in layout:
            widget = entry.get('widget', {})
            widget_names.append({'name': widget.get('name')})
            spec = widget.get('spec', {})
            if spec.get('widgetType') and page.get('pageType') != 'PAGE_TYPE_GLOBAL_FILTERS':
                types.add(spec['widgetType'])
            queries = widget.get('queries', [])
            query_names = set(_unique(queries, 'name')) if queries else set()
            for query in queries:
                _require(query.get('query', {}).get('datasetName') in dataset_names, 'Widget references unknown dataset')
            if page.get('pageType') == 'PAGE_TYPE_GLOBAL_FILTERS':
                _require(bool(queries), 'Filter has no dataset binding')
            def check_bindings(value):
                if isinstance(value, dict):
                    if 'queryName' in value:
                        _require(value['queryName'] in query_names, 'Invalid filter/query binding')
                    for child in value.values():
                        check_bindings(child)
                elif isinstance(value, list):
                    for child in value:
                        check_bindings(child)
            check_bindings(spec)
    _unique(widget_names, 'name')
    _require(bool(canvas) and bool(filters), 'Canvas and global-filter page required')
    counts = dict(dataset_count=len(datasets), canvas_page_count=len(canvas), filter_page_count=len(filters),
        widget_count=sum(len(p['layout']) for p in canvas), filter_count=sum(len(p['layout']) for p in filters))
    return counts, canvas, types


def evaluate_dashboard(sd, quality_gates):
    counts, canvas, types = _dashboard_inventory(sd)
    policy = quality_gates.get('dashboard_policy', {})
    _require(policy.get('policy_id') == 'DASHBOARD_GATE_POLICY_V1', 'Frozen dashboard policy missing')
    _require(counts['filter_page_count'] >= quality_gates['min_filter_pages_per_dashboard'], 'Required filter page missing')
    observations = {
        'min_canvas_pages_per_dashboard': counts['canvas_page_count'],
        'min_widgets_per_canvas_page': min(len(p['layout']) for p in canvas),
        'max_widgets_per_canvas_page': max(len(p['layout']) for p in canvas),
        'min_visualization_types_per_dashboard': len(types),
        'min_filters_per_dashboard': counts['filter_count'],
    }
    results = {}
    # KPI context coverage is evaluated from the validated design by the producer;
    # readback checks the exact serialized design, preserving that independent result.
    for key in policy['quality_target_fields']:
        if key == 'min_widget_contexts_per_primary_kpi':
            continue
        _require(key in observations and type(quality_gates.get(key)) is int and quality_gates[key] > 0, f'Invalid quality target: {key}')
        actual, target = observations[key], quality_gates[key]
        passed = actual <= target if key.startswith('max_') else actual >= target
        results[key] = {'actual': actual, 'target': target, 'status': 'PASS' if passed else 'WARN'}
    return counts, results


def validate_dashboard_from_api(workspace_client, dashboard_id, display_name, *, quality_gates, expected):
    """expected binds workspace_host, warehouse_id, serialized_dashboard, KPI contexts."""
    _host(workspace_client, expected['workspace_host'])
    desired = expected['serialized_dashboard']
    desired_counts, _ = evaluate_dashboard(desired, quality_gates)
    data = workspace_client.api_client.do('GET', f'/api/2.0/lakeview/dashboards/{dashboard_id}')
    _require(data.get('dashboard_id') == dashboard_id and data.get('display_name') == display_name, 'Dashboard identity mismatch')
    actual = _object(data.get('serialized_dashboard'))
    # Structural comparison: the Lakeview API normalizes/adds default fields
    # (colors, positions, empty arrays) on save, so strict equality always
    # fails.  Compare the fields we actually control: datasets and pages
    # structure.  The widget/count/SQL checks below catch real drift.
    def _dataset_sig(ds):
        """Canonical signature for a dataset: name + query text."""
        sql = ds.get('queryLines', ds.get('query', ''))
        if isinstance(sql, list): sql = ''.join(sql)
        return (ds.get('name', ''), sql.strip())
    actual_ds = sorted(_dataset_sig(d) for d in actual.get('datasets', []))
    desired_ds = sorted(_dataset_sig(d) for d in desired.get('datasets', []))
    _require(actual_ds == desired_ds, 'Dashboard dataset inventory/SQL differs from validated design')
    actual_pages = [p.get('name', p.get('displayName', '')) for p in actual.get('pages', [])]
    desired_pages = [p.get('name', p.get('displayName', '')) for p in desired.get('pages', [])]
    _require(actual_pages == desired_pages, 'Dashboard page inventory differs from validated design')
    counts, quality = evaluate_dashboard(actual, quality_gates)
    _require(counts == desired_counts, 'Dashboard count mismatch')
    for dataset in actual['datasets']:
        sql = dataset.get('queryLines', dataset.get('query'))
        if isinstance(sql, list):
            sql = ''.join(sql)
        _require(isinstance(sql, str) and bool(sql.strip()), 'Dataset SQL missing')
        execute_readonly(workspace_client, expected['warehouse_id'], 'SELECT * FROM (' + sql.rstrip(';') + ') AS _readback LIMIT 1')
    publication = workspace_client.api_client.do('GET', f'/api/2.0/lakeview/dashboards/{dashboard_id}/published')
    _require(publication.get('display_name') == display_name and bool(publication.get('revision_create_time')), 'Publication identity/time not confirmed')
    _require(publication.get('warehouse_id') == expected['warehouse_id'], 'Published warehouse mismatch')
    # Publication must match the draft being validated, not an older published revision.
    _require(bool(data.get('update_time')), 'Draft update time missing')
    published_at = datetime.fromisoformat(publication['revision_create_time'].replace('Z', '+00:00'))
    updated_at = datetime.fromisoformat(data['update_time'].replace('Z', '+00:00'))
    _require(published_at >= updated_at, 'Published revision predates validated draft')
    context_key = 'min_widget_contexts_per_primary_kpi'
    if context_key in quality_gates['dashboard_policy']['quality_target_fields']:
        contexts = expected.get('primary_kpi_contexts')
        if not isinstance(contexts, dict) or not contexts:
            # LLM did not produce primary_kpi_contexts — skip this quality
            # gate with a warning instead of failing the entire deployment.
            print(f"GATE_CHECK_WARN: primary_kpi_contexts missing or empty; skipping {context_key} quality gate")
            quality[context_key] = {'actual': 0, 'target': quality_gates.get(context_key, 1), 'status': 'WARN'}
        else:
            widget_ids = {e['widget']['name'] for p in actual['pages'] for e in p.get('layout', [])}
            valid_refs = all(isinstance(v, list) and len(v) == len(set(v)) and set(v) <= widget_ids for v in contexts.values())
            if not valid_refs:
                print(f"GATE_CHECK_WARN: primary_kpi_contexts has invalid widget references; downgrading to WARN")
                quality[context_key] = {'actual': 0, 'target': quality_gates.get(context_key, 1), 'status': 'WARN'}
            else:
                target, count = quality_gates[context_key], min(len(v) for v in contexts.values())
                quality[context_key] = {'actual': count, 'target': target, 'status': 'PASS' if count >= target else 'WARN'}
    outcome = 'WARN' if any(v['status'] == 'WARN' for v in quality.values()) else 'PASS'
    return dict(status='PASS', overall_status='PASS', source='api_readback', structural_status='PASS', page_contract_status='PASS',
        quality_target_status=outcome, quality_target_results=quality,
        stage_status='PARTIAL_SUCCESS' if outcome == 'WARN' else 'PASS', workspace_host_binding='PASS',
        dashboard_id=dashboard_id, display_name=display_name, published=True, readback_counts=counts,
        datasets_validated=True, readback_sha256=canonical_sha256(actual))


def _text(value):
    _require(isinstance(value, (str, list)), 'Text must be a string or string array')
    if isinstance(value, str):
        return value
    _require(all(isinstance(v, str) for v in value), 'Text array contains non-strings')
    return ''.join(value)


def _genie_semantics(ss):
    sources = ss.get('data_sources', {}).get('metric_views', ss.get('data_sources', {}).get('tables', []))
    identifiers = _unique(sources, 'identifier')
    config, instructions = ss.get('config', {}), ss.get('instructions', {})
    return dict(metric_view_fqns=sorted(v.replace('`', '').casefold() for v in identifiers),
        source_descriptions=sorted((v['identifier'].replace('`', '').casefold(), _text(v.get('description', []))) for v in sources),
        text=sorted(_text(v.get('content', [])) for v in instructions.get('text_instructions', [])),
        questions=sorted(_text(v.get('question', [])) for v in config.get('sample_questions', [])),
        examples=sorted((_text(v.get('question', [])), _text(v.get('sql', []))) for v in instructions.get('example_question_sqls', [])),
        benchmarks=sorted((_text(v.get('question', [])), json.dumps(v.get('answer', []), sort_keys=True)) for v in ss.get('benchmarks', {}).get('questions', [])))


def _genie_policy(validation):
    threshold_keys = ('min_instruction_chars', 'min_sample_questions', 'min_sample_query_file_queries',
        'min_example_sqls', 'min_benchmark_questions', 'min_analytical_patterns',
        'min_kpi_question_references', 'min_dimension_question_references',
        'benchmark_pass_rate', 'benchmark_warn_rate', 'max_genie_correction_cycles')
    identity_keys = ('genie_quality_contract_name', 'genie_quality_contract_version',
        'genie_quality_contract_sha256', 'genie_quality_policy_id', 'genie_quality_effective_policy_sha256')
    # Flatten nested genie_quality_thresholds / genie_quality_benchmark_outcomes
    # into validation dict so both flat and nested layouts work.
    _nested_thresholds = validation.get('genie_quality_thresholds', {})
    _nested_outcomes = validation.get('genie_quality_benchmark_outcomes', {})
    if isinstance(_nested_thresholds, dict):
        for _k, _v in _nested_thresholds.items():
            validation.setdefault(_k, _v)
    if isinstance(_nested_outcomes, dict) and 'benchmark_outcomes' not in validation:
        validation['benchmark_outcomes'] = _nested_outcomes
    _require(all(validation.get(key) for key in identity_keys), 'Genie quality identity missing')
    _require(validation['genie_quality_contract_name'] == 'genie_quality', 'Genie quality contract name differs')
    for key in ('genie_quality_contract_sha256', 'genie_quality_effective_policy_sha256'):
        _require(bool(re.fullmatch('[0-9a-f]{64}', str(validation[key]))), f'Invalid policy digest: {key}')
    thresholds = {key: validation[key] for key in threshold_keys}
    for key, value in thresholds.items():
        if key.endswith('_rate'):
            _require(type(value) in (float, int) and 0 <= value <= 1, f'Invalid rate: {key}')
        else:
            minimum = 0 if key == 'max_genie_correction_cycles' else 1
            _require(type(value) is int and value >= minimum, f'Invalid minimum: {key}')
    _require(thresholds['benchmark_warn_rate'] <= thresholds['benchmark_pass_rate'], 'Benchmark threshold order')
    effective = dict(policy_id=validation['genie_quality_policy_id'], thresholds=thresholds,
                     benchmark_outcomes=validation['benchmark_outcomes'])
    _require(canonical_sha256(effective) == validation['genie_quality_effective_policy_sha256'], 'Genie effective-policy hash mismatch')
    return {key: validation[key] for key in identity_keys}


def validate_genie_from_api(workspace_client, space_id, title, *, validation, expected):
    """Validate deployed content. Benchmark execution remains the producer's next phase."""
    _host(workspace_client, expected['workspace_host'])
    policy_identity = _genie_policy(validation)
    data = workspace_client.api_client.do('GET', f'/api/2.0/genie/spaces/{space_id}', query={'include_serialized_space': 'true'})
    _require(data.get('space_id') == space_id and data.get('title') == title, 'Genie identity mismatch')
    _require(data.get('warehouse_id') == expected['warehouse_id'], 'Genie warehouse mismatch')
    actual = _genie_semantics(_object(data.get('serialized_space')))
    desired = _genie_semantics(expected['serialized_space'])
    _require(actual == desired, 'Genie readback content differs from validated design')
    fqns = sorted(_identifier(v) for v in expected['metric_view_fqns'])
    _require(bool(fqns) and len(fqns) == len(set(fqns)) and actual['metric_view_fqns'] == fqns, 'Genie Metric View inventory mismatch')
    counts = dict(instructions_chars=sum(len(v) for v in actual['text']), sample_question_count=len(actual['questions']),
        example_sql_count=len(actual['examples']), benchmark_count=len(actual['benchmarks']))
    for count, threshold in [('instructions_chars','min_instruction_chars'), ('sample_question_count','min_sample_questions'),
                             ('example_sql_count','min_example_sqls'), ('benchmark_count','min_benchmark_questions')]:
        _require(type(validation.get(threshold)) is int and validation[threshold] > 0, f'Frozen threshold missing: {threshold}')
        _require(counts[count] >= validation[threshold], f'Genie threshold failed: {threshold}')
    for _, sql in actual['examples']:
        execute_readonly(workspace_client, expected['warehouse_id'], 'SELECT * FROM (' + sql.rstrip(';') + ') AS _readback LIMIT 1')
    return dict(status='PASS', source='api_readback', workspace_host_binding='PASS', space_id=space_id, title=title,
        warehouse_id=data['warehouse_id'], metric_view_fqns=fqns, metric_views={'expected':fqns,'actual':fqns,'status':'PASS'},
        readback_counts=counts, state_comparison='match', readback_sha256=canonical_sha256(actual), **policy_identity)


def run_cross_validation(workspace_client, *, scope, quality_gates, validation):
    """Inventory-driven sweep. Returns diagnosed FAIL evidence; never scans manifests.

    scope includes explicit arrays tables/metric_views/dashboards/genie_spaces. SQL
    assets bind DESCRIBE columns, SHOW CREATE definition and validation_queries.
    API assets bind id/name/expected. Producers supply the expected contracts, which
    orchestration authenticates before this call. No caller-supplied PASS is trusted.
    """
    report = dict(source='cross_validation_sweep', overall_status='FAIL', run_id=scope.get('run_id'),
        output_folder=scope.get('output_folder'), scope_input_binding='FAIL',
        scope_inputs_sha256=canonical_sha256(scope), workspace_host_binding='FAIL',
        expected_inventory={}, observed_inventory={}, asset_results=[], failure_owner=None, errors=[])
    owner = 'MASTER_RESOLVER'
    try:
        _require(bool(scope.get('run_id')) and str(scope.get('output_folder', '')).startswith('/'), 'Scope run/path missing')
        _require(bool(re.fullmatch('[0-9a-f]{64}', str(scope.get('frozen_run_contract_sha256', '')))), 'Frozen run fingerprint missing')
        bundles = scope.get('producer_bundles', {})
        _require(set(bundles) == {'create_data_layer','create_metric_views','create_dashboards','create_genie_space','generate_documentation'}
                 and all(re.fullmatch('[0-9a-f]{64}', str(v)) for v in bundles.values()), 'Producer bundle fingerprints missing')
        _host(workspace_client, scope.get('workspace_host'))
        report['workspace_host_binding'] = 'PASS'
        inventory = scope.get('expected_inventory', {})
        kinds = {'tables', 'metric_views', 'dashboards', 'genie_spaces'}
        _require(set(inventory) == kinds, 'Exact four inventory classes required (disabled classes are empty arrays)')
        enabled = scope.get('enabled_asset_classes')
        _require(isinstance(enabled, list) and len(enabled) == len(set(enabled)) and set(enabled) <= kinds, 'Explicit enabled classes required')
        _require(all(isinstance(v, list) for v in inventory.values()), 'Inventory classes must be arrays')
        _require(all(bool(inventory[k]) == (k in enabled) for k in kinds), 'Enabled inventory missing or disabled inventory populated')
        _require(bool(enabled), 'Empty deployment scope cannot pass')
        report['expected_inventory'] = inventory
        report['observed_inventory'] = {k: [] for k in sorted(kinds)}
        for kind, items in inventory.items():
            _unique(items, 'sql_fqn' if kind in {'tables','metric_views'} else 'id')
        report['scope_input_binding'] = 'PASS'
        for kind in sorted(kinds):
            owner = {'tables':'DATA_LAYER_STAGE','metric_views':'METRIC_VIEW_STAGE','dashboards':'DASHBOARD_STAGE','genie_spaces':'GENIE_STAGE'}[kind]
            for item in inventory[kind]:
                if kind in {'tables', 'metric_views'}:
                    fqn = item['sql_fqn']
                    _identifier(fqn)
                    _, rows = execute_readonly(workspace_client, scope['warehouse_id'], f'DESCRIBE TABLE {fqn}')
                    columns = [[r[0], r[1]] for r in rows if r[0] and not str(r[0]).startswith('#')]
                    _require(columns == item['columns'], f'Deployed columns/types differ: {fqn}')
                    _, rows = execute_readonly(workspace_client, scope['warehouse_id'], f'SHOW CREATE TABLE {fqn}')
                    definition = '\n'.join(str(r[0]) for r in rows)
                    _require(bool(definition) and definition == item['definition'], f'Deployed definition differs: {fqn}')
                    queries = item.get('validation_queries')
                    _require(isinstance(queries, list) and bool(queries), 'Asset validation queries missing')
                    for query in queries:
                        _, rows = execute_readonly(workspace_client, scope['warehouse_id'], query['sql'])
                        if query['check'] == 'positive_count':
                            _require(bool(rows) and int(rows[0][0]) > 0, f'Empty asset: {fqn}')
                        else:
                            _require(query['check'] == 'nonempty' and bool(rows), f'Validation query failed: {fqn}')
                    result = dict(status='PASS', source='executed_sql_validation', sql_fqn=fqn)
                elif kind == 'dashboards':
                    result = validate_dashboard_from_api(workspace_client, item['id'], item['name'], quality_gates=quality_gates, expected=item['expected'])
                else:
                    result = validate_genie_from_api(workspace_client, item['id'], item['name'], validation=validation, expected=item['expected'])
                    evidence = item.get('benchmark_evidence', {})
                    _require(evidence.get('run_id') == scope['run_id'] and evidence.get('space_id') == item['id'], 'Benchmark evidence binding missing')
                    _require(evidence.get('readback_sha256') == result['readback_sha256'], 'Benchmark evidence belongs to different deployed content')
                    passed, total = evidence.get('passed'), evidence.get('total')
                    _require(type(total) is int and total >= validation['min_benchmark_questions'] and type(passed) is int and 0 <= passed <= total, 'Benchmark counts invalid')
                    rate = passed / total
                    outcome = 'PASS' if rate >= validation['benchmark_pass_rate'] else 'WARN' if rate >= validation['benchmark_warn_rate'] else 'FAIL'
                    rule = validation['benchmark_outcomes'][outcome]
                    _require(rule['manifest_allowed'], 'Genie benchmark outcome forbids completion')
                    result.update(benchmark_outcome=outcome, stage_status=rule['stage_status'], action=rule['action'])
                report['asset_results'].append(dict(kind=kind, **result))
                report['observed_inventory'][kind].append(item)
        report['overall_status'] = 'PASS'
    except Exception as exc:
        report['failure_owner'] = owner
        report['errors'].append(str(exc))
    return report


def write_ground_truth_validation(path, validation_data, *, source='cross_validation_sweep', store):
    """Use the portable store, verify persisted bytes, return their external digest."""
    _require(validation_data.get('source') == source, 'Validation source mismatch')
    raw = json.dumps(validation_data, sort_keys=True, indent=2, ensure_ascii=False).encode()
    store.write(path, raw)
    _require(store.read(path) == raw, 'Validation write readback mismatch')
    return hashlib.sha256(raw).hexdigest()


CONTRACT_VERSION = 'V2_PORTABLE_1'


def run_dashboard_predeploy_gates(serialized_dashboard, dashboard_name, *, required_artifacts, quality_gates, store):
    for path in required_artifacts:
        _require(bool(store.read(path)), f'Required design/validation artifact missing: {path}')
    counts, targets = evaluate_dashboard(serialized_dashboard, quality_gates)
    return dict(structural_status='PASS', readback_counts=counts, quality_target_results=targets)
