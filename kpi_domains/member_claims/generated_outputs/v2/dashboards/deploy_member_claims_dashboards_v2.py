# Databricks notebook source
# COMMAND ----------
%pip install -q databricks-sdk dbldatagen

dbutils.library.restartPython()

# COMMAND ----------
import dbldatagen

# COMMAND ----------
import json
from databricks.sdk import WorkspaceClient

warehouse_id = '2d8e531640ffa469'
parent_path = '/Users/arun.wagle@databricks.com'
claims_mv = 'aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2'
enroll_mv = 'aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2'
w = WorkspaceClient()


def api(method, path, body=None, query=None):
    resp = w.api_client.do(method, path, body=body, query=query or {})
    return resp or {}


def list_dashboards():
    out, tok = [], None
    while True:
        q = {'page_size': 100}
        if tok:
            q['page_token'] = tok
        data = api('GET', '/api/2.0/lakeview/dashboards', query=q)
        out.extend(data.get('dashboards', []))
        tok = data.get('next_page_token')
        if not tok:
            return out


def delete_matching(display_name):
    deleted = []
    for d in list_dashboards():
        if (d.get('display_name') or '').lower() == display_name.lower():
            api('DELETE', f"/api/2.0/lakeview/dashboards/{d['dashboard_id']}")
            deleted.append(d['dashboard_id'])
    return deleted


def ds(name, display, sql):
    assert sql and sql.strip(), name
    return {'name': name, 'displayName': display, 'queryLines': [sql.strip() + ' ']}


def filter_widget(name, dataset, field, title, wtype, x, y):
    return {'widget': {'name': name, 'queries': [{'name': 'main_query', 'query': {'datasetName': dataset, 'fields': [{'name': field, 'expression': f'`{field}`'}], 'disaggregated': True}}], 'spec': {'version': 2, 'widgetType': wtype, 'encodings': {'fields': [{'fieldName': field, 'displayName': title, 'queryName': 'main_query'}]}, 'frame': {'showTitle': True, 'title': title}}}, 'position': {'x': x, 'y': y, 'width': 2, 'height': 2}}


def counter(name, dataset, field_name, expr, title, x, y):
    return {'widget': {'name': name, 'queries': [{'name': 'main_query', 'query': {'datasetName': dataset, 'fields': [{'name': field_name, 'expression': expr}], 'disaggregated': False}}], 'spec': {'version': 2, 'widgetType': 'counter', 'encodings': {'value': {'fieldName': field_name, 'displayName': title}}, 'frame': {'showTitle': True, 'title': title}}}, 'position': {'x': x, 'y': y, 'width': 2, 'height': 3}}


def bar(name, dataset, dim, dim_title, measure_field, measure_expr, measure_title, title, x, y, width=3, height=5):
    return {'widget': {'name': name, 'queries': [{'name': 'main_query', 'query': {'datasetName': dataset, 'fields': [{'name': dim, 'expression': f'`{dim}`'}, {'name': measure_field, 'expression': measure_expr}], 'disaggregated': False}}], 'spec': {'version': 3, 'widgetType': 'bar', 'encodings': {'x': {'fieldName': dim, 'scale': {'type': 'categorical'}, 'displayName': dim_title}, 'y': {'fieldName': measure_field, 'scale': {'type': 'quantitative'}, 'displayName': measure_title}}, 'frame': {'showTitle': True, 'title': title}}}, 'position': {'x': x, 'y': y, 'width': width, 'height': height}}


def line(name, dataset, time_field, time_title, measure_field, measure_expr, measure_title, title, x, y, width=6, height=5):
    return {'widget': {'name': name, 'queries': [{'name': 'main_query', 'query': {'datasetName': dataset, 'fields': [{'name': time_field, 'expression': f'`{time_field}`'}, {'name': measure_field, 'expression': measure_expr}], 'disaggregated': False}}], 'spec': {'version': 3, 'widgetType': 'line', 'encodings': {'x': {'fieldName': time_field, 'scale': {'type': 'temporal'}, 'displayName': time_title}, 'y': {'fieldName': measure_field, 'scale': {'type': 'quantitative'}, 'displayName': measure_title}}, 'frame': {'showTitle': True, 'title': title}}}, 'position': {'x': x, 'y': y, 'width': width, 'height': height}}


