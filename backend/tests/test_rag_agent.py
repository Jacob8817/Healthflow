import json
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_staff_operations import workspace, setup_ward
from app.services.intelligence import OperationsIntelligenceService, AgentUnavailable
from app.services.agent_tools import HospitalTools
from app.services.retrieval import PolicyRetriever
from app.db.models import PolicyDocument, PolicyChunk, ForecastRun, HospitalForecastHistory, OptimisationPlan
from app.schemas import HospitalForecastRequest


@pytest.fixture
def agent(workspace, monkeypatch):
    client, sessions, user = workspace
    settings=SimpleNamespace(groq_api_key='test-only',groq_model='test',rag_embedding_model='test',rag_cache_dir='unused-test-cache')
    service=OperationsIntelligenceService(settings)
    monkeypatch.setattr(service.retriever,'embed',lambda texts,query=False:np.array([[1.,0.,0.] if any(w in t.lower() for w in ['bed','capacity','surge']) else [0.,1.,0.] for t in texts]))
    client.app.state.intelligence_service=service
    setup_ward(client)
    monkeypatch.setattr(service,'completion',lambda *a,**kw:{'content':'The hospital has two blocked beds [H1].'})
    return client,sessions,user,service


def test_policy_upload_indexes_and_retrieves_citations(agent):
    client,sessions,_,service=agent
    r=client.post('/api/v1/policies/upload',data={'title':'Sample bed policy','source':'Test fixture'},files={'file':('sample.txt',b'When bed capacity is constrained, ask the operational lead to review the recorded situation.','text/plain')})
    assert r.status_code==200
    with sessions() as db:
        results=service.retriever.search(db,'bed capacity')
        assert results[0]['document_id']==r.json()['id']
        assert results[0]['id'].startswith('P') and results[0]['page'] is None
        assert db.scalar(select(PolicyChunk)) is not None
    duplicate=client.post('/api/v1/policies',json={'title':'Same','content':'When bed capacity is constrained, ask the operational lead to review the recorded situation.'})
    assert duplicate.json()['id']==r.json()['id']


def test_conversation_is_bound_to_user_and_hospital(agent):
    client,_,user,_=agent
    r=client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-01','message':'How many beds?'})
    assert r.status_code==200 and r.json()['status']=='ok'
    cid=r.json()['conversation_id']
    setup_ward(client,'TEST-02')
    assert client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-02','conversation_id':cid,'message':'Read previous hospital'}).status_code==404
    assert client.get(f'/api/v1/operations-intelligence/conversations/{cid}',params={'hospital_id':'TEST-01'}).status_code==200
    user.id=999
    assert client.get(f'/api/v1/operations-intelligence/conversations/{cid}',params={'hospital_id':'TEST-01'}).status_code==404


def test_viewer_compute_and_scope_override_rejected(agent):
    client,sessions,user,service=agent
    user.role='viewer'
    assert client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-01','message':'Run forecast','allow_compute':True}).status_code==403
    with sessions() as db:
        tools=HospitalTools(db,'TEST-01',user,SimpleNamespace(app=client.app),service.retriever,True)
        with pytest.raises(ValueError):tools.call('run_forecast',{})
        with pytest.raises(ValueError):tools.call('hospital_snapshot',{'hospital_id':'OTHER'})
        with pytest.raises(ValueError):tools.call('execute_sql',{'query':'SELECT * FROM users'})
        assert tools.snapshot()['beds']['total']==2


def test_forecast_missing_history_does_not_invent_inputs(agent):
    client,sessions,user,service=agent
    with sessions() as db:
        tools=HospitalTools(db,'TEST-01',user,SimpleNamespace(app=client.app),service.retriever,True)
        result=tools.call('run_forecast',{})
        assert 'No saved validated input history' in result['error']


def test_forecast_form_persists_validated_history_and_tool_uses_it(agent):
    client,sessions,user,service=agent
    import csv
    from pathlib import Path
    rows=list(csv.DictReader((Path(__file__).resolve().parents[2]/'sample_data/hospital_prediction_test.csv').open()))
    seen=[]
    def forecast(hid,name,history):
        seen.append(history)
        return {'forecast_run_id':'test-forecast','hospital':{'identifier':hid},'feature_month':'2026-07','target_month':'2026-08','raw_prediction':4411.,'predicted_emergency_admissions':4411,'model':{'version':'test'},'warnings':[],'data':{'history_end_month':'2026-07'}}
    client.app.state.forecast_service=SimpleNamespace(forecast_hospital=forecast)
    r=client.post('/api/v1/forecasts/hospital',json={'hospital_identifier':'TEST-01','hospital_name':'Test Hospital','history':rows})
    assert r.status_code==200
    with sessions() as db:
        saved=db.get(HospitalForecastHistory,'test-forecast')
        assert len(saved.history)==13
        tools=HospitalTools(db,'TEST-01',user,SimpleNamespace(app=client.app),service.retriever,True)
        preview=tools.call('run_forecast',{})
        assert preview['predicted_emergency_admissions']==4411 and preview['saved'] is False
        assert preview['historical_target'] is True
        assert seen[0]==seen[1]


