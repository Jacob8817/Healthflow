"""Allow-listed agent tools. Hospital scope comes from the authenticated request, never the LLM."""
from datetime import date, datetime, timezone
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from app.api.operations import inventory, PlanningIn, calculate_plan
from app.db.models import (Hospital, EmergencySnapshot, ResourceRecord, ForecastRun,
    StaffShift, EquipmentStock, OperationalTask, OptimisationPlan, HospitalForecastHistory)
from app.schemas import HospitalForecastRequest


def record(row, fields):
    return {field: jsonable_encoder(getattr(row, field)) for field in fields} if row else None


class HospitalTools:
    def __init__(self, db, hospital_id, user, request, retriever, allow_compute=False):
        self.db, self.hospital_id, self.user = db, hospital_id, user
        self.request, self.retriever = request, retriever
        self.allow_compute = allow_compute and user.role in ('admin', 'planner')
        self.sources = {}
        self.trace = []

    def snapshot(self):
        db, hid = self.db, self.hospital_id
        hospital = db.get(Hospital, hid)
        wards, beds, counts = inventory(db, hid)
        emergency = db.scalar(select(EmergencySnapshot).where(EmergencySnapshot.hospital_id == hid).order_by(EmergencySnapshot.id.desc()))
        forecasts = db.scalars(select(ForecastRun).where(ForecastRun.hospital_identifier == hid).order_by(ForecastRun.created_at.desc()).limit(3)).all()
        resources = db.scalars(select(ResourceRecord).where(ResourceRecord.hospital_id == hid).order_by(ResourceRecord.month.desc()).limit(12)).all()
        result = {'hospital': record(hospital, ['id','name','data_origin']), 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'scope': 'Latest staff-maintained records, not live hospital telemetry; missing records are unknown, not zero.',
                  'beds': counts, 'inventory_updated_at': max((b.updated_at.isoformat() for b in beds), default=None),
                  'wards': [{'name':w.name, 'floor':w.floor, 'specialty':w.specialty,
                             'total':sum(b.ward_id == w.id for b in beds),
                             'available':sum(b.ward_id == w.id and b.staffed and b.status == 'available' for b in beds)} for w in wards],
                  'emergency': record(emergency, ['awaiting_assessment','awaiting_bed','high_priority','medium_priority','low_priority','updated_at']),
                  'forecasts': [record(f,['id','target_month','displayed_prediction','feature_month','created_at']) | {'historical_target': f.target_month < date.today().strftime('%Y-%m')} for f in forecasts],
                  'monthly_resources': [record(r,['month','available_staff_hours','equipment_available','updated_at']) for r in resources]}
        self.sources['H1'] = {'id':'H1','kind':'hospital','title':f'{hospital.name}: recorded hospital state',
                               'excerpt':'Beds, wards, emergency counts, saved forecasts and monthly resources.',
                               'updated_at':result['retrieved_at'], 'source':'/operations/'+hid+'/board'}
        return result

    def definitions(self):
        def tool(name, desc, props=None, required=None):
            return {'type':'function','function':{'name':name,'description':desc,'parameters':{
                'type':'object','properties':props or {},'required':required or [],'additionalProperties':False}}}
        definitions = [
            tool('search_policies','Search local indexed policies by meaning and keywords. Pass a specific query.',{'query':{'type':'string','maxLength':1000}},['query']),
            tool('hospital_snapshot','Read beds, wards, emergency counts, latest saved forecasts and monthly capacity. Cite [H1].'),
            tool('staffing_equipment_tasks','Read recorded shifts, equipment and tasks for the selected hospital. Cite [H2].'),
            tool('saved_capacity_plans','Read the latest recorded capacity plans and their approval state. Cite [H3].'),
        ]
        if self.allow_compute:
            definitions += [tool('run_forecast','Run the existing trained admission model using only the latest saved validated input history. No arguments or invented history. Returns an unsaved preview; missing history needs a forecast form submission. Cite [F1].'),
                tool('preview_capacity','Run a non-persisted monthly capacity simulation/optimisation using an existing saved forecast. Defaults: stay 20 hours, occupancy .85, staff-hours/admission 4, max beds 100, max staff hours 10000. State assumptions. No allocation or approval. Cite [C1].',
                     {'forecast_id':{'type':'string'}, 'average_length_of_stay_hours':{'type':'number','minimum':.1,'maximum':720},
                      'target_occupancy':{'type':'number','minimum':.5,'maximum':1},
                      'staff_hours_per_admission':{'type':'number','minimum':.1,'maximum':200},
                      'max_extra_beds':{'type':'integer','minimum':0,'maximum':1000},
                      'max_extra_staff_hours':{'type':'integer','minimum':0,'maximum':1000000}}, ['forecast_id'])]
        return definitions

    def call(self, name, args):
        allowed = {t['function']['name']: t['function']['parameters'] for t in self.definitions()}
        if name not in allowed:
            raise ValueError('Tool unavailable for this role or compute setting.')
        if not isinstance(args, dict) or set(args) - set(allowed[name]['properties']):
            raise ValueError('Invalid tool arguments; hospital scope cannot be overridden.')
        if not set(allowed[name]['required']).issubset(args):
            raise ValueError('Missing tool arguments.')
        db, hid = self.db, self.hospital_id
        if name == 'hospital_snapshot':
            return self.snapshot()
        if name == 'search_policies':
            query = args['query']
            if not isinstance(query,str) or not 1 <= len(query) <= 1000:
                raise ValueError('Search query must be 1–1000 characters.')
            citations = self.retriever.search(db, query)
            self.sources.update({c['id']:c for c in citations})
            return {'passages':citations,'note':'No matching evidence means do not invent policy requirements.'}
        if name == 'staffing_equipment_tasks':
            shifts = db.scalars(select(StaffShift).where(StaffShift.hospital_id == hid).order_by(StaffShift.shift_date.desc()).limit(20)).all()
            equipment = db.scalars(select(EquipmentStock).where(EquipmentStock.hospital_id == hid).limit(30)).all()
            tasks = db.scalars(select(OperationalTask).where(OperationalTask.hospital_id == hid).order_by(OperationalTask.id.desc()).limit(20)).all()
            self.sources['H2'] = {'id':'H2','kind':'hospital','title':'Recorded shifts, equipment and tasks','excerpt':'Latest saved records; bounded to 20 shifts/tasks and 30 equipment records.','source':'/operations/'+hid+'/board'}
            return {'shifts':[record(r,['shift_date','shift','team','required_staff','available_staff','hours_per_person','updated_at']) for r in shifts],
                    'equipment':[record(r,['name','location','total','available','updated_at']) for r in equipment],
                    'tasks':[record(r,['title','owner','status','priority','updated_at']) for r in tasks],
                    'note':'These are bounded records, not complete historical totals. Shift hours do not replace monthly staffing budgets.'}
        if name == 'saved_capacity_plans':
            plans = db.scalars(select(OptimisationPlan).where(OptimisationPlan.hospital_identifier == hid).order_by(OptimisationPlan.created_at.desc()).limit(3)).all()
            self.sources['H3'] = {'id':'H3','kind':'hospital','title':'Saved capacity plans','excerpt':'Latest three plans and recorded decision state.','source':'/operations/'+hid+'/board'}
            return [record(r,['id','status','input_data','recommendation','created_at']) for r in plans]
        if name == 'run_forecast':
            history = db.scalar(select(HospitalForecastHistory).where(HospitalForecastHistory.hospital_id == hid).order_by(HospitalForecastHistory.created_at.desc()))
            if history is None:
                return {'error':'No saved validated input history. Submit 13–120 completed months on Demand forecast first. Older saved predictions do not contain their input rows.'}
            hospital = db.get(Hospital,hid)
            payload = HospitalForecastRequest(hospital_identifier=hid,hospital_name=hospital.name,history=history.history)
            result = self.request.app.state.forecast_service.forecast_hospital(hid,hospital.name,[r.model_dump() for r in payload.history])
            self.sources['F1'] = {'id':'F1','kind':'forecast','title':'Trained-model forecast preview','excerpt':f"{result['predicted_emergency_admissions']} admissions for {result['target_month']}; saved input history {history.forecast_id}.",'source':'trained Random Forest pipeline'}
            return {k:result[k] for k in ['target_month','predicted_emergency_admissions','data','warnings']} | {'saved':False,'source_input_forecast_id':history.forecast_id,'citation_id':'F1','as_of_date':date.today().isoformat(),'historical_target':result['target_month'] < date.today().strftime('%Y-%m')}
        if name == 'preview_capacity':
            result = calculate_plan(hid,PlanningIn(**args),self.request,db,self.user,persist=False)
            self.sources['C1'] = {'id':'C1','kind':'scenario','title':'Capacity scenario preview','excerpt':'Existing simulator and optimiser; current recorded inventory; assumptions are included in tool result. No plan saved or approved.','source':'HealthFlow capacity service'}
            result['citation_id'] = 'C1'
            result['historical_target'] = result['input_data']['target_month'] < date.today().strftime('%Y-%m')
            result['as_of_date'] = date.today().isoformat()
            return result
        raise ValueError('Unknown tool.')
