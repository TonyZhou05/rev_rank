import { useEffect, useId, useRef, useState } from 'react';
import { CircleAlert, X } from 'lucide-react';
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
  const list = (xs: string[]) => [...xs].map(x => x.trim()).filter(Boolean).sort().join('\0');
  return a.budget === b.budget
    && a.annual_mileage === b.annual_mileage
    && a.ownership_years === b.ownership_years
    && (a.location || '') === (b.location || '')
    && list(a.priorities) === list(b.priorities)
    && list(a.must_haves) === list(b.must_haves);
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
  const titleId = useId();
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const atDefaults = preferencesEqual(preferences, defaultPreferences);
  const dirty = mode === 'report' && applied != null && !preferencesEqual(preferences, applied);

  const customBits = [
    preferences.budget != null ? `Budget ≤ $${preferences.budget.toLocaleString()}` : null,
    preferences.location ? preferences.location : null,
    ...preferences.priorities.slice(0, 2),
    ...preferences.must_haves.slice(0, 2),
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
