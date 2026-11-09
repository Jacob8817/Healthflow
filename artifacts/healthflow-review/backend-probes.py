"""Read-only reproductions of validation defects; no database writes."""
import json
from pathlib import Path
from pydantic import ValidationError
from app.db.models import PolicyDocument
from app.schemas import HospitalForecastRequest, IntelligenceRequest, CapacityIn
from app.services.intelligence import OperationsIntelligenceService

output = Path(__file__).resolve().parent
payload = json.loads((output / 'prediction-input.json').read_text())
results = []
for i, row in enumerate(payload['history']):
    row['month'] = f'{2090 + i // 12}-{i % 12 + 1:02d}'
HospitalForecastRequest.model_validate(payload)
results.append({'finding': 'Future months accepted as completed history', 'reproduced': True, 'last_month': payload['history'][-1]['month']})

try:
    IntelligenceRequest(message='Follow-up', conversation_id='e6e8978b-4402-44b5-a169-956cacb23ccc')
except ValidationError:
    results.append({'finding': 'Returned UUID conversation ID rejected by follow-up request schema', 'reproduced': True})

policies = [PolicyDocument(id=i, title='Capacity policy', text_content='Capacity planning') for i in (1, 2)]
try:
    OperationsIntelligenceService.policy_context('Capacity planning', policies)
except TypeError as exc:
    results.append({'finding': 'Equal policy relevance scores cause sort TypeError', 'reproduced': True, 'error': str(exc)})

CapacityIn(hospital_identifier='DEMO-HOSP-01', snapshot_month='2026-07-01', staffed_beds=100, occupied_beds=150,
           available_staff_hours=3000, required_staff_hours=3200, equipment_available=10)
results.append({'finding': 'Occupied beds can exceed staffed beds without validation', 'reproduced': True})
(output / 'backend-probes.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))
