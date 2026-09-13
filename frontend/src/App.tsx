import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Check, CircleAlert, FileText, Gauge, Link2, LoaderCircle, Pencil, Plus, RefreshCw, RotateCcw, Sparkles, Trash2, X } from 'lucide-react';
import { api, API_REVISION, ApiError, errorMessage } from './api';
import type { Candidate, Health, ImportSlot, Preferences, Report } from './types';
import { cacheImport, cachedImport, clearDraft, loadDraft, saveDraft } from './storage';
import { dateLabel, defaultPreferences, editCandidate, freshSlot, importBody, mileage, money, readableField, restoreSlot, safeUrl, sourceLabel } from './utils';

const fields: (keyof Candidate)[] = ['year', 'make', 'model', 'trim', 'generation', 'price', 'mileage', 'transmission', 'location', 'history'];

export default function App() {
  // Restore the browser-local draft so imported cars survive reloads and step changes.
  const [draft] = useState(loadDraft);
  const [slots, setSlots] = useState<ImportSlot[]>(() => draft?.slots.map(restoreSlot) ?? [freshSlot()]);
  const [preferences, setPreferences] = useState<Preferences>(() => ({ ...defaultPreferences, ...draft?.preferences }));
  const [loadingSlot, setLoadingSlot] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [step, setStep] = useState<'import'|'review'|'report'>('import');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [health, setHealth] = useState<Health | null>(null);
  const candidates = useMemo(() => slots.map(s => s.candidate).filter((c): c is Candidate => Boolean(c)), [slots]);

  useEffect(() => { api.health().then(setHealth).catch(() => undefined); }, []);
  useEffect(() => saveDraft({ slots, preferences }), [slots, preferences]);

  const updateSlot = (id: string, update: Partial<ImportSlot>) => {
    setReport(null);
    setSlots(current => current.map(s => s.id === id ? { ...s, ...update } : s));
  };
  // Importing stays on this step: the result is shown in the car's card, and the user moves on when ready.
  const importSlot = async (slot: ImportSlot, refresh = false) => {
    const body = importBody(slot);
    const cached = refresh ? null : cachedImport(body);
    if (cached) {
      const { result } = cached;
      // A fresh id keeps candidates unique if the same listing is cached into two cards.
      updateSlot(slot.id, { candidate: result.candidate && { ...result.candidate, id: crypto.randomUUID() }, status: result.status,
                            message: result.message, attempts: result.attempts, recovery_status: result.recovery_status, cachedAt: cached.at, editing: false });
      return;
    }
    setBusy(true); setLoadingSlot(slot.id); setNotice('');
    try {
      const result = await api.import(body);
      cacheImport(body, result);
      updateSlot(slot.id, { candidate: result.candidate, status: result.status, message: result.message, attempts: result.attempts,
                            recovery_status: result.recovery_status, cachedAt: undefined, editing: false });
    } catch (error) {
      updateSlot(slot.id, { candidate: null, status: 'failed', message: errorMessage(error), attempts: error instanceof ApiError ? error.result.attempts : [],
                            recovery_status: error instanceof ApiError ? error.result.recovery_status : null, cachedAt: undefined, editing: false });
    } finally { setBusy(false); setLoadingSlot(null); }
  };
  const addSlot = () => setSlots(current => current.length < 3 ? [...current, freshSlot()] : current);
  const removeSlot = (keep: (slot: ImportSlot) => boolean) => {
    setSlots(current => { const next = current.filter(keep); return next.length ? next : [freshSlot()]; });
    setReport(null);
  };
  const updateCandidate = (id: string, field: keyof Candidate, raw: string) => {
    setSlots(current => current.map(s => {
      if (s.candidate?.id !== id) return s;
      const numeric = field === 'year' || field === 'price' || field === 'mileage';
      return { ...s, candidate: editCandidate(s.candidate, field, numeric ? (raw ? Number(raw) : null) : raw || null) };
    }));
    setReport(null);
  };
  const generateReport = async () => {
    if (candidates.length < 2) { setNotice('Import at least two candidates before generating a report.'); return; }
    setBusy(true); setNotice('');
    try { setReport(await api.compare(candidates, preferences)); setStep('report'); }
    catch (error) { setNotice(errorMessage(error)); } finally { setBusy(false); }
  };
  const loadDemo = async () => { setReport(null); setBusy(true); try { const data = await api.demo(); setSlots(data.candidates.slice(0, 3).map(candidate => ({ ...freshSlot(), candidate, status: 'success', message: 'Loaded synthetic example' }))); setStep('import'); setNotice('Synthetic examples loaded. These are not live market observations.'); } catch (error) { setNotice(errorMessage(error)); } finally { setBusy(false); } };
  const reset = () => { if (busy) return; clearDraft(); setSlots([freshSlot()]); setPreferences(defaultPreferences); setReport(null); setStep('import'); setNotice(''); };

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" onClick={e => { e.preventDefault(); reset(); }}><span className="brand-mark">R</span><span>RevRank</span></a><span className="top-note">Vehicle comparison workspace</span><button className="text-button" onClick={reset}><RotateCcw size={15}/> New comparison</button></header>
    <main><fieldset className="workspace-controls" disabled={busy}>
      <section className="intro"><div><p className="eyebrow">COMPARE THE CARS, NOT THE HYPE</p><h1>Make the next car decision with evidence.</h1><p className="lede">Bring in the listings you’re considering. RevRank extracts the details, checks the tradeoffs, and builds a report around what matters to you.</p></div><div className="status-card"><span className="status-dot"/>Local workspace<br/><small>Your draft stays in this browser.</small></div></section>
      <nav className="steps" aria-label="Comparison steps">{[['import','01','Import listings'],['review','02','Review details'],['report','03','Read report']].map(([key,num,label], i) => <button key={key} className={step === key ? 'step active' : 'step'} onClick={() => (key === 'review' && candidates.length === 0) ? setNotice('Import a listing first.') : setStep(key as typeof step)}><span>{num}</span>{label}{i < 2 && <ArrowRight size={15}/>}</button>)}</nav>
      {health && health.api_revision !== API_REVISION && <div className="notice" role="alert"><CircleAlert size={17}/><span>The running RevRank backend is older than this page (API revision {health.api_revision ?? 1}, expected {API_REVISION}). Its results may be wrong, for example rejecting enabled websites. Stop scripts/dev.py with Ctrl+C and start it again.</span></div>}
      {health?.search_enabled === false && !health.licensed_inventory_enabled && <div className="notice" role="status"><CircleAlert size={17}/><span>{!health.search_provider?.trim() || health.search_provider === 'none' ? 'Search recovery is unavailable: no search provider is configured.' : `Search recovery is unavailable (provider setting: ${health.search_provider}).`} For local setup, set REVRANK_SEARCH_PROVIDER to brave or tavily and REVRANK_SEARCH_API_KEY (or a licensed REVRANK_MARKETCHECK_API_KEY) in the backend’s local .env, then restart the backend and reload this page. Keep the key server-side. Paste listing text to continue without search.</span></div>}
      {notice && <div className="notice"><CircleAlert size={17}/><span>{notice}</span></div>}
      {step === 'import' && <section className="workspace"><div className="panel main-panel"><div className="panel-heading"><div><p className="eyebrow">START HERE</p><h2>Import the cars you’re considering</h2></div><button className="secondary-button" onClick={loadDemo} disabled={busy}><Sparkles size={16}/> Use examples</button></div><p className="muted">Paste a listing URL from a supported source, or paste the listing text when a website blocks automated access.</p><div className="import-grid">{slots.map((slot, index) => <ImportCard key={slot.id} slot={slot} index={index} busy={busy} loading={loadingSlot === slot.id} canRemove={slots.length > 1 || Boolean(slot.candidate || slot.url || slot.text || slot.vin)} onChange={update => updateSlot(slot.id, update)} onImport={refresh => importSlot(slot, refresh)} onRemove={() => removeSlot(s => s.id !== slot.id)} />)}{slots.length < 3 && <button className="add-card" onClick={addSlot}><Plus size={18}/><strong>Add a {slots.length === 1 ? 'second' : 'third'} car</strong><span>Compare up to three listings</span></button>}</div><div className="import-footer"><p className="muted">{candidates.length} of {slots.length} {slots.length === 1 ? 'car' : 'cars'} imported{candidates.length < 2 ? ' · import at least two to generate a report' : ''}</p><button className="primary-button" disabled={!candidates.length} onClick={() => setStep('review')}>Review details <ArrowRight size={16}/></button></div></div><aside className="panel side-panel"><Gauge size={21} className="amber"/><h3>What happens next</h3><ol><li>We identify the exact model, generation, mileage, and price.</li><li>You confirm anything missing or unclear.</li><li>Your priorities shape the final comparison.</li></ol><div className="side-callout"><strong>Built for uncertainty</strong><p>Seller claims and unknown history remain labeled in your report.</p></div></aside></section>}
      {step === 'review' && <div className="review-imports">{slots.filter(s => s.message || s.attempts?.length || s.recovery_status).map((slot) => <div className="panel" key={slot.id}><strong>{slot.candidate?.title || slot.url || 'Import result'}</strong><p>{slot.message}</p><RecoveryAttempts slot={slot}/></div>)}<button className="secondary-button" onClick={() => setStep('import')}>Import or retry listings</button></div>}
      {step === 'review' && <Review candidates={candidates} preferences={preferences} setPreferences={value => { setPreferences(value); setReport(null); }} updateCandidate={updateCandidate} removeCandidate={(id) => removeSlot(s => s.candidate?.id !== id)} generateReport={generateReport} busy={busy} />}
      {step === 'report' && !report && <div className="panel main-panel"><h2>Generate an updated report</h2><p>Your inputs have changed or no report has been generated yet.</p><button className="primary-button" onClick={() => setStep(candidates.length ? 'review' : 'import')}>Return to {candidates.length ? 'review' : 'import'}</button></div>}
      {step === 'report' && report && <ReportView report={report} onBack={() => setStep('review')} onReset={reset} />}
    </fieldset></main>
    <footer><span>RevRank v0.1 · Evidence before certainty</span><span><FileText size={14}/> Reports are informational estimates</span></footer>
  </div>;
}