def make_dashboard(datasets, pages):
    dataset_names = {d['name'] for d in datasets}
    assert datasets and pages
    for d in datasets:
        assert d.get('displayName') and d.get('queryLines') and ''.join(d['queryLines']).strip()
    for p in pages:
        assert p.get('pageType') in ('PAGE_TYPE_GLOBAL_FILTERS', 'PAGE_TYPE_CANVAS')
        assert isinstance(p.get('layout'), list)
        for item in p['layout']:
            assert 'widget' in item and 'position' in item
            for q in item['widget'].get('queries', []):
                assert q['query']['datasetName'] in dataset_names, q['query']['datasetName']
    return {'datasets': datasets, 'pages': pages, 'uiSettings': {'theme': {'widgetHeaderAlignment': 'ALIGNMENT_UNSPECIFIED'}, 'applyModeEnabled': False}}


def create_and_publish(display_name, spec):
    deleted = delete_matching(display_name)
    body = {'display_name': display_name, 'warehouse_id': warehouse_id, 'parent_path': parent_path, 'serialized_dashboard': json.dumps(spec)}
    created = api('POST', '/api/2.0/lakeview/dashboards', body=body)
    did = created.get('dashboard_id') or created.get('id')
    if not did:
        raise RuntimeError(f'Create response missing dashboard_id: {created}')
    persisted = api('GET', f'/api/2.0/lakeview/dashboards/{did}')
    sd = persisted.get('serialized_dashboard') or '{}'
    persisted_spec = json.loads(sd) if isinstance(sd, str) else sd
    assert persisted.get('display_name') == display_name
    assert len(persisted_spec.get('datasets', [])) == len(spec['datasets'])
    assert len(persisted_spec.get('pages', [])) == len(spec['pages'])
    published = api('POST', f'/api/2.0/lakeview/dashboards/{did}/published')
    return {'dashboard_id': did, 'display_name': display_name, 'deleted_existing': deleted, 'dataset_count': len(spec['datasets']), 'page_count': len(spec['pages']), 'widget_count': sum(len(p['layout']) for p in spec['pages']), 'filter_count': len(spec['pages'][0]['layout']), 'create_status': 'PASS', 'get_status': 'PASS', 'publish_status': 'PASS', 'published_response': published}

# KPI dashboard specification
kpi_datasets = [
    ds('ds_kpis_total_claims', 'Total Claims', f'SELECT MEASURE(total_claims) AS total_claims FROM {claims_mv}'),
    ds('ds_kpis_avg_paid', 'Average Paid per Claim', f'SELECT MEASURE(average_paid_per_claim) AS average_paid_per_claim FROM {claims_mv}'),
    ds('ds_kpis_claims_shared', 'Claims KPIs Shared', f'SELECT service_date, service_month, line_of_business, claim_type, MEASURE(total_paid_amount) AS total_paid_amount, MEASURE(denied_lines) AS denied_lines, MEASURE(clean_lines) AS clean_lines, MEASURE(total_claim_lines) AS total_claim_lines FROM {claims_mv} GROUP BY service_date, service_month, line_of_business, claim_type'),
    ds('ds_members_by_lob', 'Members by LOB', f'SELECT enrollment_line_of_business, MEASURE(active_enrolled_members) AS active_enrolled_members FROM {enroll_mv} GROUP BY enrollment_line_of_business'),
    ds('ds_members_by_state', 'Members by State', f'SELECT member_state, MEASURE(active_enrolled_members) AS active_enrolled_members FROM {enroll_mv} GROUP BY member_state'),
    ds('ds_members_by_sex', 'Members by Sex', f'SELECT member_sex, MEASURE(active_enrolled_members) AS active_enrolled_members FROM {enroll_mv} GROUP BY member_sex')]
