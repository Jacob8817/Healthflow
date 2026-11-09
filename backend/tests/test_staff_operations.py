from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.operations import router as operations_router
from app.api.router import router
from app.db.base import Base
from app.db.models import AuditLog, ForecastRun, Hospital, OptimisationPlan, User
from app.services.optimisation import OptimisationService
from app.services.simulation import SimulationService


@pytest.fixture
def workspace():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(operations_router, prefix='/api/v1')
    app.include_router(router, prefix='/api/v1')
    current = SimpleNamespace(id=1, role='admin')
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: current
    app.state.optimisation_service = OptimisationService()
    app.state.simulation_service = SimulationService()
    app.state.forecast_service = None  # Viewer rejection must occur before inference.
    with sessions() as db:
        db.add(User(id=1, email='test@example.invalid', full_name='Test staff', password_hash='unused', role='admin'))
        db.commit()
    with TestClient(app) as client:
        yield client, sessions, current
    engine.dispose()


def setup_ward(client, hospital='TEST-01'):
    assert client.post('/api/v1/operations/hospitals', json={'id': hospital, 'name': 'Test Hospital'}).status_code == 201
    r = client.post(f'/api/v1/operations/{hospital}/wards', json={
        'name': 'Medical', 'floor': 'Ground', 'specialty': 'Medicine', 'bed_count': 2})
    assert r.status_code == 201
    return client.get(f'/api/v1/operations/{hospital}/board').json()


def test_inventory_persistence_and_safe_initial_state(workspace):
    client, sessions, _ = workspace
    board = setup_ward(client)
    assert board['counts']['total'] == 2
    assert board['counts']['available'] == 0
    assert board['counts']['blocked'] == 2
    assert not any(b['staffed'] for b in board['beds'])
    with sessions() as db:
        assert db.get(Hospital, 'TEST-01').name == 'Test Hospital'
        assert len(db.scalars(select(AuditLog)).all()) == 2


def test_bed_validation_conflict_and_hospital_boundary(workspace):
    client, _, _ = workspace
    bed = setup_ward(client)['beds'][0]
    url = f"/api/v1/operations/TEST-01/beds/{bed['id']}"
    payload = {'status': 'available', 'staffed': False, 'note': '', 'version': 1}
    assert client.patch(url, json=payload).status_code == 422
    payload['staffed'] = True
    assert client.patch(url.replace('TEST-01', 'OTHER'), json=payload).status_code == 404
    r = client.patch(url, json=payload)
    assert r.status_code == 200 and r.json()['version'] == 2
    assert client.patch(url, json=payload).status_code == 409
    assert client.get('/api/v1/operations/TEST-01/board').json()['counts']['available'] == 1


def test_viewer_cannot_edit_or_access_diagnostics(workspace):
    client, _, user = workspace
    setup_ward(client)
    user.role = 'viewer'
    assert client.get('/api/v1/operations/TEST-01/board').status_code == 200
    assert client.post('/api/v1/operations/TEST-01/tasks', json={'title':'Check beds','owner':'Team'}).status_code == 403
    assert client.post('/api/v1/operations/demo').status_code == 403
    assert client.get('/api/v1/model/metrics').status_code == 403
    assert client.get('/api/v1/model/benchmarks').status_code == 403
    assert client.post('/api/v1/forecasts/hospital', json={}).status_code == 403
    assert client.post('/api/v1/simulations', json={}).status_code == 403


def test_resource_month_upsert_and_task_lifecycle(workspace):
    client, _, _ = workspace
    setup_ward(client)
    url='/api/v1/operations/TEST-01'
    resource={'month':'2026-08','available_staff_hours':500,'equipment_available':10,'notes':'Monitor units'}
    assert client.put(url+'/resources', json=resource).status_code == 200
    resource['available_staff_hours']=600
    assert client.put(url+'/resources', json=resource).status_code == 200
    task=client.post(url+'/tasks',json={'title':'Review blocked beds','owner':'Bed team'}).json()
    assert client.patch(url+f"/tasks/{task['id']}",json={'status':'in_progress'}).status_code == 200
    board=client.get(url+'/board').json()
    assert len(board['resources']) == 1 and board['resources'][0]['available_staff_hours'] == 600
    assert board['tasks'][0]['status'] == 'in_progress'