const ORDINALS = ['First', 'Second', 'Third'];
const METHOD_LABELS: Record<string, string> = {
  direct: 'Fetched from listing', search: 'Recovered via search', licensed: 'Licensed inventory',
  registry: 'VIN decode only', paste: 'From pasted text', synthetic: 'Synthetic example',
};

interface ImportCardProps {
  slot: ImportSlot; index: number; busy: boolean; loading: boolean; canRemove: boolean;
  onChange: (update: Partial<ImportSlot>) => void; onImport: (refresh: boolean) => void; onRemove: () => void;
}

function ImportCard({ slot, index, busy, loading, canRemove, onChange, onImport, onRemove }: ImportCardProps) {
  const candidate = slot.candidate;
  const showForm = !candidate || slot.editing;
  const ready = slot.status === 'success';
  return <div className={showForm ? 'import-card' : 'import-card has-vehicle'}>
    <div className="card-top">
      <span className="card-number">0{index + 1}</span><strong>{ORDINALS[index]} car</strong>
      <span className="card-actions">
        {candidate && <span className={ready ? 'pill success' : 'pill review'}>{ready ? <><Check size={12}/> Ready</> : 'Needs review'}</span>}
        {canRemove && <button className="icon-button" title="Remove this car" aria-label={`Remove ${ORDINALS[index].toLowerCase()} car`} onClick={onRemove}><X size={15}/></button>}
      </span>
    </div>
    {showForm ? <>
      <label>Listing URL <span>optional</span><input value={slot.url} onChange={e => onChange({ url: e.target.value })} placeholder="https://…" /></label>
      <label>VIN <span>optional</span><input value={slot.vin} onChange={e => onChange({ vin: e.target.value })} placeholder="Vehicle identification number" /></label>
      <label className="recovery-toggle"><input type="checkbox" checked={slot.recover} onChange={e => onChange({ recover: e.target.checked })}/> Try search recovery if needed</label>
      <label>Or paste listing text <span>fallback</span><textarea value={slot.text} onChange={e => onChange({ text: e.target.value })} placeholder="Vehicle name, price, mileage, options…" rows={4}/></label>
      <div className="form-actions">
        <button className="primary-button full" onClick={() => onImport(false)} disabled={busy || (!slot.url.trim() && !slot.text.trim())}>
          {loading ? <LoaderCircle className="spin" size={16}/> : <Link2 size={16}/>} {loading ? 'Importing…' : candidate ? 'Import replacement' : 'Import car'}
        </button>
        {candidate && <button className="secondary-button full" onClick={() => onChange({ editing: false })}>Cancel</button>}
      </div>
      {!candidate && slot.message && <p className="import-error"><CircleAlert size={15}/><span>{slot.message}</span></p>}
    </> : <VehicleSummary slot={slot} busy={busy} loading={loading} onEdit={() => onChange({ editing: true })} onRefresh={() => onImport(true)} />}
    {(slot.message || !!slot.attempts?.length) && <details className="import-log">
      <summary>Import details</summary>
      {candidate && slot.message && <p>{slot.message}</p>}
      <RecoveryAttempts slot={slot}/>
    </details>}
  </div>;
}

