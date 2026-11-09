import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from './api';
import { Heading, Notice } from './staff';
import { useWorkspace, errorText, displayTime } from './workspace';

type Citation = {id:string;title:string;kind:string;page?:number|null;excerpt:string;source?:string;updated_at?:string};
type Answer = {answer:string;status:string;conversation_id:string;citations:Citation[];tools:{name:string;status:string;result?:{target_month?:string;predicted_emergency_admissions?:number;historical_target?:boolean;input_data?:{target_month:string};recommendation?:{recommendation?:{extra_beds:number;extra_staff_hours:number;estimated_incremental_cost:number}}}}[];warnings:string[]};
type Turn = {role:'user'|'assistant';content:string;result?:Answer};
type Service = {available:boolean;provider:string;reason?:string;model:string};

function AnswerText({text}:{text:string}){return <div className="chat-text">{text.split('\n').map((line,i)=><div key={i}>{line.split(/(\*\*[^*]+\*\*)/g).map((part,j)=>part.startsWith('**')&&part.endsWith('**')?<strong key={j}>{part.slice(2,-2)}</strong>:<span key={j}>{part||'\u00a0'}</span>)}</div>)}</div>;}

export function Intelligence(){
 const {hospitalId,board,canWrite,user}=useWorkspace();
 const [message,setMessage]=useState(''),[turns,setTurns]=useState<Turn[]>([]),[conversation,setConversation]=useState<string|undefined>();
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState<Service|null>(null),[compute,setCompute]=useState(false);
 const scope=useRef(hospitalId); scope.current=hospitalId;
 const key=`healthflow_chat_${user.id}_${hospitalId}`;
 useEffect(()=>{let active=true;setTurns([]);setConversation(undefined);setCompute(false);setError('');
   const saved=localStorage.getItem(key);
   if(saved) api.get(`/operations-intelligence/conversations/${saved}`,{params:{hospital_id:hospitalId}}).then(r=>{
     if(active){setConversation(saved);setTurns(r.data.map((m:{role:'user'|'assistant';content:string;structured_response?:Answer})=>({role:m.role,content:m.content,result:m.structured_response})));}
   }).catch(()=>{localStorage.removeItem(key);});
   api.get('/operations-intelligence/status').then(r=>{if(active)setStatus(r.data);}).catch(()=>{if(active)setStatus(null);});
   return()=>{active=false;};
 },[hospitalId,key]);
 const ask=async(e:FormEvent)=>{e.preventDefault();if(!message.trim()||busy)return;const asked=message, hospital=hospitalId;setBusy(true);setError('');setMessage('');setTurns(t=>[...t,{role:'user',content:asked}]);
   try{const r=await api.post<Answer>('/operations-intelligence',{message:asked,hospital_id:hospital,conversation_id:conversation,allow_compute:compute});
     if(scope.current===hospital){setConversation(r.data.conversation_id);localStorage.setItem(key,r.data.conversation_id);setTurns(t=>[...t,{role:'assistant',content:r.data.answer,result:r.data}]);}
   }catch(e){if(scope.current===hospital){setError(errorText(e));setMessage(asked);}}finally{setBusy(false);}
 };
 const reset=()=>{localStorage.removeItem(key);setConversation(undefined);setTurns([]);setError('');};
 return <main><Heading eyebrow="Operational support" title="Operations assistant" text="Ask about recorded hospital capacity, saved forecasts and indexed policies. Answers include sources and reporting periods."/>
 <div className="record-strip"><span className="pill">{board?.hospital.name}</span><span>{status?.available?'AI Service available':status?.reason==='missing_key'?'Backend API key needed':status?.reason==='invalid_key'?'API key rejected':status?'AI service unavailable':'Checking AI service…'}</span><button className="secondary" onClick={reset} disabled={busy}>New conversation</button></div>
 <div className="assistant-layout"><section className="panel assistant-chat" aria-live="polite">
 {!turns.length&&<div className="empty"><h2>How can I help with operations?</h2><p>Ask about available beds, capacity gaps, forecasts, staffing or policy guidance.</p><div className="suggestion-list">{['Summarise our recorded beds and emergency queue.','What is our latest saved forecast and its reporting month?','Which policies discuss admission surges?'].map(q=><button className="secondary" key={q} onClick={()=>setMessage(q)}>{q}</button>)}</div></div>}
 {turns.map((t,i)=><article key={i} className={`chat-turn ${t.role}`}><strong>{t.role==='user'?'You':'HealthFlow'}</strong><AnswerText text={t.content}/>{t.result&&<>
 {t.result.status!=='ok'&&<span className="pill">{t.result.status.replaceAll('_',' ')}</span>}
 {t.result.warnings?.map(w=><p className="warning" key={w}>{w}</p>)}
 {!!t.result.tools?.length&&<details open><summary>Tools used ({t.result.tools.length})</summary>{t.result.tools.map((tool,j)=><div key={j} className="fine"><p>{tool.name.replaceAll('_',' ')} · {tool.status}</p>{tool.result&&<div className="source-card"><b>Verified tool result · {tool.result.target_month||tool.result.input_data?.target_month}</b>{tool.result.predicted_emergency_admissions!=null&&<p>{tool.result.predicted_emergency_admissions.toLocaleString()} predicted admissions</p>}{tool.result.recommendation?.recommendation&&<p>{tool.result.recommendation.recommendation.extra_beds} additional beds · {tool.result.recommendation.recommendation.extra_staff_hours} additional staff-hours</p>}<small>{tool.result.historical_target?'Retrospective scenario':'Forecast/scenario preview'} · Not saved or applied</small></div>}</div>)}</details>}
 {!!t.result.citations?.length&&<details className="source-list"><summary>Retrieved evidence ({t.result.citations.length})</summary>{t.result.citations.map(c=><div className="source-card" key={c.id}><b>[{c.id}] {c.title}</b><small>{c.kind}{c.page?` · page ${c.page}`:''}{c.updated_at?` · ${displayTime(c.updated_at)}`:''}</small><p>{c.excerpt}</p>{c.source&&<small>Source: {c.source}</small>}</div>)}</details>}
 </>}</article>)}
 {busy&&<p className="loading">Checking records and preparing an evidence-based answer…</p>}
 <form onSubmit={ask} className="chat-compose"><Notice error={error}/><label htmlFor="assistant-question">Your question</label><textarea id="assistant-question" rows={3} required maxLength={8000} value={message} onChange={e=>setMessage(e.target.value)} placeholder="Ask about this hospital…" disabled={busy}/>
 <div className="section-bar">{canWrite&&<label className="compute-toggle"><input type="checkbox" checked={compute} onChange={e=>setCompute(e.target.checked)} disabled={busy}/> Enable forecast and scenario previews for this message</label>}<button disabled={busy||!message.trim()||!hospitalId}>{busy?'Working…':'Send question'}</button></div></form>
</section></div></main>;
}