def test_emergency_counts_are_staff_recorded_and_validated(workspace):
    client, _, _ = workspace
    setup_ward(client)
    payload={'awaiting_assessment':5,'awaiting_bed':7,'high_priority':4,'medium_priority':11,'low_priority':8}
    assert client.post('/api/v1/operations/TEST-01/emergency',json=payload).status_code == 200
    assert client.get('/api/v1/operations/TEST-01/board').json()['emergency']['high_priority'] == 4
    payload['high_priority']=-1
    assert client.post('/api/v1/operations/TEST-01/emergency',json=payload).status_code == 422


def test_linked_plan_uses_forecast_inventory_month_and_human_review(workspace):
    client, sessions, user = workspace
    board=setup_ward(client)
    for bed in board['beds']:
        assert client.patch(f"/api/v1/operations/TEST-01/beds/{bed['id']}", json={
            'status':'available','staffed':True,'version':1,'note':''}).status_code == 200
    with sessions() as db:
        db.add(ForecastRun(id='forecast-test',hospital_identifier='TEST-01',feature_month='2026-07',target_month='2026-08',
                           raw_prediction=1000,displayed_prediction=1000,model_version='test',warnings=[]))
        db.commit()
    payload={'forecast_id':'forecast-test','average_length_of_stay_hours':20,'target_occupancy':.85,'staff_hours_per_admission':1}
    assert client.post('/api/v1/operations/TEST-01/planning',json=payload).status_code == 422
    client.put('/api/v1/operations/TEST-01/resources',json={'month':'2026-08','available_staff_hours':500,'equipment_available':0})
    r=client.post('/api/v1/operations/TEST-01/planning',json=payload)
    assert r.status_code == 200, r.text
    plan=r.json()
    assert plan['input_data']['horizon_days'] == 31
    assert plan['input_data']['demand'] == 1000
    assert plan['input_data']['staffed_beds'] == 2
    recommendation=plan['recommendation']['recommendation']
    assert recommendation['extra_beds'] == 30
    assert recommendation['extra_staff_hours'] == 500
    assert recommendation['estimated_incremental_cost'] == 30*31*500+500*45
    assert plan['status'] == 'pending_approval'
    user.role='planner'
    approval=f"/api/v1/optimisations/{plan['id']}/approval"
    assert client.post(approval,json={'decision':'approved'}).status_code == 403
    user.role='admin'
    assert client.post(approval,json={'decision':'approved'}).status_code == 200
    assert client.post(approval,json={'decision':'rejected'}).status_code == 409
    with sessions() as db:
        assert db.get(OptimisationPlan,plan['id']).status == 'approved'
    payload['max_extra_beds']=0
    failed=client.post('/api/v1/operations/TEST-01/planning',json=payload).json()
    assert failed['status'] == 'infeasible'
    assert client.post(f"/api/v1/optimisations/{failed['id']}/approval",json={'decision':'approved'}).status_code == 409


def test_planning_rejects_forecast_from_other_hospital(workspace):
    client, sessions, _ = workspace
    setup_ward(client)
    with sessions() as db:
        db.add(ForecastRun(id='other',hospital_identifier='OTHER',feature_month='2026-07',target_month='2026-08',
                           raw_prediction=100,displayed_prediction=100,model_version='test',warnings=[])); db.commit()
    r=client.post('/api/v1/operations/TEST-01/planning',json={'forecast_id':'other'})
    assert r.status_code == 422 and 'this hospital' in r.json()['detail']


def test_shift_coverage_and_equipment_update_validation(workspace):
    client, _, _ = workspace
    setup_ward(client)
    url='/api/v1/operations/TEST-01'
    shift={'shift_date':'2026-08-01','shift':'Day','team':'Emergency nursing',
           'required_staff':12,'available_staff':10,'hours_per_person':8}
    assert client.put(url+'/shifts',json=shift).status_code == 200
    shift['available_staff']=11
    assert client.put(url+'/shifts',json=shift).status_code == 200
    equipment={'name':'Monitor','location':'Emergency','total':12,'available':14}
    assert client.put(url+'/equipment',json=equipment).status_code == 422
    equipment['available']=8
    assert client.put(url+'/equipment',json=equipment).status_code == 200
    equipment['available']=9
    assert client.put(url+'/equipment',json=equipment).status_code == 200
    board=client.get(url+'/board').json()
    assert len(board['shifts']) == 1 and board['shifts'][0]['available_staff'] == 11
    assert len(board['equipment']) == 1 and board['equipment'][0]['available'] == 9