function VehicleSummary({ slot, busy, loading, onEdit, onRefresh }: { slot: ImportSlot; busy: boolean; loading: boolean; onEdit: () => void; onRefresh: () => void }) {
  const car = slot.candidate as Candidate;
  const unresolved = (car.conflicts ?? []).filter(field => !car.verified_fields.includes(field));
  const unknown = (field: 'price' | 'mileage') => unresolved.includes(field) ? 'Sources disagree' : 'Unknown';
  // A bare "$" does not establish the currency, so an unconfirmed price is shown without one.
  const price = car.price === null ? null : car.currency === 'UNK' ? car.price.toLocaleString() : money(car.price, car.currency);
  const missing = (['year', 'make', 'model', 'price', 'mileage'] as const).filter(field => car[field] === null && !unresolved.includes(field));
  const review = [...unresolved.map(field => `${readableField(field).toLowerCase()} (sources disagree)`),
                  ...missing.map(field => readableField(field).toLowerCase()),
                  ...(car.price !== null && car.currency === 'UNK' ? ['currency'] : [])];
  const vin = car.evidence.vin?.value;
  const link = safeUrl(car.source_url);
  const name = [car.year, car.make, car.model].filter(Boolean).join(' ') || car.title;
  return <div className="vehicle-summary">
    <p className="vehicle-kicker">{link ? <a href={link} target="_blank" rel="noopener noreferrer">{sourceLabel(car)}</a> : sourceLabel(car)}</p>
    <h3>{name}</h3>
    {car.trim && <p className="vehicle-trim">{car.trim}</p>}
    <dl className="vehicle-stats">
      <div><dt>Price</dt><dd className={price ? '' : 'muted-value'}>{price ?? unknown('price')}{price && car.currency === 'UNK' && <small>currency unconfirmed</small>}</dd></div>
      <div><dt>Mileage</dt><dd className={car.mileage === null ? 'muted-value' : ''}>{car.mileage === null ? unknown('mileage') : mileage(car)}</dd></div>
      <div><dt>Location</dt><dd className={car.location ? '' : 'muted-value'}>{car.location ?? (unresolved.includes('location') ? 'Sources disagree' : 'Unknown')}</dd></div>
    </dl>
    <div className="vehicle-tags">
      <span className="tag">{METHOD_LABELS[car.retrieval_method ?? 'direct'] ?? readableField(car.retrieval_method ?? 'direct')}</span>
      <span className="tag">{vin ? `VIN ${vin}` : 'VIN unknown'}</span>
      {slot.cachedAt && <span className="tag" title="Reused a result saved in this browser; Refresh requests it again.">Saved {dateLabel(new Date(slot.cachedAt).toISOString())}</span>}
    </div>
    {review.length ? <p className="vehicle-review"><CircleAlert size={15}/><span>Check before comparing: {review.join(', ')}.</span></p>
                   : <p className="vehicle-ok"><Check size={15}/><span>Key details found. Confirm them on the review step.</span></p>}
    <div className="vehicle-actions">
      <button className="secondary-button" onClick={onEdit} disabled={busy}><Pencil size={14}/> Change listing</button>
      {(slot.url.trim() || slot.text.trim()) && <button className="secondary-button" onClick={onRefresh} disabled={busy}>
        {loading ? <LoaderCircle className="spin" size={14}/> : <RefreshCw size={14}/>} {loading ? 'Refreshing…' : 'Refresh'}
      </button>}
    </div>
  </div>;
}

