import { useEffect, useId, useRef, useState } from 'react';
import { CircleAlert, LoaderCircle, Sparkles, X } from 'lucide-react';
import { api, errorMessage } from './api';
import type { Preferences } from './types';
import { defaultPreferences } from './utils';

const SUGGESTIONS = [
  { label: 'Under $45k', apply: (p: Preferences): Preferences => ({ ...p, budget: 45000 }) },
  { label: 'Keep 4 years', apply: (p: Preferences): Preferences => ({ ...p, ownership_years: 4 }) },
  { label: '12k mi / year', apply: (p: Preferences): Preferences => ({ ...p, annual_mileage: 12000 }) },
  { label: 'Priority: lower price', apply: (p: Preferences): Preferences => ({
    ...p, priorities: p.priorities.includes('Lower asking price') ? p.priorities : [...p.priorities, 'Lower asking price'],
  }) },
];

function splitList(value: string) {
  return value.split(',').map(x => x.trim()).filter(Boolean);
}

export function preferencesEqual(a: Preferences, b: Preferences): boolean {
  const list = (xs: string[] | undefined) => [...(xs ?? [])].map(x => x.trim()).filter(Boolean).sort().join('\0');
  return a.budget === b.budget
    && a.annual_mileage === b.annual_mileage
    && a.ownership_years === b.ownership_years
    && (a.location || '') === (b.location || '')
    && (a.max_mileage ?? null) === (b.max_mileage ?? null)
    && (a.transmission ?? null) === (b.transmission ?? null)
    && list(a.priorities) === list(b.priorities)
    && list(a.must_haves) === list(b.must_haves)
    && list(a.excludes) === list(b.excludes);
}

const MODE_LABEL = {
  llm: 'Mapped by the configured model, and checked against your own words',
  rules: 'Mapped by phrase rules on the server (no model configured, or the model call failed)',
};
const EXAMPLE = 'About 30k, keeping it 5 years, needs AWD, no salvage titles';

interface Turn {
  id: number;
  you: string;
  reply?: string;
  mode?: 'llm' | 'rules';
  applied?: number;
  failure?: string;
}

/** A short chat that only fills the chips below. It can write preference fields and nothing else:
 *  it never states or changes a fact about a car, and it is not inventory discovery — the
 *  shortlist stays the cars you imported. */
function ConstraintChat({ preferences, onChange, busy, mode }: {
  preferences: Preferences; onChange: (next: Preferences) => void; busy?: boolean; mode: 'review' | 'report';
}) {
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [reading, setReading] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const nextCta = mode === 'report' ? 'Apply to report' : 'Generate comparison';

  // Keep the newest turn in view without yanking the whole page around.
  useEffect(() => {
    const box = thread.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns]);

  const send = async (message: string) => {
    const said = message.trim();
    if (!said || reading) return;
    const id = Date.now();
    setTurns(current => [...current, { id, you: said }].slice(-6));
    setText('');
    setReading(true);
    try {
      const parsed = await api.constraints(said, preferences);
      onChange(parsed.preferences);
      setTurns(current => current.map(turn => turn.id === id
        ? { ...turn, reply: parsed.reply, mode: parsed.mode, applied: parsed.constraints.length }
        : turn));
    } catch (error) {
      setTurns(current => current.map(turn => turn.id === id ? { ...turn, failure: errorMessage(error) } : turn));
    } finally {
      setReading(false);
    }
  };

  return <div className="constraint-chat">
    <p className="constraint-label">Say it in your own words <span>optional</span></p>
    {turns.length > 0 && <div className="chat-thread" ref={thread} aria-live="polite">
      {turns.map(turn => <div className="chat-turn" key={turn.id}>
        <p className="chat-you">{turn.you}</p>
        {turn.failure
          ? <p className="chat-reply failed"><CircleAlert size={13}/> {turn.failure}</p>
          : turn.reply
            ? <div className="chat-reply">
                <p>{turn.reply}</p>
                <small title={MODE_LABEL[turn.mode ?? 'rules']}>
                  {turn.mode === 'llm' ? 'Model-mapped' : 'Phrase rules'}
                  {turn.applied ? ` · ${turn.applied} chip${turn.applied === 1 ? '' : 's'} set` : ''}
                </small>
              </div>
            : <p className="chat-reply pending"><LoaderCircle className="spin" size={13}/> Reading…</p>}
      </div>)}
    </div>}
    <textarea value={text} rows={2} disabled={busy || reading} aria-label="Describe your constraints"
      placeholder={turns.length ? 'Add another constraint…' : EXAMPLE}
      onChange={e => setText(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(text); } }}/>
    <div className="chat-actions">
      <button type="button" className="secondary-button" disabled={busy || reading || !text.trim()} onClick={() => void send(text)}>
        {reading ? <><LoaderCircle className="spin" size={14}/> Reading…</> : <><Sparkles size={14}/> Read into chips</>}
      </button>
      {!turns.length && !text.trim() && <button type="button" className="chat-example" disabled={busy || reading}
        onClick={() => setText(EXAMPLE)}>Try an example</button>}
    </div>
    <p className="constraint-hint">Fills the chips below. It never changes a car's details and never looks for other cars.
      {turns.some(turn => turn.applied) && <> Check the chips, then <strong>{nextCta}</strong>.</>}</p>
  </div>;
}

