import { ArrowRight, CircleAlert, LoaderCircle, Trash2 } from 'lucide-react';
import { msrpNeoVinKind, msrpOrigin } from './compare';
import { ConstraintPanel } from './ConstraintPanel';
import type { Candidate, Preferences } from './types';
import { carName, dateLabel, fieldOptions, hostOf, provenance, readableField, safeUrl, sourceLabel, unresolvedConflicts } from './utils';

type Edit = (id: string, field: keyof Candidate, value: string) => void;

const GROUPS: { title: string; fields: (keyof Candidate)[] }[] = [
  { title: 'Vehicle', fields: ['year', 'make', 'model', 'trim'] },
  { title: 'Specs', fields: ['transmission', 'engine', 'drivetrain', 'body', 'fuel_type'] },
  { title: 'Seller', fields: ['location', 'history'] },
];
const METHODS: Record<string, string> = {
  direct: 'Fetched from listing', search: 'Recovered via search', licensed: 'Licensed inventory',
  registry: 'VIN decode only', paste: 'Pasted text', synthetic: 'Synthetic example',
};
const CURRENCIES = ['USD', 'CAD', 'EUR', 'GBP', 'AUD', 'JPY'];

interface Attention { field: keyof Candidate; reason: string; conflict?: boolean }

// What the user should look at before comparing, most important first.
function attentionItems(c: Candidate): Attention[] {
  // Mileage keeps the seller's reading and is flagged only when another source reports a higher one.
  const items: Attention[] = unresolvedConflicts(c).map(field => ({ field: field as keyof Candidate, conflict: true,
    reason: field === 'mileage' && c.mileage !== null ? 'another source reports higher mileage' : 'sources disagree' }));
  const listed = new Set(items.map(item => item.field));
  for (const field of ['price', 'mileage', 'year', 'make', 'model'] as const) {
    if (c[field] === null && !listed.has(field)) items.push({ field, reason: 'not found' });
  }
  if (c.price !== null && (c.currency === 'UNK' || !c.currency)) items.push({ field: 'currency', reason: 'currency not confirmed' });
  if (c.mileage !== null && !c.evidence.mileage_unit) items.push({ field: 'mileage_unit', reason: 'unit not confirmed' });
  return items;
}

function Badge({ candidate, field }: { candidate: Candidate; field: string }) {
  const origin = provenance(candidate, field);
  return origin ? <span className={`origin origin-${origin.tone}`} title={origin.source}>{origin.label}</span> : null;
}

function FieldInput({ candidate, field, flagged, onEdit, wide }: { candidate: Candidate; field: keyof Candidate; flagged: boolean; onEdit: Edit; wide?: boolean }) {
  const value = candidate[field];
  const numeric = field === 'year';
  return <label className={`field${flagged ? ' flagged' : ''}${wide ? ' wide' : ''}`}>
    <span className="field-label">{readableField(field)} <Badge candidate={candidate} field={field}/></span>
    <input type={numeric ? 'number' : 'text'} value={(Array.isArray(value) ? value.join(', ') : value ?? '') as string | number}
           placeholder="Unknown" onChange={e => onEdit(candidate.id, field, e.target.value)}/>
  </label>;
}