function RecoveryAttempts({ slot }: { slot: ImportSlot }) {
  if (!slot.recovery_status && !slot.attempts?.length) return null;
  return <div className="recovery-details" aria-live="polite">
    <strong>Import attempts</strong>
    {slot.recovery_status && <p>Recovery status: {readableField(slot.recovery_status)}</p>}
    <ol>{slot.attempts?.map((attempt, index) => <li key={index}><strong>{readableField(attempt.method)} · {attempt.status}</strong><p>{attempt.detail}</p></li>)}</ol>
  </div>;
}

function CandidateEvidence({ candidate }: { candidate: Candidate }) {
  const unresolved = (candidate.conflicts ?? []).filter(field => !candidate.verified_fields.includes(field));
  return <div className="candidate-evidence">
    <p>Retrieval: {readableField(candidate.retrieval_method ?? 'direct')}</p>
    {!!candidate.conflicts?.length && <div className={unresolved.length ? 'conflict-details' : 'conflict-audit'}><strong>{unresolved.length ? `${unresolved.length} unresolved source conflict(s)` : 'Source conflicts reviewed'}</strong><p>Conflict audit — user corrections do not independently verify sources. Withheld price or mileage must also be entered after resolving its currency or unit.</p><ul>{candidate.conflicts.map((field, index) => <li key={index}>{readableField(field)} — {candidate.verified_fields.includes(field) ? 'Resolved by user input' : 'Unresolved'}</li>)}</ul></div>}
    {!!candidate.observations?.length && <div><strong>Source observations</strong><p>Search, licensed-inventory, and seller observations are source claims, not independently verified facts. Registry observations come from the NHTSA VIN decoder.</p><ul className="observation-list">{candidate.observations.map((observation, index) => {
      const url = safeUrl(observation.source_url);
      return <li key={index}><strong>{readableField(observation.field)}: {observation.value}</strong><div>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{observation.source_url}</a> : <span>Source link unavailable: {observation.source_url || 'not supplied'}</span>}</div><small>Observed: {observation.observed_at ? dateLabel(observation.observed_at) : 'Unknown'} · Retrieved: {dateLabel(observation.retrieved_at)} · Method: {observation.method} · VIN: {observation.vin || 'Unknown'}</small></li>;
    })}</ul></div>}
    {!!candidate.verified_fields.length && <p>User-reviewed fields: {candidate.verified_fields.map(readableField).join(', ')}</p>}
  </div>;
}