interface Props {
  preferences: Preferences;
  onChange: (next: Preferences) => void;
  onApply: () => void;
  busy?: boolean;
  /** Report re-rank vs Review setup before first generate. */
  mode: 'review' | 'report';
  /** Mobile: collapsed summary + Edit opens the sheet. */
  narrow?: boolean;
  /** Preferences last applied into the current report (Report mode dirty cue). */
  applied?: Preferences | null;
}

export function ConstraintPanel({ preferences, onChange, onApply, busy, mode, narrow, applied }: Props) {
  const [open, setOpen] = useState(false);
  const [draftPriority, setDraftPriority] = useState('');
  const [draftMust, setDraftMust] = useState('');
  const [draftExclude, setDraftExclude] = useState('');
  const titleId = useId();
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const atDefaults = preferencesEqual(preferences, defaultPreferences);
  const dirty = mode === 'report' && applied != null && !preferencesEqual(preferences, applied);

  const excludes = preferences.excludes ?? [];
  const customBits = [
    preferences.budget != null ? `Budget ≤ $${preferences.budget.toLocaleString()}` : null,
    preferences.max_mileage != null ? `≤ ${preferences.max_mileage.toLocaleString()} mi` : null,
    preferences.transmission,
    preferences.location ? preferences.location : null,
    ...preferences.priorities.slice(0, 2),
    ...preferences.must_haves.slice(0, 2),
    ...excludes.slice(0, 1).map(x => `no ${x}`),
  ].filter(Boolean) as string[];
  const yearsMilesCustom = preferences.ownership_years !== defaultPreferences.ownership_years
    || preferences.annual_mileage !== defaultPreferences.annual_mileage;
  const summaryText = atDefaults
    ? `Defaults: ${defaultPreferences.ownership_years} yr · ${defaultPreferences.annual_mileage.toLocaleString()} mi/yr`
    : [
        ...customBits,
        yearsMilesCustom || !customBits.length
          ? `${preferences.ownership_years} yr · ${preferences.annual_mileage.toLocaleString()} mi/yr`
          : null,
      ].filter(Boolean).join(' · ');

  const clearAll = () => onChange({ ...defaultPreferences });

  const closeSheet = () => {
    setOpen(false);
    queueMicrotask(() => editButtonRef.current?.focus());
  };

  useEffect(() => {
    if (!open || !narrow) return;
    const prev = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeSheet(); }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      if (prev && document.contains(prev)) prev.focus();
    };
  }, [open, narrow]);

  const body = <>
    <div className="constraint-head">
      <div>
        <p className="eyebrow">RE-RANK CONTROLS</p>
        <h3 id={titleId}>Your constraints</h3>
      </div>
      <p className="muted constraint-lede">
        {mode === 'report'
          ? 'Adjust chips, then Apply to rebuild the cited comparison. This is not discovery chat.'
          : 'Optional. Facts stay primary; these only steer the report when you generate.'}
      </p>
    </div>

    {dirty && <div className="constraint-dirty" role="status">
      <CircleAlert size={14}/> Constraints changed — Apply to rebuild.
    </div>}

    <ConstraintChat preferences={preferences} onChange={onChange} busy={busy} mode={mode}/>

    <div className="constraint-chips" role="list">
      <label className="constraint-chip" role="listitem">
        <span>Budget</span>
        <input type="number" inputMode="numeric" placeholder="No limit" value={preferences.budget ?? ''}
          onChange={e => onChange({ ...preferences, budget: e.target.value ? Number(e.target.value) : null })}/>
        {preferences.budget != null && <button type="button" className="chip-x" aria-label="Clear budget" onClick={() => onChange({ ...preferences, budget: null })}><X size={12}/></button>}
      </label>
      <label className="constraint-chip" role="listitem">
        <span>Years kept</span>
        <input type="number" inputMode="numeric" min={1} max={30} value={preferences.ownership_years}
          onChange={e => onChange({ ...preferences, ownership_years: Math.max(1, Number(e.target.value) || 1) })}/>
      </label>
      <label className="constraint-chip" role="listitem">
        <span>Annual miles</span>
        <input type="number" inputMode="numeric" min={0} value={preferences.annual_mileage}
          onChange={e => onChange({ ...preferences, annual_mileage: Math.max(0, Number(e.target.value) || 0) })}/>
      </label>
      <label className="constraint-chip" role="listitem">
        <span>Max miles</span>
        <input type="number" inputMode="numeric" min={0} placeholder="No limit" value={preferences.max_mileage ?? ''}
          onChange={e => onChange({ ...preferences, max_mileage: e.target.value ? Math.max(0, Number(e.target.value)) : null })}/>
        {preferences.max_mileage != null && <button type="button" className="chip-x" aria-label="Clear mileage ceiling" onClick={() => onChange({ ...preferences, max_mileage: null })}><X size={12}/></button>}
      </label>
      <label className="constraint-chip" role="listitem">
        <span>Gearbox</span>
        <select value={preferences.transmission ?? ''}
          onChange={e => onChange({ ...preferences, transmission: (e.target.value || null) as Preferences['transmission'] })}>
          <option value="">Either</option>
          <option value="manual">Manual</option>
          <option value="automatic">Automatic</option>
        </select>
      </label>
      <label className="constraint-chip wide" role="listitem">
        <span>Location</span>
        <input type="text" placeholder="City or ZIP" value={preferences.location}
          onChange={e => onChange({ ...preferences, location: e.target.value })}/>
        {preferences.location && <button type="button" className="chip-x" aria-label="Clear location" onClick={() => onChange({ ...preferences, location: '' })}><X size={12}/></button>}
      </label>
    </div>

    <div className="constraint-lists">
      <div>
        <p className="constraint-label">Priorities</p>
        <div className="chip-row">
          {preferences.priorities.map(p => <button key={p} type="button" className="tag-chip" onClick={() => onChange({ ...preferences, priorities: preferences.priorities.filter(x => x !== p) })}>
            {p}<X size={11}/>
          </button>)}
        </div>
        <form className="chip-add" onSubmit={e => {
          e.preventDefault();
          const next = splitList(draftPriority);
          if (!next.length) return;
          onChange({ ...preferences, priorities: [...new Set([...preferences.priorities, ...next])] });
          setDraftPriority('');
        }}>
          <input value={draftPriority} onChange={e => setDraftPriority(e.target.value)} placeholder="Add priority"/>
          <button type="submit" className="secondary-button">Add</button>
        </form>
      </div>
      <div>
        <p className="constraint-label">Must-haves</p>
        <div className="chip-row">
          {preferences.must_haves.map(p => <button key={p} type="button" className="tag-chip" onClick={() => onChange({ ...preferences, must_haves: preferences.must_haves.filter(x => x !== p) })}>
            {p}<X size={11}/>
          </button>)}
        </div>
        <form className="chip-add" onSubmit={e => {
          e.preventDefault();
          const next = splitList(draftMust);
          if (!next.length) return;
          onChange({ ...preferences, must_haves: [...new Set([...preferences.must_haves, ...next])] });
          setDraftMust('');
        }}>
          <input value={draftMust} onChange={e => setDraftMust(e.target.value)} placeholder="Add must-have"/>
          <button type="submit" className="secondary-button">Add</button>
        </form>
      </div>
      <div>
        <p className="constraint-label">Rule out</p>
        <div className="chip-row">
          {excludes.map(p => <button key={p} type="button" className="tag-chip" onClick={() => onChange({ ...preferences, excludes: excludes.filter(x => x !== p) })}>
            {p}<X size={11}/>
          </button>)}
        </div>
        <form className="chip-add" onSubmit={e => {
          e.preventDefault();
          const next = splitList(draftExclude);
          if (!next.length) return;
          onChange({ ...preferences, excludes: [...new Set([...excludes, ...next])] });
          setDraftExclude('');
        }}>
          <input value={draftExclude} onChange={e => setDraftExclude(e.target.value)} placeholder="e.g. salvage title"/>
          <button type="submit" className="secondary-button">Add</button>
        </form>
        {/* Silence in a listing has not ruled anything out, so the report says "not established"
            rather than treating a missing mention as a pass. */}
        <p className="constraint-hint">A silent listing counts as unestablished, not as a pass.</p>
      </div>
    </div>

    {atDefaults && <div className="constraint-suggestions">
      <p className="constraint-label">Suggested</p>
      <div className="chip-row">
        {SUGGESTIONS.map(s => <button key={s.label} type="button" className="suggest-chip" onClick={() => onChange(s.apply(preferences))}>{s.label}</button>)}
      </div>
    </div>}

    <div className={`constraint-actions${narrow ? ' sticky' : ''}`}>
      {mode === 'report'
        ? <button type="button" className="primary-button" disabled={busy} onClick={() => { onApply(); setOpen(false); }}>Apply to report</button>
        : narrow
          ? <button type="button" className="secondary-button" disabled={busy} onClick={() => setOpen(false)}>Save for report</button>
          : null}
      <button type="button" className="text-button" disabled={busy} onClick={clearAll}>Clear all</button>
    </div>
    {mode === 'review' && <p className="constraint-note muted-note">Generate comparison uses these chips.</p>}
    <p className="constraint-note"><CircleAlert size={13}/> We won’t invent fair-price or fit scores from these chips.</p>
  </>;

  if (!narrow) {
    return <aside className="constraint-panel panel">{body}</aside>;
  }

  return <div className="constraint-mobile">
    <div className="constraint-summary">
      <div>
        <p className="eyebrow">YOUR CONSTRAINTS</p>
        <p className="constraint-summary-text">{summaryText}</p>
        {dirty && <p className="constraint-dirty-inline">Constraints changed — Apply to rebuild.</p>}
      </div>
      <button type="button" className="secondary-button" ref={editButtonRef} onClick={() => setOpen(true)}>Edit</button>
    </div>
    {open && <div className="constraint-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="constraint-sheet-backdrop" onClick={closeSheet}/>
      <div className="constraint-sheet-card">
        <div className="constraint-sheet-top">
          <button type="button" className="secondary-button" ref={closeButtonRef} onClick={closeSheet}>Close</button>
        </div>
        {body}
      </div>
    </div>}
  </div>;
}
