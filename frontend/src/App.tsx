import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, Check, CircleAlert, FileText, Gauge, Link2, LoaderCircle, Pencil, Plus, RefreshCw, RotateCcw, Sparkles, X } from 'lucide-react';
import { api, apiLog, API_REVISION, ApiError, compareClientTimeoutMs, errorMessage, importClientTimeoutMs } from './api';
import { ApiInspector, JsonView } from './ApiInspector';
import type { Candidate, Health, ImportSlot, Preferences, RecoverySource, Report } from './types';
import { Review } from './Review';
import { ReportView } from './ReportView';
import { cacheImport, cachedImport, clearDraft, loadDraft, loadRecoverySource, saveDraft, saveRecoverySource } from './storage';
import { derivePercentOfMsrp } from './compare';
import { dateLabel, defaultPreferences, editCandidate, fieldOptions, freshSlot, importBody, mileage, money, readableField, recoveryBadge, restoreSlot, safeUrl, sourceLabel } from './utils';

const CONSTRAINT_NARROW = '(max-width: 900px)';
const mediaQuery = (query: string) =>
  typeof window === 'undefined' || typeof window.matchMedia !== 'function' ? null : window.matchMedia(query);
function useNarrowViewport(query: string): boolean {
  const [narrow, setNarrow] = useState(() => mediaQuery(query)?.matches ?? false);
  useEffect(() => {
    const mql = mediaQuery(query);
    if (!mql) return;
    setNarrow(mql.matches);
    const onChange = (event: MediaQueryListEvent) => setNarrow(event.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return narrow;
}

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
  const [recoverySource, setRecoverySource] = useState<RecoverySource>(loadRecoverySource);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [buildSlow, setBuildSlow] = useState(false);
  const compareAbort = useRef<AbortController | null>(null);
  const importAbort = useRef<AbortController | null>(null);
  const candidates = useMemo(() => slots.map(s => s.candidate).filter((c): c is Candidate => Boolean(c)), [slots]);
  const narrowConstraints = useNarrowViewport(CONSTRAINT_NARROW);

  useEffect(() => { api.health().then(setHealth).catch(() => undefined); }, []);
  useEffect(() => saveDraft({ slots, preferences }), [slots, preferences]);
  useEffect(() => saveRecoverySource(recoverySource), [recoverySource]);
  useEffect(() => {
    if (!busy) { setBuildSlow(false); return; }
    const t = window.setTimeout(() => setBuildSlow(true), 20_000);
    return () => window.clearTimeout(t);
  }, [busy]);


  const updateSlot = (id: string, update: Partial<ImportSlot>) => {
    setReport(null);
    setSlots(current => current.map(s => s.id === id ? { ...s, ...update } : s));
  };
  // Importing stays on this step: the result is shown in the car's card, and the user moves on when ready.
  const importSlot = async (slot: ImportSlot, refresh = false) => {
    const body = importBody(slot, recoverySource);
    const cached = refresh ? null : cachedImport(body);
    if (cached) {
      const { result } = cached;
      apiLog.add({ method: 'POST', endpoint: '/api/import', request: body, status: 'cached', response: result,
                   note: `No request sent: reused the result saved in this browser at ${new Date(cached.at).toLocaleString()}. Use Refresh to call the API.` });
      // A fresh id keeps candidates unique if the same listing is cached into two cards.
      updateSlot(slot.id, { candidate: result.candidate && { ...result.candidate, id: crypto.randomUUID() }, status: result.status,
                            message: result.message, attempts: result.attempts, recovery_status: result.recovery_status, cachedAt: cached.at, editing: false,
                            raw: { request: body, status: 'cached', response: result } });
      return;
    }
    setBusy(true); setLoadingSlot(slot.id); setNotice('');
    importAbort.current?.abort();
    const ac = new AbortController();
    importAbort.current = ac;
    try {
      const result = await api.import(body, ac.signal, importClientTimeoutMs(health?.import_timeout_seconds));
      cacheImport(body, result);
      updateSlot(slot.id, { candidate: result.candidate, status: result.status, message: result.message, attempts: result.attempts,
                            recovery_status: result.recovery_status, cachedAt: undefined, editing: false, raw: { request: body, status: 200, response: result } });
    } catch (error) {
      updateSlot(slot.id, { candidate: null, status: 'failed', message: errorMessage(error), attempts: error instanceof ApiError ? error.result.attempts : [],
                            recovery_status: error instanceof ApiError ? error.result.recovery_status : null, cachedAt: undefined, editing: false,
                            raw: { request: body, status: errorMessage(error).split(':')[0], response: error instanceof ApiError ? error.result : { error: errorMessage(error) } } });
    } finally {
      setBusy(false); setLoadingSlot(null);
      // Refresh the paid-provider meter shown in the source switch (a local call, nothing is billed).
      api.health().then(setHealth).catch(() => undefined);
    }
  };
  const addSlot = () => setSlots(current => current.length < 3 ? [...current, freshSlot()] : current);
  const removeSlot = (keep: (slot: ImportSlot) => boolean) => {
    setSlots(current => { const next = current.filter(keep); return next.length ? next : [freshSlot()]; });
    setReport(null);
  };
  const updateCandidate = (id: string, field: keyof Candidate, raw: string) => {
    setSlots(current => current.map(s => {
      if (s.candidate?.id !== id) return s;
      const numeric = field === 'year' || field === 'price' || field === 'mileage' || field === 'msrp';
      let candidate = editCandidate(s.candidate, field, numeric ? (raw ? Number(raw) : null) : raw || null);
      // Keep percent_of_msrp in sync with local price/msrp edits (contract shape).
      if (field === 'price' || field === 'msrp' || field === 'currency') {
        candidate = { ...candidate, percent_of_msrp: derivePercentOfMsrp(candidate) };
      }
      return { ...s, candidate };
    }));
    setReport(null);
  };
  const cancelImport = () => { importAbort.current?.abort('cancel'); };
  const cancelCompare = () => { compareAbort.current?.abort('cancel'); };
  const generateReport = async () => {
    if (candidates.length < 2) { setNotice('Import at least two candidates before generating a report.'); return; }
    compareAbort.current?.abort();
    const ac = new AbortController();
    compareAbort.current = ac;
    setBusy(true); setNotice(''); setCompareError(null); setBuildSlow(false);
    try {
      const remote = await api.compare(candidates, preferences, ac.signal, compareClientTimeoutMs(health?.compare_timeout_seconds));
      // Keep the MSRP this page holds if the backend omits it on the way back, with its own evidence:
      // a value the buyer typed stays "you entered", a VIN-decoded one keeps the NeoVIN source.
      const local = new Map(candidates.map(c => [c.id, c]));
      const merged = remote.candidates.map(c => {
        const from = local.get(c.id);
        const msrp = from?.msrp ?? c.msrp ?? null;
        const evidence = from?.evidence.msrp ?? c.evidence.msrp
          ?? (from?.msrp != null ? { value: String(msrp), source: 'Buyer-entered original MSRP', status: 'user_confirmed' as const } : null);
        const withMsrp = msrp == null ? c : {
          ...c,
          msrp,
          evidence: { ...c.evidence, ...(evidence ? { msrp: evidence } : {}) },
        };
        // Prefer backend-derived percent_of_msrp; FE fallback only when PR #2 fields absent.
        if (withMsrp.percent_of_msrp != null) return withMsrp;
        const percent = derivePercentOfMsrp(withMsrp);
        return percent == null ? withMsrp : { ...withMsrp, percent_of_msrp: percent };
      });
      // Mirror contract: Report.cross_model until backend sets it.
      const makes = new Set(merged.map(c => (c.make ?? '').trim().toLowerCase()));
      const models = new Set(merged.map(c => (c.model ?? '').trim().toLowerCase()));
      const cross = remote.cross_model ?? (merged.some(c => !c.make || !c.model) || makes.size > 1 || models.size > 1);
      const next = { ...remote, candidates: merged, cross_model: cross };
      setReport(next);
      setStep('report');
      const aiMsg = next.ai_analysis?.message?.trim();
      if (aiMsg && (next.ai_analysis?.status === 'unavailable' || next.ai_analysis?.status === 'partial')
          && /time limit|timed out|stopped at the server/i.test(aiMsg)) {
        setNotice(aiMsg);
      }
    }
    catch (error) {
      const msg = errorMessage(error);
      setCompareError(msg);
      setNotice(msg);
    } finally {
      if (compareAbort.current === ac) compareAbort.current = null;
      setBusy(false);
      setBuildSlow(false);
    }
  };
  const loadDemo = async () => { setReport(null); setBusy(true); try { const data = await api.demo(); setSlots(data.candidates.slice(0, 3).map(candidate => ({ ...freshSlot(), candidate, status: 'success', message: 'Loaded synthetic example' }))); setStep('import'); setNotice('Synthetic examples loaded. These are not live market observations.'); } catch (error) { setNotice(errorMessage(error)); } finally { setBusy(false); } };
  const reset = () => { if (busy) return; clearDraft(); setSlots([freshSlot()]); setPreferences(defaultPreferences); setReport(null); setStep('import'); setNotice(''); };

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" onClick={e => { e.preventDefault(); reset(); }}><span className="brand-mark">R</span><span>RevRank</span></a><span className="top-note">Vehicle comparison workspace</span><button className="text-button" onClick={reset}><RotateCcw size={15}/> New comparison</button></header>
    <main><div className="workspace-controls" aria-busy={busy || undefined}>
      {step === 'import' && <section className="intro"><div><p className="eyebrow">COMPARE THE CARS, NOT THE HYPE</p><h1>Make the next car decision with evidence.</h1><p className="lede">Bring in the listings you’re considering. RevRank extracts the details, checks the tradeoffs, and builds a report around what matters to you.</p></div><div className="status-card"><span className="status-dot"/>Local workspace<br/><small>Your draft stays in this browser.</small></div></section>}
      <nav className="steps" aria-label="Comparison steps">{[['import','01','Import listings'],['review','02','Review details'],['report','03','Read report']].map(([key,num,label], i) => <button key={key} className={step === key ? 'step active' : 'step'} onClick={() => (key === 'review' && candidates.length === 0) ? setNotice('Import a listing first.') : setStep(key as typeof step)}><span>{num}</span>{label}{i < 2 && <ArrowRight size={15}/>}</button>)}</nav>
      {health && health.api_revision !== API_REVISION && <div className="notice" role="alert"><CircleAlert size={17}/><span>The running RevRank backend is older than this page (API revision {health.api_revision ?? 1}, expected {API_REVISION}). Its results may be wrong, for example rejecting enabled websites. Stop scripts/dev.py with Ctrl+C and start it again.</span></div>}
      {health?.search_enabled === false && !health.licensed_inventory_enabled && !health.browser_recovery_enabled && <div className="notice" role="status"><CircleAlert size={17}/><span>{!health.search_provider?.trim() || health.search_provider === 'none' ? 'Search recovery is unavailable: no search provider is configured.' : `Search recovery is unavailable (provider setting: ${health.search_provider}).`} For local setup, set REVRANK_SEARCH_PROVIDER to brave or tavily and REVRANK_SEARCH_API_KEY (or a licensed REVRANK_MARKETCHECK_API_KEY, or REVRANK_BROWSER_RECOVERY_ENABLED) in the backend’s local .env, then restart the backend and reload this page. Keep the key server-side. Paste listing text to continue without search.</span></div>}
      {notice && <div className="notice"><CircleAlert size={17}/><span>{notice}</span></div>}
      {step === 'import' && <section className="workspace"><div className="panel main-panel"><div className="panel-heading"><div><p className="eyebrow">START HERE</p><h2>Import the cars you’re considering</h2></div><button className="secondary-button" onClick={loadDemo} disabled={busy}><Sparkles size={16}/> Use examples</button></div><p className="muted">Paste a listing URL from a supported source, or paste the listing text when a website blocks automated access.</p><SourceSwitch value={recoverySource} onChange={setRecoverySource} health={health}/><div className="import-grid">{slots.map((slot, index) => <ImportCard key={slot.id} slot={slot} index={index} busy={busy} loading={loadingSlot === slot.id} canRemove={slots.length > 1 || Boolean(slot.candidate || slot.url || slot.text || slot.vin)} onChange={update => updateSlot(slot.id, update)} onImport={refresh => importSlot(slot, refresh)} onCancel={cancelImport} onRemove={() => removeSlot(s => s.id !== slot.id)} onEditField={(field, raw) => slot.candidate && updateCandidate(slot.candidate.id, field, raw)} />)}{slots.length < 3 && <button className="add-card" onClick={addSlot}><Plus size={18}/><strong>Add a {slots.length === 1 ? 'second' : 'third'} car</strong><span>Compare up to three listings</span></button>}</div><div className="import-footer"><p className="muted">{candidates.length} of {slots.length} {slots.length === 1 ? 'car' : 'cars'} imported{candidates.length < 2 ? ' · import at least two to generate a report' : ''}</p><button className="primary-button" disabled={!candidates.length} onClick={() => setStep('review')}>Review details <ArrowRight size={16}/></button></div></div><aside className="panel side-panel"><Gauge size={21} className="amber"/><h3>What happens next</h3><ol><li>We identify the exact model, generation, mileage, and price.</li><li>You confirm anything missing or unclear.</li><li>Price, mileage, and evidence quality shape the final comparison.</li></ol><div className="side-callout"><strong>Built for uncertainty</strong><p>Seller claims and unknown history remain labeled in your report.</p></div></aside></section>}
      {step === 'review' && <Review candidates={candidates} preferences={preferences} setPreferences={setPreferences} updateCandidate={updateCandidate} removeCandidate={(id) => removeSlot(s => s.candidate?.id !== id)} generateReport={generateReport} onCancelCompare={cancelCompare} compareError={compareError} buildSlow={buildSlow} onAddMore={() => { addSlot(); setStep('import'); }} busy={busy} narrow={narrowConstraints} />}
      {step === 'report' && !report && <div className="panel main-panel"><h2>Generate an updated report</h2><p>Your inputs have changed or no report has been generated yet.</p><button className="primary-button" onClick={() => setStep(candidates.length ? 'review' : 'import')}>Return to {candidates.length ? 'review' : 'import'}</button></div>}
      {step === 'report' && report && <ReportView report={report} preferences={preferences} setPreferences={setPreferences} onApply={generateReport} onCancelCompare={cancelCompare} compareError={compareError} buildSlow={buildSlow} busy={busy} narrow={narrowConstraints} onBack={() => setStep('review')} onReset={reset} />}
    </div></main>
    <ApiInspector/>
    <footer><span>RevRank v0.1 · Evidence before certainty</span><span><FileText size={14}/> Reports are informational estimates</span></footer>
  </div>;
}

const PROVIDER_NAMES: Record<string, string> = { marketcheck: 'MarketCheck', tavily: 'Tavily', brave: 'Brave' };
const providerName = (key: string | undefined) => (key && PROVIDER_NAMES[key]) || 'Search';

// Debug switch: which paid provider may be called when a listing page is blocked. Both have small quotas.
function SourceSwitch({ value, onChange, health }: { value: RecoverySource; onChange: (source: RecoverySource) => void; health: Health | null }) {
  const search = providerName(health?.search_provider);
  // One more MarketCheck call decodes a known VIN for the factory MSRP; say so, the quota is small.
  const neovin = health?.neovin_msrp_enabled ? ' One extra call decodes a known VIN for its original MSRP.' : '';
  const options: { key: RecoverySource; label: string; ready: boolean; hint: string }[] = [
    { key: 'auto', label: 'Auto', ready: true, hint: health?.browser_recovery_enabled
      ? `MarketCheck first; private browse of your listing URL only if MarketCheck misses; ${search} after that.${neovin}`
      : `MarketCheck first, then ${search}. Private browse is off (Tongli opt-in; not counsel clearance).${neovin}` },
    { key: 'marketcheck', label: 'MarketCheck', ready: Boolean(health?.licensed_inventory_enabled), hint: `Only MarketCheck is called: usually 1 call per import, at most 3.${neovin}` },
    { key: 'browse', label: 'Private browse', ready: Boolean(health?.browser_recovery_enabled), hint: 'Off by default. When enabled, opens only the listing URL you pasted. No review sites. Bot-manager blocks are reported, not bypassed. Enablement waits on Research rights guidance and Tongli opt-in; not counsel clearance.' },
    { key: 'search', label: search, ready: Boolean(health?.search_enabled), hint: `Only ${search} is called: up to 4 searches per import. Excerpts can be stale.` },
  ];
  const chosen = options.find(o => o.key === value) ?? options[0];
  const meter = Object.entries(health?.usage ?? {});
  return <div className="source-switch">
    <span className="source-label">Recovery source <em>debug</em></span>
    <div className="segmented" role="radiogroup" aria-label="Recovery source for blocked listings">
      {options.map(o => <button key={o.key} type="button" role="radio" aria-checked={value === o.key} className={value === o.key ? 'on' : ''}
        disabled={!o.ready} title={o.ready ? o.hint : `${o.label} is not configured on the server.`} onClick={() => onChange(o.key)}>{o.label}</button>)}
    </div>
    <small>{chosen.hint}{meter.length > 0 && <> This month: {meter.map(([key, u]) =>
      <span key={key} className={u.used >= u.limit * .9 ? 'meter low' : 'meter'}
        title="Counted by this server only. The provider's own account may have spent more, and its own limit is the one that refuses a call.">
        {providerName(key)} {u.used}/{u.limit} {u.unit}</span>)}</>}</small>
  </div>;
}

const ORDINALS = ['First', 'Second', 'Third'];
const METHOD_LABELS: Record<string, string> = {
  direct: 'Fetched from listing', search: 'Recovered via search', licensed: 'MarketCheck inventory',
  browse: 'Private browse of listing', registry: 'VIN decode only', paste: 'From pasted text', synthetic: 'Synthetic example',
};

type StatField = 'price' | 'mileage' | 'location';
interface ImportCardProps {
  slot: ImportSlot; index: number; busy: boolean; loading: boolean; canRemove: boolean;
  onChange: (update: Partial<ImportSlot>) => void; onImport: (refresh: boolean) => void; onCancel?: () => void; onRemove: () => void;
  onEditField: (field: StatField, raw: string) => void;
}

// What still needs a look before comparing; a value the user entered counts as resolved.
function reviewItems(car: Candidate): string[] {
  const unresolved = (car.conflicts ?? []).filter(field => !car.verified_fields.includes(field));
  const missing = (['year', 'make', 'model', 'price', 'mileage'] as const).filter(field => car[field] === null && !unresolved.includes(field));
  return [...unresolved.map(field => `${readableField(field).toLowerCase()} (${field === 'mileage' && car.mileage !== null ? 'higher reading elsewhere' : 'sources disagree'})`),
          ...missing.map(field => readableField(field).toLowerCase()),
          ...(car.price !== null && car.currency === 'UNK' && !car.verified_fields.includes('price') ? ['currency'] : [])];
}


const PASTE_STATUSES = new Set(['blocked', 'restricted', 'failed', 'unsupported', 'partial']);
const PASTE_RECOVERY = new Set(['failed', 'not_found', 'unavailable']);

function needsPasteFallback(slot: ImportSlot): boolean {
  if (slot.candidate || !slot.message) return false;
  // Identity conflict is a VIN disagreement, not a silent miss — do not swap it for paste.
  if (slot.recovery_status === 'identity_conflict') return false;
  if (slot.recovery_status && PASTE_RECOVERY.has(slot.recovery_status)) return true;
  return Boolean(slot.status && PASTE_STATUSES.has(slot.status));
}

function pasteFallbackTitle(status: ImportSlot['status'] | undefined): string {
  // Buyer-facing; never surface operator/infra wording.
  if (status === 'blocked' || status === 'restricted' || status === 'unsupported') {
    return 'We couldn’t open this listing page';
  }
  return 'We couldn’t import this listing';
}

// Map server/registry strings to plain buyer copy (friend demo).
function buyerImportMessage(message: string | undefined): string | null {
  if (!message) return null;
  const m = message.toLowerCase();
  if (m.includes('operator opt-in') || m.includes('live fetch') || m.includes('allowlist')) {
    return 'We couldn’t open this listing page — paste the asking price, mileage, and VIN.';
  }
  if (m.includes('robot') || m.includes('blocked') || m.includes('403')) {
    return 'We couldn’t open this listing page — paste the asking price, mileage, and VIN.';
  }
  return message;
}


// One-line outcome from attempts; never invents providers beyond what the server returned.
function recoveryOutcomeLine(slot: ImportSlot): string | null {
  const attempts = slot.attempts ?? [];
  if (!attempts.length && !slot.recovery_status) return null;
  if (!attempts.length) return `Recovery status: ${readableField(slot.recovery_status!)}`;
  const parts = attempts.map(a => `${readableField(a.method)} · ${readableField(a.status).toLowerCase()}`);
  const last = attempts[attempts.length - 1];
  // "not found" contains "found": a dead end must never be read as the step that worked.
  const ok = last.status !== 'not_found' && ['success', 'ok', 'matched', 'found'].some(s => last.status.toLowerCase().includes(s));
  if (slot.candidate) {
    return ok
      ? `Tried ${parts.join(', then ')} — used ${METHOD_LABELS[slot.candidate.retrieval_method ?? ''] ?? readableField(slot.candidate.retrieval_method ?? 'recovery')}.`
      : `Tried ${parts.join(', then ')}.`;
  }
  return `Tried ${parts.join(', then ')} — paste the listing text or add a VIN to continue.`;
}

function ImportCard({ slot, index, busy, loading, canRemove, onChange, onImport, onCancel, onRemove, onEditField }: ImportCardProps) {
  const candidate = slot.candidate;
  const showForm = !candidate || slot.editing;
  const ready = slot.status === 'success' || (candidate !== null && reviewItems(candidate).length === 0);
  const pasteNeeded = needsPasteFallback(slot);
  const outcome = recoveryOutcomeLine(slot);
  const cardClass = [showForm ? 'import-card' : 'import-card has-vehicle', pasteNeeded ? 'needs-paste' : ''].filter(Boolean).join(' ');
  return <div className={cardClass}>
    <div className="card-top">
      <span className="card-number">0{index + 1}</span><strong>{ORDINALS[index]} car</strong>
      <span className="card-actions">
        {candidate && <span className={ready ? 'pill success' : 'pill review'}>{ready ? <><Check size={12}/> Ready</> : 'Needs review'}</span>}
        {canRemove && <button className="icon-button" title="Remove this car" aria-label={`Remove ${ORDINALS[index].toLowerCase()} car`} onClick={onRemove}><X size={15}/></button>}
      </span>
    </div>
    {showForm ? <>
      {pasteNeeded && <div className="paste-callout" role="status">
        <strong><CircleAlert size={15}/> {pasteFallbackTitle(slot.status)}</strong>
        <p>Paste the asking price, mileage, and VIN from the listing, then import again.</p>
        {buyerImportMessage(slot.message) && <p className="paste-callout-detail">{buyerImportMessage(slot.message)}</p>}
      </div>}
      <label>Listing URL <span>optional</span><input value={slot.url} onChange={e => onChange({ url: e.target.value })} placeholder="https://…" /></label>
      <label>VIN <span>optional</span><input value={slot.vin} onChange={e => onChange({ vin: e.target.value })} placeholder="Vehicle identification number" /></label>
      <label className="recovery-toggle"><input type="checkbox" checked={slot.recover} onChange={e => onChange({ recover: e.target.checked })}/> Try search recovery if needed</label>
      <label className={pasteNeeded ? 'paste-field highlight' : undefined}>Or paste listing text <span>fallback</span>
        <textarea value={slot.text} onChange={e => onChange({ text: e.target.value })} placeholder="Vehicle name, price, mileage, options…" rows={4}/></label>
      <div className="form-actions">
        <button className="primary-button full" onClick={() => onImport(false)} disabled={busy || (!slot.url.trim() && !slot.text.trim())}>
          {loading ? <LoaderCircle className="spin" size={16}/> : <Link2 size={16}/>} {loading ? 'Importing…' : candidate ? 'Import replacement' : 'Import car'}
        </button>
        {loading && onCancel && <button type="button" className="secondary-button full" onClick={onCancel}>Cancel</button>}
        {candidate && <button className="secondary-button full" onClick={() => onChange({ editing: false })}>Cancel</button>}
      </div>
      {!candidate && slot.message && !pasteNeeded && <p className="import-error"><CircleAlert size={15}/><span>{buyerImportMessage(slot.message) ?? slot.message}</span></p>}
    </> : <VehicleSummary slot={slot} busy={busy} loading={loading} onEdit={() => onChange({ editing: true })} onRefresh={() => onImport(true)} onCancel={onCancel} onEditField={onEditField} />}
    {outcome && <p className="recovery-outcome"><CircleAlert size={14}/><span>{outcome}</span></p>}
    {(slot.message || !!slot.attempts?.length) && <details className="import-log">
      <summary>Import details</summary>
      {candidate && slot.message && <p>{slot.message}</p>}
      <RecoveryAttempts slot={slot}/>
      {slot.raw && <details className="raw-response">
        <summary>API response · POST /api/import · {String(slot.raw.status)}</summary>
        <p className="inspector-note">Request body</p><JsonView value={slot.raw.request}/>
        <p className="inspector-note">Response</p><JsonView value={slot.raw.response}/>
      </details>}
    </details>}
  </div>;
}

interface StatProps {
  car: Candidate; field: StatField; label: string; display: string | null; empty: string; note?: ReactNode;
  unit?: string; disabled: boolean; onSave: (field: StatField, raw: string) => void;
}

// A summary value that turns into an input on click. Enter or leaving the field saves; Escape cancels.
function EditableStat({ car, field, label, display, empty, note, unit, disabled, onSave }: StatProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const numeric = field !== 'location';
  const current = car[field] === null ? '' : String(car[field]);
  const clean = draft === null ? '' : numeric ? draft.replace(/[\s,$]/g, '') : draft.trim();
  // Catches typos such as a pasted-in-twice price; real listings are far below these limits.
  const max = field === 'price' ? 10_000_000 : 2_000_000;
  const valid = (value: string) => !numeric || value === '' || (Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= max);
  const edited = car.evidence[field]?.status === 'user_confirmed';
  // Values the sources reported, offered as one-click answers.
  const options = fieldOptions(car, field).filter(o => o.value !== current).slice(0, 3);
  const save = (value = clean) => {
    if (!valid(value)) return;
    if (value !== current) onSave(field, value);
    setDraft(null);
  };
  if (draft === null) {
    return <div className="stat">
      <dt>{label}{edited && <span className="edited-tag" title={car.evidence[field]?.source}>edited</span>}</dt>
      <dd><button type="button" className={display ? 'stat-value' : 'stat-value muted-value'} disabled={disabled}
                  title={`Edit ${label.toLowerCase()}`} onClick={() => setDraft(current)}>
        <span>{display ?? empty}</span><Pencil size={11} aria-hidden="true"/>
      </button>{note}</dd>
    </div>;
  }
  return <div className="stat editing" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) save(); }}>
    <dt><label htmlFor={`${car.id}-${field}`}>{label}</label></dt>
    <dd>
      <span className="stat-input">
        <input id={`${car.id}-${field}`} autoFocus value={draft} inputMode={numeric ? 'numeric' : 'text'} aria-invalid={!valid(clean)}
               placeholder={numeric ? 'Unknown' : 'City, ST'} onChange={e => setDraft(e.target.value)}
               onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setDraft(null); }}/>
        {unit && <span className="stat-unit">{unit}</span>}
      </span>
      {!valid(clean) && <small className="stat-error">{Number.isFinite(Number(clean)) && Number(clean) > max
        ? `That looks too high; enter at most ${max.toLocaleString()}.` : 'Enter a number, for example 40998.'}</small>}
      {options.length > 0 && <span className="stat-options">{options.map(o =>
        <button key={o.value} type="button" className="choice" onClick={() => save(o.value)} title={`Use the value reported by ${o.hosts.join(', ')}`}>
          {numeric ? Number(o.value).toLocaleString() : o.value}<small>{o.hosts.join(', ')}</small></button>)}</span>}
    </dd>
  </div>;
}