function Review({ candidates, preferences, setPreferences, updateCandidate, removeCandidate, generateReport, busy }: { candidates: Candidate[]; preferences: Preferences; setPreferences: (p: Preferences) => void; updateCandidate: (id: string, field: keyof Candidate, value: string) => void; removeCandidate: (id: string) => void; generateReport: () => void; busy: boolean }) {
  return <section className="workspace review-layout"><div className="panel main-panel"><div className="panel-heading"><div><p className="eyebrow">CHECK THE INPUTS</p><h2>Review each candidate</h2></div><span className="count-badge">{candidates.length} of 3</span></div><p className="muted">Make corrections before analysis. A user correction confirms your input; it does not independently verify a seller’s claim.</p><div className="candidate-list">{candidates.map((candidate, i) => <article className="candidate-card" key={candidate.id}><div className="candidate-head"><div><span className="candidate-index">0{i+1}</span><h3>{candidate.make || 'Unknown make'} {candidate.model || 'vehicle'}</h3><p>{sourceLabel(candidate)} · {candidate.source_kind === 'synthetic' ? 'synthetic example' : 'imported listing'}</p></div><button className="icon-button" title="Remove candidate" onClick={() => removeCandidate(candidate.id)}><Trash2 size={16}/></button></div><div className="field-grid">{fields.map(field => <label key={field}>{readableField(field)}<input value={Array.isArray(candidate[field]) ? candidate[field].join(', ') : (candidate[field] ?? '') as string|number} onChange={e => updateCandidate(candidate.id, field, e.target.value)} /></label>)}<label>Currency<select required value={candidate.currency === 'UNK' || (candidate.conflicts?.includes('currency') && !candidate.verified_fields.includes('currency')) ? '' : candidate.currency} onChange={e => updateCandidate(candidate.id, 'currency', e.target.value)}><option value="" disabled>Select currency</option>{[...new Set([candidate.currency, 'USD', 'CAD', 'EUR', 'GBP', 'AUD', 'JPY'])].filter(currency => currency && currency !== 'UNK').map(currency => <option key={currency} value={currency}>{currency}</option>)}</select></label><label>Mileage unit<select required value={candidate.conflicts?.includes('mileage_unit') && !candidate.verified_fields.includes('mileage_unit') ? '' : candidate.mileage_unit} onChange={e => updateCandidate(candidate.id, 'mileage_unit', e.target.value)}><option value="" disabled>Select unit</option><option value="mi">Miles (mi)</option><option value="km">Kilometres (km)</option></select></label></div><CandidateEvidence candidate={candidate}/><div className="feature-line"><strong>Features</strong><span>{candidate.features.length ? candidate.features.join(' · ') : 'Unknown'}</span></div>{candidate.warnings.length > 0 && <div className="warning-line"><CircleAlert size={15}/>{candidate.warnings.filter(warning => !candidate.verified_fields.some(field => warning.startsWith(`Conflicting ${field}:`))).join(' ')}</div>}</article>)}</div><div className="preferences"><div className="section-title"><span className="eyebrow">YOUR CONTEXT</span><h3>What should matter most?</h3></div><div className="pref-grid"><label>Budget<input type="number" placeholder="No limit" value={preferences.budget ?? ''} onChange={e => setPreferences({...preferences, budget: e.target.value ? Number(e.target.value) : null})}/></label><label>Annual mileage<input type="number" value={preferences.annual_mileage} onChange={e => setPreferences({...preferences, annual_mileage: Number(e.target.value)})}/></label><label>Location<input value={preferences.location} placeholder="City or ZIP" onChange={e => setPreferences({...preferences, location: e.target.value})}/></label></div><label>Priorities<input value={preferences.priorities.join(', ')} placeholder="Price, performance, practicality" onChange={e => setPreferences({...preferences, priorities: e.target.value.split(',').map(x => x.trim()).filter(Boolean)})}/></label></div><button className="primary-button report-button" onClick={generateReport} disabled={busy || candidates.length < 2 || candidates.some(c => !c.currency || !['mi', 'km'].includes(c.mileage_unit))}>{busy ? <><LoaderCircle className="spin" size={17}/> Building report…</> : <>Generate comparison report <ArrowRight size={17}/></>}</button></div></section>;
}