kpi_pages = [
    {'name': 'filters_page', 'displayName': 'Filters', 'pageType': 'PAGE_TYPE_GLOBAL_FILTERS', 'layout': [filter_widget('filter-service-date', 'ds_kpis_claims_shared', 'service_date', 'Service Date', 'filter-date-range-picker', 0, 0), filter_widget('filter-line-of-business', 'ds_kpis_claims_shared', 'line_of_business', 'Line of Business', 'filter-multi-select', 2, 0), filter_widget('filter-claim-type', 'ds_kpis_claims_shared', 'claim_type', 'Claim Type', 'filter-multi-select', 4, 0)]},
    {'name': 'financial_overview', 'displayName': 'Financial Overview', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [counter('kpi-total-claims', 'ds_kpis_total_claims', 'sum(total_claims)', 'SUM(`total_claims`)', 'Total Claims', 0, 0), counter('kpi-total-paid', 'ds_kpis_claims_shared', 'sum(total_paid_amount)', 'SUM(`total_paid_amount`)', 'Total Paid Amount', 2, 0), bar('paid-by-claim-type', 'ds_kpis_claims_shared', 'claim_type', 'Claim Type', 'sum(total_paid_amount)', 'SUM(`total_paid_amount`)', 'Total Paid', 'Paid Amount by Claim Type', 0, 3), bar('paid-by-lob', 'ds_kpis_claims_shared', 'line_of_business', 'Line of Business', 'sum(total_paid_amount)', 'SUM(`total_paid_amount`)', 'Total Paid', 'Paid Amount by LOB', 3, 3)]},
    {'name': 'claims_analysis', 'displayName': 'Claims Analysis', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [counter('avg-paid-per-claim', 'ds_kpis_avg_paid', 'avg(average_paid_per_claim)', 'AVG(`average_paid_per_claim`)', 'Average Paid per Claim', 0, 0), counter('denial-rate', 'ds_kpis_claims_shared', 'denial_rate_calc', 'SUM(`denied_lines`) / SUM(`total_claim_lines`)', 'Denial Rate', 2, 0), counter('clean-claim-rate', 'ds_kpis_claims_shared', 'clean_claim_rate_calc', 'SUM(`clean_lines`) / SUM(`total_claim_lines`)', 'Clean Claim Rate', 4, 0), line('monthly-paid-trend', 'ds_kpis_claims_shared', 'service_month', 'Service Month', 'sum(total_paid_amount)', 'SUM(`total_paid_amount`)', 'Total Paid', 'Monthly Paid Trend', 0, 3)]},
    {'name': 'member_demographics', 'displayName': 'Member Demographics', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [bar('members-by-lob', 'ds_members_by_lob', 'enrollment_line_of_business', 'Line of Business', 'sum(active_enrolled_members)', 'SUM(`active_enrolled_members`)', 'Active Members', 'Members by Line of Business', 0, 0), bar('members-by-state', 'ds_members_by_state', 'member_state', 'State', 'sum(active_enrolled_members)', 'SUM(`active_enrolled_members`)', 'Active Members', 'Members by Geography', 3, 0), bar('members-by-sex', 'ds_members_by_sex', 'member_sex', 'Sex', 'sum(active_enrolled_members)', 'SUM(`active_enrolled_members`)', 'Active Members', 'Member Sex Breakdown', 0, 5, 6, 5)]}]

# Utilization dashboard specification
util_datasets = [
    ds('ds_util_total_counts', 'Utilization Total Counts', f'SELECT MEASURE(total_claims) AS total_claims, MEASURE(total_claim_lines) AS total_claim_lines FROM {claims_mv}'),
    ds('ds_util_patterns', 'Utilization Patterns', f'SELECT service_date, line_of_business, claim_type, MEASURE(total_claims) AS total_claims, MEASURE(inpatient_paid_amount) AS inpatient_paid_amount, MEASURE(outpatient_paid_amount) AS outpatient_paid_amount FROM {claims_mv} GROUP BY service_date, line_of_business, claim_type'),
    ds('ds_claims_by_type', 'Claims By Type', f'SELECT claim_type, MEASURE(total_claims) AS total_claims FROM {claims_mv} GROUP BY claim_type'),
    ds('ds_in_out_paid', 'Inpatient Outpatient Paid', f"SELECT service_date, line_of_business, claim_type, 'Inpatient Paid' AS paid_category, MEASURE(inpatient_paid_amount) AS paid_amount FROM {claims_mv} GROUP BY service_date,line_of_business,claim_type UNION ALL SELECT service_date, line_of_business, claim_type, 'Outpatient Paid' AS paid_category, MEASURE(outpatient_paid_amount) AS paid_amount FROM {claims_mv} GROUP BY service_date,line_of_business,claim_type"),
    ds('ds_provider_insights', 'Provider Insights', f'SELECT service_date, line_of_business, rendering_provider_specialty, MEASURE(total_paid_amount) AS total_paid_amount, MEASURE(par_paid_amount) AS par_paid_amount FROM {claims_mv} GROUP BY service_date, line_of_business, rendering_provider_specialty'),
    ds('ds_operational_metrics', 'Operational Metrics', f'SELECT service_date, service_month, line_of_business, claim_type, MEASURE(denied_lines) AS denied_lines, MEASURE(total_claim_lines) AS total_claim_lines, MEASURE(total_paid_amount) AS total_paid_amount, MEASURE(total_billed_amount) AS total_billed_amount, MEASURE(total_allowed_amount) AS total_allowed_amount FROM {claims_mv} GROUP BY service_date, service_month, line_of_business, claim_type')]