function VehicleSummary({ slot, busy, loading, onEdit, onRefresh, onCancel, onEditField }: { slot: ImportSlot; busy: boolean; loading: boolean; onEdit: () => void; onRefresh: () => void; onCancel?: () => void; onEditField: (field: StatField, raw: string) => void }) {
  const car = slot.candidate as Candidate;
  const unresolved = (car.conflicts ?? []).filter(field => !car.verified_fields.includes(field));
  const unknown = (field: StatField) => unresolved.includes(field) ? 'Sources disagree' : 'Unknown';
  // A bare "$" does not establish the currency, so an unconfirmed price is shown without one.
  const price = car.price === null ? null : car.currency === 'UNK' ? car.price.toLocaleString() : money(car.price, car.currency);
  const review = reviewItems(car);
  const vin = car.evidence.vin?.value;
  const link = safeUrl(car.source_url);
  const name = [car.year, car.make, car.model].filter(Boolean).join(' ') || car.title;
  return <div className="vehicle-summary">
    <p className="vehicle-kicker">{link ? <a href={link} target="_blank" rel="noopener noreferrer">{sourceLabel(car)}</a> : sourceLabel(car)}</p>
    <h3>{name}</h3>
    {car.trim && <p className="vehicle-trim">{car.trim}</p>}
    <dl className="vehicle-stats">
      <EditableStat car={car} field="price" label="Price" display={price} empty={unknown('price')} disabled={busy} onSave={onEditField}
        unit={car.currency === 'UNK' ? undefined : car.currency}
        note={<>{price && car.currency === 'UNK' && <small>currency unconfirmed</small>}
          {!price && car.evidence.last_listed_price && <small title={car.evidence.last_listed_price.source}>last listed {car.evidence.last_listed_price.value}</small>}</>}/>
      <EditableStat car={car} field="mileage" label="Mileage" display={car.mileage === null ? null : mileage(car)} empty={unknown('mileage')}
        unit={car.mileage_unit} disabled={busy} onSave={onEditField}/>
      <EditableStat car={car} field="location" label="Location" display={car.location} empty={unknown('location')} disabled={busy} onSave={onEditField}/>
    </dl>
    <div className="vehicle-tags">
      <span className="tag">{METHOD_LABELS[car.retrieval_method ?? 'direct'] ?? readableField(car.retrieval_method ?? 'direct')}</span>
      {recoveryBadge(slot.recovery_status) && <span className="tag recovery-tag">{recoveryBadge(slot.recovery_status)}</span>}
      <span className="tag">{vin ? `VIN ${vin}` : 'VIN unknown'}</span>
      {(car.dom != null || car.dom_active != null) && <span className="tag" title={car.first_seen_at ? `First seen ${car.first_seen_at}` : undefined}>
        {car.dom_active != null ? `${car.dom_active}d active` : `${car.dom}d on market`}
      </span>}
      {slot.cachedAt && <span className="tag" title="Reused a result saved in this browser; Refresh requests it again.">Saved {dateLabel(new Date(slot.cachedAt).toISOString())}</span>}
    </div>
    {(car.retrieval_method === 'search' || car.retrieval_method === 'licensed' || car.retrieval_method === 'browse') &&
      <p className="vehicle-recovered"><CircleAlert size={15}/><span>{car.retrieval_method === 'browse'
        ? 'Recovered from a private browse of this listing — please confirm price and mileage.'
        : 'Recovered from inventory data — please confirm price and mileage.'}</span></p>}
    {review.length ? <p className="vehicle-review"><CircleAlert size={15}/><span>Check before comparing: {review.join(', ')}.</span></p>
                   : <p className="vehicle-ok"><Check size={15}/><span>Key details found. Click a value to correct it.</span></p>}
    <div className="vehicle-actions">
      <button className="secondary-button" onClick={onEdit} disabled={busy}><Pencil size={14}/> Change listing</button>
      {(slot.url.trim() || slot.text.trim()) && <button className="secondary-button" onClick={onRefresh} disabled={busy}>
        {loading ? <LoaderCircle className="spin" size={14}/> : <RefreshCw size={14}/>} {loading ? 'Refreshing…' : 'Refresh'}
      </button>}
      {loading && onCancel && <button type="button" className="secondary-button" onClick={onCancel}>Cancel</button>}
    </div>
  </div>;
}

function RecoveryAttempts({ slot }: { slot: ImportSlot }) {
  if (!slot.recovery_status && !slot.attempts?.length) return null;
  return <div className="recovery-details" aria-live="polite">
    <strong>Import attempts</strong>
    {slot.recovery_status && <p>Recovery status: {readableField(slot.recovery_status)}</p>}
    <ol>{slot.attempts?.map((attempt, index) => <li key={index}>
      <strong>{readableField(attempt.method)} · {readableField(attempt.status).toLowerCase()}</strong><p>{attempt.detail}</p></li>)}</ol>
  </div>;
}