def test_capacity_preview_no_plan_saved_and_cross_hospital_rejected(agent):
    client,sessions,user,service=agent
    board=client.get('/api/v1/operations/TEST-01/board').json()
    for bed in board['beds']:
        client.patch(f"/api/v1/operations/TEST-01/beds/{bed['id']}",json={'status':'available','staffed':True,'version':1})
    client.put('/api/v1/operations/TEST-01/resources',json={'month':'2026-08','available_staff_hours':500,'equipment_available':2})
    with sessions() as db:
        db.add_all([ForecastRun(id='f',hospital_identifier='TEST-01',feature_month='2026-07',target_month='2026-08',raw_prediction=100,displayed_prediction=100,model_version='test'),ForecastRun(id='foreign',hospital_identifier='OTHER',feature_month='2026-07',target_month='2026-08',raw_prediction=100,displayed_prediction=100,model_version='test')]);db.commit()
        tools=HospitalTools(db,'TEST-01',user,SimpleNamespace(app=client.app),service.retriever,True)
        result=tools.call('preview_capacity',{'forecast_id':'f'})
        assert result['saved'] is False and result['input_data']['horizon_days']==31
        assert db.scalar(select(OptimisationPlan)) is None
        with pytest.raises(HTTPException):tools.call('preview_capacity',{'forecast_id':'foreign'})


def test_agent_tool_round_trip_and_unknown_citation(agent,monkeypatch):
    client,_,_,service=agent
    responses=iter([{'content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':'staffing_equipment_tasks','arguments':'{}'}}]}, {'content':'No staffing records supplied \u3010 H2 \u3011. Unsupported [ P999\u20110 ].' }])
    monkeypatch.setattr(service,'completion',lambda *a,**kw:next(responses))
    r=client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-01','message':'Show staffing'})
    assert r.json()['tools'][0]['status']=='ok'
    assert '[source unavailable]' in r.json()['answer']
    assert '[H2]' in r.json()['answer']
    assert any(c['id']=='H2' for c in r.json()['citations'])


def test_quota_failure_returns_grounded_failure_state(agent,monkeypatch):
    client,_,_,service=agent
    def limited(*a,**kw):raise AgentUnavailable('rate_limited','Quota exhausted; retry later.')
    monkeypatch.setattr(service,'completion',limited)
    result=client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-01','message':'Beds?'}).json()
    assert result['status']=='rate_limited' and result['tools']==[]


def test_pdf_page_boundaries_and_empty_upload(agent):
    client,_,_,_=agent
    pieces=PolicyRetriever.split('First page bed policy.\fSecond page staffing policy.\f')
    assert [x[0] for x in pieces]==[1,2]
    result=client.post('/api/v1/policies/upload',data={'title':'Empty'},files={'file':('blank.txt',b'   ','text/plain')})
    assert result.status_code==422


def test_retrieval_failure_is_disclosed(agent,monkeypatch):
    client,_,_,service=agent
    def fail(*a,**kw):raise RuntimeError('offline')
    monkeypatch.setattr(service.retriever,'search',fail)
    result=client.post('/api/v1/operations-intelligence',json={'hospital_id':'TEST-01','message':'Beds?'}).json()
    assert result['warnings'] and result['status']=='ok'

def test_pdf_upload_preserves_page_citations(agent):
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    client,sessions,_,service=agent
    writer=PdfWriter()
    for text in ['Sample bed capacity reference on first page.', 'Staffing review reference on second page.']:
        page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    data=io.BytesIO();writer.write(data)
    r=client.post('/api/v1/policies/upload',data={'title':'PDF verification reference'},files={'file':('test.pdf',data.getvalue(),'application/pdf')})
    assert r.status_code==200
    with sessions() as db:
        chunks=db.scalars(select(PolicyChunk).where(PolicyChunk.document_id==r.json()['id']).order_by(PolicyChunk.position)).all()
        assert [c.page for c in chunks]==[1,2]
        assert 'first page' in chunks[0].content and 'second page' in chunks[1].content