function ReviewCard({ candidate, index, onEdit, onRemove }: { candidate: Candidate; index: number; onEdit: Edit; onRemove: () => void }) {
  const attention = attentionItems(candidate);
  // A VIN decode filled the MSRP and the buyer has not touched it yet.
  const decodedMsrp = candidate.msrp != null && !candidate.verified_fields.includes('msrp') && msrpOrigin(candidate) !== null;
  const flagged = new Set(attention.map(item => item.field));
  const link = safeUrl(candidate.source_url);
  const vin = candidate.evidence.vin?.value;
  const notes = [...new Set(candidate.warnings)].filter(w => !candidate.verified_fields.some(f => w.startsWith(`Conflicting ${f}:`)));
  const observations = candidate.observations ?? [];
  return <article className="review-card">
    <header className="review-card-head">
      <span className="candidate-index">0{index + 1}</span>
      <div className="review-title">
        <h3>{carName(candidate)}</h3>
        {candidate.trim && <p>{candidate.trim}</p>}
        <div className="vehicle-tags">
          <span className="tag">{link ? <a href={link} target="_blank" rel="noopener noreferrer">{sourceLabel(candidate)}</a> : sourceLabel(candidate)}</span>
          <span className="tag">{METHODS[candidate.retrieval_method ?? 'direct'] ?? readableField(candidate.retrieval_method ?? '')}</span>
          <span className="tag">{vin ? `VIN ${vin}` : 'VIN unknown'}</span>
        </div>
      </div>
      <button className="icon-button" title="Remove this car" aria-label={`Remove ${carName(candidate)}`} onClick={onRemove}><Trash2 size={16}/></button>
    </header>

    {attention.length > 0 && <div className="attention">
      <strong><CircleAlert size={15}/> {attention.length === 1 ? '1 thing' : `${attention.length} things`} to check</strong>
      <ul>{attention.map(item => {
        const options = item.conflict ? fieldOptions(candidate, item.field) : [];
        return <li key={item.field}>
          <span>{readableField(item.field)} — {item.reason}</span>
          {options.length > 0 && <span className="choices">{options.map(option =>
            <button key={option.value} className="choice" title={`Use the value reported by ${option.hosts.join(', ')}`}
                    onClick={() => onEdit(candidate.id, item.field, option.value)}>
              {/^\d+(\.\d+)?$/.test(option.value) ? Number(option.value).toLocaleString() : option.value}<small>{option.hosts.join(', ')}</small>
            </button>)}</span>}
        </li>;
      })}</ul>
    </div>}

    <section className="field-group">
      <h4>Price &amp; mileage</h4>
      <div className="field-row wide-fields">
        <label className={`field${flagged.has('price') ? ' flagged' : ''}`}>
          <span className="field-label">Asking price <Badge candidate={candidate} field="price"/></span>
          <span className="joined">
            <input type="number" value={candidate.price ?? ''} placeholder="Unknown" onChange={e => onEdit(candidate.id, 'price', e.target.value)}/>
            <select aria-label="Currency" className={flagged.has('currency') ? 'flagged' : ''}
                    value={candidate.currency === 'UNK' || (unresolvedConflicts(candidate).includes('currency')) ? '' : candidate.currency}
                    onChange={e => onEdit(candidate.id, 'currency', e.target.value)}>
              <option value="" disabled>Currency</option>
              {[...new Set([candidate.currency, ...CURRENCIES])].filter(c => c && c !== 'UNK').map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </span>
          {candidate.price === null && candidate.evidence.last_listed_price && <span className="field-hint" title={candidate.evidence.last_listed_price.source}>
            No current price found · last listed {candidate.evidence.last_listed_price.value}</span>}
        </label>
        <label className={`field${flagged.has('mileage') ? ' flagged' : ''}`}>
          <span className="field-label">Mileage <Badge candidate={candidate} field="mileage"/></span>
          <span className="joined">
            <input type="number" value={candidate.mileage ?? ''} placeholder="Unknown" onChange={e => onEdit(candidate.id, 'mileage', e.target.value)}/>
            <select aria-label="Mileage unit" className={flagged.has('mileage_unit') ? 'flagged' : ''}
                    value={unresolvedConflicts(candidate).includes('mileage_unit') ? '' : candidate.mileage_unit}
                    onChange={e => onEdit(candidate.id, 'mileage_unit', e.target.value)}>
              <option value="" disabled>Unit</option><option value="mi">mi</option><option value="km">km</option>
            </select>
          </span>
        </label>
        <label className="field">
          <span className="field-label">Original MSRP <Badge candidate={candidate} field="msrp"/>
            <span className="field-optional">{msrpOrigin(candidate) === 'Factory MSRP · NeoVIN' ? 'Factory MSRP · NeoVIN' : (msrpOrigin(candidate) ?? 'you enter')}</span></span>
          <input type="number" value={candidate.msrp ?? ''} placeholder="Optional — never invented"
                 onChange={e => onEdit(candidate.id, 'msrp', e.target.value)}/>
          <span className="field-hint">{decodedMsrp
            ? <>{msrpNeoVinKind(candidate) ?? 'VIN decode'}. Factory sticker as built, not the listing price. Change it if you know better.</>
            : 'Used for % of original MSRP in the report. Leave blank if you do not know it.'}</span>
        </label>
      </div>
    </section>
    {GROUPS.map(group => <section className="field-group" key={group.title}>
      <h4>{group.title}</h4>
      <div className="field-row">{group.fields.map(field =>
        <FieldInput key={field} candidate={candidate} field={field} flagged={flagged.has(field)} onEdit={onEdit} wide={field === 'history'}/>)}</div>
    </section>)}

    {observations.length > 0 && <details className="review-more">
      <summary>Where the values came from ({observations.length})</summary>
      <SourceTable candidate={candidate}/>
    </details>}
    {notes.length > 0 && <details className="review-more">
      <summary>Notes ({notes.length})</summary>
      <ul className="notes">{notes.map(note => <li key={note}>{note}</li>)}</ul>
    </details>}
  </article>;
}

export function SourceTable({ candidate }: { candidate: Candidate }) {
  return <div className="table-scroll"><table className="source-table">
    <thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Observed</th></tr></thead>
    <tbody>{(candidate.observations ?? []).map((o, i) => {
      const url = safeUrl(o.source_url);
      return <tr key={i}>
        <td>{readableField(o.field)}</td>
        <td>{/^\d+\.0$/.test(o.value) ? Number(o.value).toLocaleString() : o.value}</td>
        <td>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{o.method === 'registry' ? 'NHTSA VIN decode' : hostOf(url)}</a> : o.method}</td>
        <td>{o.observed_at ? dateLabel(o.observed_at) : 'Date unknown'}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

interface ReviewProps {
  candidates: Candidate[];
  preferences: Preferences;
  setPreferences: (p: Preferences) => void;
  updateCandidate: Edit; removeCandidate: (id: string) => void; generateReport: () => void; onAddMore: () => void; busy: boolean;
  onCancelCompare?: () => void;
  compareError?: string | null;
  buildSlow?: boolean;
  narrow?: boolean;
}

export function Review({ candidates, preferences, setPreferences, updateCandidate, removeCandidate, generateReport, onCancelCompare, compareError, buildSlow, onAddMore, busy, narrow }: ReviewProps) {
  const open = candidates.reduce((total, c) => total + attentionItems(c).length, 0);
  const panel = <ConstraintPanel mode="review" preferences={preferences} onChange={setPreferences} onApply={generateReport} busy={busy} narrow={narrow}/>;
  return <section className="workspace review-layout">
    {narrow && panel}
    <div className="panel main-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">CHECK THE INPUTS</p><h2>Review each car</h2></div>
        <span className="count-badge">{candidates.length} of 3</span>
      </div>
      <p className="muted">Highlighted fields need a decision. Badges show where each value came from; your edits are marked “You”.</p>
      {compareError && !busy && <div className="compare-empty" role="alert">
        <strong><CircleAlert size={16}/> Report didn’t finish</strong>
        <p>{compareError}</p>
        <div className="compare-empty-actions">
          <button type="button" className="primary-button" onClick={generateReport} disabled={candidates.length < 2}>Retry</button>
        </div>
      </div>}
      {busy && <div className="compare-building" role="status">
        <LoaderCircle className="spin" size={16}/>
        <div>
          <strong>{buildSlow ? 'Still building the report…' : 'Building report…'}</strong>
          <p>{buildSlow
            ? 'This is taking longer than usual. You can cancel and retry — your draft stays intact.'
            : 'Comparing reviewed details. This can take up to about a minute.'}</p>
        </div>
        {onCancelCompare && <button type="button" className="secondary-button" onClick={onCancelCompare}>Cancel</button>}
      </div>}
      <div className="candidate-list">{candidates.map((candidate, i) =>
        <ReviewCard key={candidate.id} candidate={candidate} index={i} onEdit={updateCandidate} onRemove={() => removeCandidate(candidate.id)}/>)}</div>
      {candidates.length < 3 && <button className="add-button" onClick={onAddMore}>+ Add {candidates.length < 2 ? 'another' : 'a third'} car</button>}
      <div className="generate-row">
        <p className="muted">{candidates.length < 2 ? 'Add at least two cars to compare.'
          : open ? `${open} highlighted item${open === 1 ? '' : 's'} still open — the report will treat them as unknown.` : 'All key details are set.'}</p>
        <button className="primary-button report-button" onClick={generateReport} disabled={busy || candidates.length < 2}>
          {busy ? <><LoaderCircle className="spin" size={17}/> Building report…</> : <>Generate comparison <ArrowRight size={17}/></>}
        </button>
      </div>
    </div>
    {!narrow && panel}
  </section>;
}
