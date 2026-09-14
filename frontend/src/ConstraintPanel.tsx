import { useState } from 'react';
import { CircleAlert, X } from 'lucide-react';
import type { Preferences } from './types';

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

interface Props {
  preferences: Preferences;
  onChange: (next: Preferences) => void;
  onApply: () => void;
  busy?: boolean;
  /** Report re-rank vs Review setup before first generate. */
  mode: 'review' | 'report';
  /** Mobile: collapsed summary + Edit opens the sheet. */
  narrow?: boolean;
}

export function ConstraintPanel({ preferences, onChange, onApply, busy, mode, narrow }: Props) {
  const [open, setOpen] = useState(false);
  const [draftPriority, setDraftPriority] = useState('');
  const [draftMust, setDraftMust] = useState('');

  const empty = preferences.budget == null && !preferences.priorities.length && !preferences.must_haves.length
    && preferences.ownership_years === 3 && preferences.annual_mileage === 12000 && !preferences.location;

  const summaryBits = [
    preferences.budget != null ? `Budget ≤ $${preferences.budget.toLocaleString()}` : null,
    `${preferences.ownership_years} yr`,
    `${preferences.annual_mileage.toLocaleString()} mi/yr`,
    ...preferences.priorities.slice(0, 2),
    ...preferences.must_haves.slice(0, 2),
  ].filter(Boolean) as string[];

  const clearAll = () => onChange({
    budget: null, annual_mileage: 12000, ownership_years: 3, location: '', priorities: [], must_haves: [],
  });

  const body = <>
    <div className="constraint-head">
      <div>
        <p className="eyebrow">RE-RANK CONTROLS</p>
        <h3>Your constraints</h3>
      </div>
      <p className="muted constraint-lede">
        {mode === 'report'
          ? 'Adjust chips, then Apply to rebuild the cited comparison. This is not discovery chat.'
          : 'Optional. Facts on the left stay primary; these only steer the report when you generate.'}
      </p>
    </div>

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

    {empty && <div className="constraint-suggestions">
      <p className="constraint-label">Suggested</p>
      <div className="chip-row">
        {SUGGESTIONS.map(s => <button key={s.label} type="button" className="suggest-chip" onClick={() => onChange(s.apply(preferences))}>{s.label}</button>)}
      </div>
    </div>}

    <div className={`constraint-actions${narrow ? ' sticky' : ''}`}>
      <button type="button" className="primary-button" disabled={busy} onClick={() => { onApply(); setOpen(false); }}>
        {mode === 'report' ? 'Apply to report' : 'Use for report'}
      </button>
      <button type="button" className="text-button" disabled={busy} onClick={clearAll}>Clear all</button>
    </div>
    <p className="constraint-note"><CircleAlert size={13}/> We won’t invent fair-price or fit scores from these chips.</p>
  </>;

  if (!narrow) {
    return <aside className="constraint-panel panel">{body}</aside>;
  }

  return <div className="constraint-mobile">
    <div className="constraint-summary">
      <div>
        <p className="eyebrow">YOUR CONSTRAINTS</p>
        <p className="constraint-summary-text">{summaryBits.length ? summaryBits.join(' · ') : 'None set — using report defaults'}</p>
      </div>
      <button type="button" className="secondary-button" onClick={() => setOpen(true)}>Edit</button>
    </div>
    {open && <div className="constraint-sheet" role="dialog" aria-label="Your constraints">
      <div className="constraint-sheet-backdrop" onClick={() => setOpen(false)}/>
      <div className="constraint-sheet-card">{body}</div>
    </div>}
  </div>;
}