function ReportView({ report, onBack, onReset }: { report: Report; onBack: () => void; onReset: () => void }) {
  return <section className="report-wrap"><div className="report-toolbar"><button className="secondary-button" onClick={onBack}>← Edit candidates</button><button className="secondary-button" onClick={() => window.print()}>Print report</button><button className="primary-button" onClick={onReset}>New comparison</button></div><article className="report"><div className="report-head"><div><p className="eyebrow">REV RANK REPORT · {new Date(report.created_at).toLocaleDateString()}</p><h2>{report.title}</h2><p className="report-summary">{report.summary}</p></div><span className="mode-pill">{report.analysis_mode === 'llm' ? 'AI assisted' : 'Rules-based'} analysis</span></div><div className="report-stats">{report.metrics.map(metric => <div key={metric.label}><span>{metric.label}</span><strong>{metric.values.join(' · ')}</strong></div>)}</div><div className="report-section"><h3>What stands out</h3>{report.findings.map(f => <div className="finding" key={f.title}><strong>{f.title}</strong><p>{f.detail}</p>{f.evidence_fields.length > 0 && <small>Based on: {f.evidence_fields.join(', ')}</small>}</div>)}</div><div className="report-section"><h3>Candidate comparison</h3><div className="report-candidates">{report.candidates.map(c => <div className="report-candidate" key={c.id}><span>{c.make} {c.model}</span><strong>{money(c.price, c.currency)}</strong><small>{mileage(c)} · {c.transmission || 'Transmission unknown'}</small><CandidateEvidence candidate={c}/></div>)}</div></div><div className="report-section market-block"><h3>Market evidence</h3><p>{report.market.message}</p></div><div className="report-section"><h3>Questions to resolve</h3>{report.questions.map(q => <div className="questions" key={q.candidate_id}><strong>{report.candidates.find(c => c.id === q.candidate_id)?.title || 'Candidate'}</strong><ul>{q.questions.map(question => <li key={question}>{question}</li>)}</ul></div>)}</div>{report.warnings.length > 0 && <div className="report-footnote"><CircleAlert size={15}/>{report.warnings.join(' ')}</div>}</article></section>;
}