export function Policies(){
 const {canWrite}=useWorkspace();const [rows,setRows]=useState<{id:number;title:string;source:string;text_content:string}[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[index,setIndex]=useState<{documents:number;chunks:number}|null>(null);
 const load=async()=>{const [r,s]=await Promise.all([api.get('/policies'),api.get('/policies/index/status')]);setRows(r.data);setIndex(s.data);};
 useEffect(()=>{void load().catch(e=>setError(errorText(e)));},[]);
 const save=async(e:FormEvent<HTMLFormElement>,upload:boolean)=>{e.preventDefault();const form=e.currentTarget,d=new FormData(form);setBusy(true);setError('');setNotice('');try{
 if(upload){await api.post('/policies/upload',d);}else{await api.post('/policies',{title:d.get('title'),content:d.get('content'),source:d.get('source')});}
 form.reset();await load();setNotice('Document saved and indexed for retrieval.');}catch(e){setError(errorText(e));}finally{setBusy(false);}};
 return <main><Heading eyebrow="Team reference" title="Policy library" text="Upload operational references for local semantic search and source-linked answers."/><Notice error={error}/>{notice&&<p className="pill">{notice}</p>}<div className="record-strip">{index&&<span>{index.documents} documents · {index.chunks} indexed passages</span>}<span>Shared across this installation</span></div>
 <div className="grid two"><section className="panel"><h2>Saved documents</h2>{rows.map(r=><details className="policy" key={r.id}><summary>{r.title}</summary><small>{r.source}</small><p className="chat-text">{r.text_content}</p></details>)}{!rows.length&&<div className="empty">No policies added yet. Upload a reference or paste its text.</div>}</section>{canWrite&&<div><form className="panel" onSubmit={e=>save(e,true)}><h2>Upload a document</h2><label>Title<input name="title" required minLength={2} maxLength={300}/></label><label>Source or reference<input name="source" maxLength={500}/></label><label>PDF, TXT or Markdown<input type="file" name="file" accept=".pdf,.txt,.md" required/></label><p className="fine">Up to 10 MB, 200 PDF pages or 200,000 extracted characters. Scanned PDFs need OCR first. PDF citations retain page numbers. Upload public/sample policies for this prototype; relevant excerpts are sent to Groq.</p><button disabled={busy}>{busy?'Indexing…':'Upload and index'}</button></form>
 <form className="panel" onSubmit={e=>save(e,false)}><h2>Paste policy text</h2><label>Title<input name="title" required minLength={2} maxLength={300}/></label><label>Source or reference<input name="source" maxLength={500}/></label><label>Policy text<textarea name="content" rows={8} required minLength={10} maxLength={200000}/></label><button disabled={busy}>{busy?'Indexing…':'Save and index'}</button></form></div>}</div></main>;
}
