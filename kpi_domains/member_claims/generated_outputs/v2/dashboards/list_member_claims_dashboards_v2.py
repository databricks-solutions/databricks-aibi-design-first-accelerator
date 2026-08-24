# Databricks notebook source
# COMMAND ----------
%pip install -q databricks-sdk dbldatagen

dbutils.library.restartPython()

# COMMAND ----------
import dbldatagen

# COMMAND ----------
import json
from databricks.sdk import WorkspaceClient
w=WorkspaceClient()

def api(method,path,body=None,query=None):
    return w.api_client.do(method,path,body=body,query=query or {}) or {}

def list_dashboards():
    out=[]; tok=None
    while True:
        q={'page_size':100}
        if tok: q['page_token']=tok
        d=api('GET','/api/2.0/lakeview/dashboards',query=q)
        out.extend(d.get('dashboards',[]))
        tok=d.get('next_page_token')
        if not tok: break
    return out
names={'member_claims_kpis_dashboard_v2','member_claims_utilization_dashboard_v2'}
res=[]
for d in list_dashboards():
    if (d.get('display_name') or '') in names:
        full=api('GET',f"/api/2.0/lakeview/dashboards/{d['dashboard_id']}")
        sd=full.get('serialized_dashboard') or '{}'
        try: spec=json.loads(sd) if isinstance(sd,str) else sd
        except Exception: spec={}
        res.append({'dashboard_id':d.get('dashboard_id'),'display_name':d.get('display_name'),'warehouse_id':full.get('warehouse_id') or d.get('warehouse_id'),'dataset_count':len(spec.get('datasets',[])),'page_count':len(spec.get('pages',[])),'widget_count':sum(len(p.get('layout',[])) for p in spec.get('pages',[])),'filter_count':len((spec.get('pages') or [{'layout':[]}])[0].get('layout',[])),'pages':[p.get('displayName') for p in spec.get('pages',[])],'datasets':[x.get('name') for x in spec.get('datasets',[])]})
dbutils.notebook.exit(json.dumps(res, sort_keys=True))

