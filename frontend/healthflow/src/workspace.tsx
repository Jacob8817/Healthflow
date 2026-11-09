import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from './api';

export type StaffUser = { id: number; full_name: string; email: string; role: string };
export type Hospital = { id: string; name: string; data_origin: string };
export type Ward = { id: number; name: string; floor: string; specialty: string };
export type BedState = 'available' | 'occupied' | 'reserved' | 'cleaning' | 'blocked';
export type Bed = { id: number; ward_id: number; label: string; status: BedState; staffed: boolean; capability: string; note: string; version: number; updated_at: string };
export type Forecast = { id: string; target_month: string; feature_month: string; displayed_prediction: number; created_at: string; warnings: string[] };
export type Resource = { id: number; month: string; available_staff_hours: number; equipment_available: number; notes: string; updated_at: string };
export type Task = { id: number; title: string; owner: string; priority: string; status: string; note: string; updated_at: string };
export type Emergency = { awaiting_assessment: number; awaiting_bed: number; high_priority: number; medium_priority: number; low_priority: number; updated_at: string };
export type Plan = { id: string; status: string; created_at: string; input_data: {target_month: string; demand: number; staffed_beds: number; average_length_of_stay_hours: number; target_occupancy: number; staff_hours_per_admission: number; available_staff_hours: number; horizon_days: number}; recommendation: { status: string; recommendation: {extra_beds?: number; extra_staff_hours?: number; estimated_incremental_cost?: number}; summary?: {required_beds_at_target: number; bed_gap: number; staff_hour_gap: number; offered_load_percent: number}; simulation?: {mean_occupancy: number; p95_wait_hours: number; waiting_at_end: number; capacity_risk: string} } };
export type Shift = {id:number;shift_date:string;shift:string;team:string;required_staff:number;available_staff:number;hours_per_person:number};
export type Equipment = {id:number;name:string;location:string;total:number;available:number};
export type Board = { shifts: Shift[]; equipment: Equipment[]; hospital: Hospital; wards: Ward[]; beds: Bed[]; counts: Record<string, number>; emergency: Emergency | null; resources: Resource[]; forecasts: Forecast[]; tasks: Task[]; plans: Plan[] };
type WorkspaceValue = { user: StaffUser; hospitals: Hospital[]; hospitalId: string; selectHospital: (id: string) => void; board: Board | null; loading: boolean; error: string; refresh: () => void; reloadHospitals: (selected?: string) => Promise<void>; canWrite: boolean };
const Context = createContext<WorkspaceValue | null>(null);
export const useWorkspace = () => { const v = useContext(Context); if (!v) throw new Error('Workspace is required'); return v; };
export const formatNumber = (n: number) => new Intl.NumberFormat('en-GB', {maximumFractionDigits: 1}).format(n);
export const displayMonth = (s: string) => new Date(`${s}-01T12:00:00`).toLocaleDateString('en-GB', {month:'long', year:'numeric'});
export const displayTime = (s?: string) => s ? new Date(s.endsWith('Z') || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`).toLocaleString('en-GB', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : 'Not recorded';
export function errorText(error: unknown) {
  const detail = (error as {response?: {data?: {detail?: unknown}}})?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(x => x.msg).join('; ');
  return 'Could not complete the request. Check the connection and try again.';
}
export function WorkspaceProvider({ user, children }: { user: StaffUser; children: ReactNode }) {
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [hospitalId, setHospitalId] = useState('');
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const selectHospital = (id: string) => { setBoard(null); setHospitalId(id); localStorage.setItem('healthflow_hospital', id); };
  const reloadHospitals = async (selected?: string) => {
    try {
      const rows = (await api.get<Hospital[]>('/operations/hospitals')).data;
      setHospitals(rows);
      const preferred = selected || localStorage.getItem('healthflow_hospital');
      const id = rows.find(h => h.id === preferred)?.id || rows[0]?.id || '';
      setHospitalId(id); setError('');
      if (!id) setLoading(false);
    } catch(e) { setError(errorText(e)); setLoading(false); }
  };
  useEffect(() => { void reloadHospitals(); }, []);
  useEffect(() => {
    if (!hospitalId) return;
    let cancelled = false;
    setLoading(true); setError('');
    api.get<Board>(`/operations/${hospitalId}/board`).then(r => { if (!cancelled) setBoard(r.data); })
      .catch(e => { if (!cancelled) setError(errorText(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [hospitalId, revision]);
  return <Context.Provider value={{user, hospitals, hospitalId, selectHospital, board, loading, error,
    refresh: () => setRevision(n => n + 1), reloadHospitals, canWrite: ['admin','planner'].includes(user.role)}}>{children}</Context.Provider>;
}