util_pages = [
    {'name': 'filters_page', 'displayName': 'Filters', 'pageType': 'PAGE_TYPE_GLOBAL_FILTERS', 'layout': [filter_widget('filter-service-date', 'ds_util_patterns', 'service_date', 'Service Date', 'filter-date-range-picker', 0, 0), filter_widget('filter-line-of-business', 'ds_util_patterns', 'line_of_business', 'Line of Business', 'filter-multi-select', 2, 0), filter_widget('filter-claim-type', 'ds_util_patterns', 'claim_type', 'Claim Type', 'filter-multi-select', 4, 0)]},
    {'name': 'utilization_patterns', 'displayName': 'Utilization Patterns', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [counter('util-total-claims', 'ds_util_total_counts', 'sum(total_claims)', 'SUM(`total_claims`)', 'Total Claims', 0, 0), counter('util-total-lines', 'ds_util_total_counts', 'sum(total_claim_lines)', 'SUM(`total_claim_lines`)', 'Total Claim Lines', 2, 0), bar('inpatient-outpatient-paid', 'ds_in_out_paid', 'paid_category', 'Paid Category', 'sum(paid_amount)', 'SUM(`paid_amount`)', 'Paid Amount', 'Inpatient vs Outpatient Paid', 0, 3), bar('claims-by-type', 'ds_claims_by_type', 'claim_type', 'Claim Type', 'sum(total_claims)', 'SUM(`total_claims`)', 'Total Claims', 'Claims by Claim Type', 3, 3)]},
    {'name': 'provider_insights', 'displayName': 'Provider Insights', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [bar('specialty-rankings', 'ds_provider_insights', 'rendering_provider_specialty', 'Specialty', 'sum(total_paid_amount)', 'SUM(`total_paid_amount`)', 'Total Paid', 'Specialty Rankings by Paid Amount', 0, 0, 6, 5), counter('par-provider-rate', 'ds_provider_insights', 'par_provider_rate_calc', 'SUM(`par_paid_amount`) / SUM(`total_paid_amount`)', 'Participating Provider Rate', 0, 5)]},
    {'name': 'operational_metrics', 'displayName': 'Operational Metrics', 'pageType': 'PAGE_TYPE_CANVAS', 'layout': [line('denial-trend', 'ds_operational_metrics', 'service_month', 'Service Month', 'denial_rate_calc', 'SUM(`denied_lines`) / SUM(`total_claim_lines`)', 'Denial Rate', 'Monthly Denial Rate Trend', 0, 0), counter('payment-to-billed', 'ds_operational_metrics', 'payment_to_billed_calc', 'SUM(`total_paid_amount`) / SUM(`total_billed_amount`)', 'Payment-to-Billed Ratio', 0, 5), counter('payment-to-allowed', 'ds_operational_metrics', 'payment_to_allowed_calc', 'SUM(`total_paid_amount`) / SUM(`total_allowed_amount`)', 'Payment-to-Allowed Ratio', 2, 5)]}]

specs = {
    'member_claims_kpis_dashboard_v2': make_dashboard(kpi_datasets, kpi_pages),
    'member_claims_utilization_dashboard_v2': make_dashboard(util_datasets, util_pages)
}
results = {name: create_and_publish(name, spec) for name, spec in specs.items()}
print('DASHBOARD_DEPLOYMENT_RESULT_JSON=' + json.dumps(results, sort_keys=True))

