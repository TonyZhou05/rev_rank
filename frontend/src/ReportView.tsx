import { useEffect, useState, type ReactNode } from 'react';
import { Check, CircleAlert, ExternalLink, LoaderCircle, Sparkles } from 'lucide-react';
import { allSame, comparable, constraintMetrics, constraintTone, delta, isCrossModel, metric, mileageValue, msrpNeoVinKind, msrpOrigin, msrpPctDelta, msrpSourceNote, msrpValue, mustHaveMetrics, numberIn, pctOfMsrp, pctOfMsrpText, priceValue, sharedAnnual, tradeOff, type DeltaKind } from './compare';
import { ConstraintPanel } from './ConstraintPanel';
import { SourceTable } from './Review';
import type { AIAnalysis, Candidate, Claim, DealerInfo, DealerSignal, DealerSignals, NHTSASafetyData, Preferences, Report, SourceRef } from './types';
import { carName, dateLabel, hostOf, money, safeUrl, unresolvedConflicts } from './utils';

interface Row {
  label: string;
  hint?: string;
  // Cell text per car (index into report.candidates); also what "differences only" compares.
  text: (c: Candidate, i: number) => string;
  cell?: (c: Candidate, i: number) => ReactNode;
  rank?: (c: Candidate, i: number) => number | null;
  best?: 'min' | 'max';
  delta?: DeltaKind;
  always?: boolean;
}

const priceText = (c: Candidate) => c.price === null ? (unresolvedConflicts(c).includes('price') ? 'Sources disagree'
    : c.evidence.last_listed_price ? `Unknown (last listed ${c.evidence.last_listed_price.value})` : 'Unknown')
  : c.currency === 'UNK' ? `${c.price.toLocaleString()} (currency?)` : money(c.price, c.currency);
const mileageText = (c: Candidate) => c.mileage === null ? (unresolvedConflicts(c).includes('mileage') ? 'Sources disagree' : 'Unknown')
  : `${c.mileage.toLocaleString()} ${c.mileage_unit}`;
const text = (value: string | number | null | undefined) => value === null || value === undefined || value === '' ? '—' : String(value);

function rowsFor(report: Report, bench: Candidate, crossModel: boolean): Row[] {
  const odometer = metric(report, 'Projected odometer after');
  const budget = metric(report, 'Budget headroom');
  const annual = sharedAnnual(report);
  const trade = (c: Candidate) => c.id === bench.id ? null : tradeOff(c, bench, annual);
  const bothMsrp = msrpValue(bench) !== null && report.candidates.every(c => c.id === bench.id || msrpValue(c) !== null);
  const rows: Row[] = [
    { label: 'Asking price', text: priceText, rank: priceValue, best: 'min', delta: 'money' },
    {
      label: '% of original MSRP', always: true, best: 'min',
      hint: 'you entered, or decoded from the VIN',
      text: (c, i) => {
        const fromMetric = metric(report, '% of original MSRP')?.values[i];
        if (fromMetric && fromMetric !== 'N/A' && fromMetric !== 'MSRP not confirmed') return `${fromMetric} of original MSRP (${msrpSourceNote(c) ?? 'sourced'})`;
        if (fromMetric === 'MSRP not confirmed') return 'MSRP not confirmed';
        return pctOfMsrpText(c) ?? 'MSRP not entered — add it on Review';
      },
      rank: (c, i) => {
        const fromMetric = metric(report, '% of original MSRP')?.values[i];
        if (fromMetric && /\d/.test(fromMetric)) return numberIn(fromMetric);
        return pctOfMsrp(c);
      },
      cell: (c, i) => {
        const fromMetric = metric(report, '% of original MSRP')?.values[i];
        if (fromMetric && fromMetric !== 'N/A' && fromMetric !== 'MSRP not confirmed') {
          return <span className="msrp-pct">{fromMetric} of original MSRP ({msrpSourceNote(c) ?? 'sourced'})</span>;
        }
        if (fromMetric === 'MSRP not confirmed') {
          return <span className="muted-cell msrp-cta">MSRP present but not sourced — confirm it on Review</span>;
        }
        const t = pctOfMsrpText(c);
        if (t) return <span className="msrp-pct">{t}</span>;
        return <span className="muted-cell msrp-cta">No MSRP yet — go back to Review and enter original MSRP (optional) to unlock % of sticker</span>;
      },
    },
    { label: 'Mileage', text: mileageText, rank: mileageValue, best: 'min', delta: 'distance' },
    {
      label: 'Days on market', best: 'min', always: false,
      hint: 'from licensed inventory when available',
      text: c => c.dom == null && c.dom_active == null ? 'Unknown' : [
        c.dom != null ? `${c.dom} total` : null,
        c.dom_active != null ? `${c.dom_active} active` : null,
      ].filter(Boolean).join(' · '),
      rank: c => c.dom_active ?? c.dom ?? null,
      cell: c => {
        if (c.dom == null && c.dom_active == null) return <span className="muted-cell">Unknown</span>;
        return <span>
          {c.dom != null && <>{c.dom} total</>}
          {c.dom != null && c.dom_active != null && ' · '}
          {c.dom_active != null && <>{c.dom_active} active</>}
          {c.first_seen_at && <small className="dom-first">First seen {dateLabel(c.first_seen_at)}</small>}
        </span>;
      },
    },
  ];
  if (odometer) rows.push({
    label: 'Mileage when you sell', delta: 'distance', best: 'min',
    hint: `+${report.preferences.annual_mileage.toLocaleString()} a year for ${report.preferences.ownership_years} yr`,
    text: (_, i) => odometer.values[i] ?? 'Unknown', rank: (_, i) => numberIn(odometer.values[i]),
  });
  // Same-model: lead with $ / miles trade-off. Cross-model with MSRP: lead with %-of-MSRP; $ / miles stays secondary.
  if (!crossModel) {
    rows.push({
      label: 'Trade-off', hint: `vs ${carName(bench)}`, always: true,
      text: c => c.id === bench.id ? 'Benchmark' : trade(c)?.text ?? 'Needs price and mileage in the same units',
      cell: c => {
        if (c.id === bench.id) return <span className="muted-cell">Benchmark</span>;
        const t = trade(c);
        return t ? <span className={`tradeoff ${t.tone}`}>{t.text}</span> : <span className="muted-cell">Needs price and mileage in the same units</span>;
      },
    });
  } else if (bothMsrp) {
    rows.push({
      label: 'Value vs MSRP', hint: `vs ${carName(bench)} · cross-model`, always: true,
      text: c => {
        if (c.id === bench.id) return 'Benchmark';
        const d = msrpPctDelta(c, bench);
        return d ? d.text : 'Same % of MSRP';
      },
      cell: c => {
        if (c.id === bench.id) return <span className="muted-cell">Benchmark</span>;
        const d = msrpPctDelta(c, bench);
        return d ? <span className={`tradeoff ${d.tone}`}>{d.text} of asking vs original MSRP</span>
          : <span className="muted-cell">Same % of MSRP</span>;
      },
    });
    rows.push({
      label: 'Price / mileage (secondary)', hint: `vs ${carName(bench)} · not apples-to-apples across models`, always: true,
      text: c => c.id === bench.id ? 'Benchmark' : trade(c)?.text ?? 'Needs price and mileage in the same units',
      cell: c => {
        if (c.id === bench.id) return <span className="muted-cell">Benchmark</span>;
        const t = trade(c);
        return t ? <span className={`tradeoff secondary ${t.tone}`}>{t.text}</span>
          : <span className="muted-cell">Needs price and mileage in the same units</span>;
      },
    });
  } else {
    rows.push({
      label: 'Price / mileage (secondary)', hint: 'Enter original MSRP on Review for a fairer cross-model % comparison', always: true,
      text: c => c.id === bench.id ? 'Benchmark' : trade(c)?.text ?? 'Needs price and mileage in the same units',
      cell: c => {
        if (c.id === bench.id) return <span className="muted-cell">Benchmark</span>;
        const t = trade(c);
        return t ? <span className={`tradeoff secondary ${t.tone}`}>{t.text}</span>
          : <span className="muted-cell">Needs price and mileage in the same units</span>;
      },
    });
  }
  rows.push(
    { label: 'Model year', text: c => text(c.year), rank: c => c.year, best: 'max', delta: 'year' },
    { label: 'Trim', text: c => text(c.trim) },
    { label: 'Transmission', text: c => text(c.transmission) },
    { label: 'Engine', text: c => text(c.engine) },
    { label: 'Drivetrain', text: c => text(c.drivetrain) },
    { label: 'Body', text: c => text(c.body) },
    { label: 'Location', text: c => text(c.location) },
  );
  for (const m of mustHaveMetrics(report)) rows.push({
    label: m.label, text: (_, i) => m.values[i] ?? 'not established',
    // "Not established" means the listing doesn't say; it is never shown as "no".
    cell: (_, i) => m.values[i] === 'listed' ? <span className="req listed">Listed</span> : <span className="req unknown">Not mentioned</span>,
  });
  // Odometer ceiling, gearbox and rule-outs, as the server read them against reviewed evidence.
  for (const m of constraintMetrics(report)) rows.push({
    label: m.label, text: (_, i) => m.values[i] ?? 'unknown',
    cell: (_, i) => <span className={`req ${constraintTone(m.values[i])}`}>{m.values[i] ?? 'unknown'}</span>,
  });
  const fit = metric(report, 'Constraint fit');
  if (fit) rows.push({
    label: 'Your constraints', always: true, hint: 'met · open · conflicting',
    text: (_, i) => fit.values[i] ?? '—',
  });
  if (budget && report.preferences.budget !== null) rows.push({ label: 'Budget headroom', text: (_, i) => budget.values[i] ?? '—' });
  return rows;
}

// The "best" marker only appears when every car has a comparable value (same currency / unit).
function bestIndex(cars: Candidate[], row: Row): number | null {
  if (!row.rank || !row.best || cars.length < 2) return null;
  const values = cars.map((c, i) => row.rank!(c, i));
  if (values.some(v => v === null)) return null;
  if (row.delta && row.delta !== 'year' && cars.some(c => !comparable(row.delta!, c, cars[0]))) return null;
  const target = row.best === 'min' ? Math.min(...(values as number[])) : Math.max(...(values as number[]));
  return values.filter(v => v === target).length === 1 ? values.indexOf(target) : null;
}

function ValueCards({ cars }: { cars: Candidate[] }) {
  return <div className="value-cards">
    {cars.map(c => {
      const pct = pctOfMsrpText(c);
      const msrp = msrpValue(c);
      return <article className="value-card" key={c.id}>
        <h4>{carName(c)}</h4>
        <p className="value-price">{priceText(c)}</p>
        <p className={pct ? 'value-msrp' : 'value-msrp muted-cta'}>{pct ? pct : 'No MSRP yet — add original MSRP on Review to see % of sticker'}</p>
        {msrp !== null && <p className="value-msrp-raw">Original MSRP {money(msrp, c.currency)}
          <small>{msrpOrigin(c)}{msrpNeoVinKind(c) ? ` · ${msrpNeoVinKind(c)}` : ''}</small></p>}
        <p className="value-miles">{mileageText(c)}</p>
        {(c.make || c.model) && <p className="value-model">{[c.year, c.make, c.model, c.trim].filter(Boolean).join(' ')}</p>}
      </article>;
    })}
  </div>;
}

// Below this width a third and fourth column crowd the row labels off the screen, so the table
// shows the benchmark plus one comparison car. The `compare-narrow` class carries the same
// decision into CSS, so the breakpoint lives here only.
const NARROW_COMPARE = '(max-width: 768px)';

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

function CompareTable({ report, activeId, onActive }: {
  report: Report; activeId?: string; onActive?: (id: string) => void;
}) {
  const cars = report.candidates;
  const crossModel = report.cross_model ?? isCrossModel(cars);
  const narrow = useNarrowViewport(NARROW_COMPARE);
  const [benchId, setBenchId] = useState(cars[0]?.id);
  const [diffOnly, setDiffOnly] = useState(true);
  const bench = cars.find(c => c.id === benchId) ?? cars[0];
  const others = cars.filter(c => c.id !== bench.id);
  // The car shown next to the benchmark on a narrow screen. It is the report's shared active car, so
  // picking one here also moves the per-car sections below to that car. Choosing it as the benchmark
  // drops it out of `others`, and the first remaining car takes over.
  const focus = others.find(c => c.id === activeId) ?? others[0] ?? null;
  // The benchmark leads; the others keep their order. Indexes stay tied to report.candidates.
  const order = [cars.indexOf(bench), ...cars.map((_, i) => i).filter(i => cars[i] !== bench)];
  const columns = narrow && focus ? [order[0], cars.indexOf(focus)] : order;
  const benchColumn = columns[0];
  const rows = rowsFor(report, bench, crossModel);
  // "Differences only" hides rows that read the same across the columns on screen.
  const shown = rows.filter(row => row.always || !diffOnly || !allSame(columns.map(i => row.text(cars[i], i))));
  const hidden = rows.length - shown.length;
  // A picker only earns its space when more than one car can take the comparison column.
  const pickable = narrow && others.length > 1 ? focus : null;
  return <div className={narrow ? 'compare compare-narrow' : 'compare'}>
    {crossModel && <>
      <p className="cross-model-note" role="note">
        <CircleAlert size={15}/>
        <span>These cars are different models — sticker prices are not apples-to-apples. Per-car value first; across-shortlist fit below.</span>
      </p>
      <div className="compare-section-label">Per-car value</div>
      <ValueCards cars={cars}/>
      <div className="compare-section-label">Across the shortlist</div>
    </>}
    <div className="compare-controls">
      <span className="control-label">Compare against</span>
      <div className="segmented" role="radiogroup" aria-label="Benchmark car">
        {cars.map(c => <button key={c.id} type="button" role="radio" aria-checked={c.id === bench.id} className={c.id === bench.id ? 'on' : ''}
          onClick={() => setBenchId(c.id)}>{carName(c)}</button>)}
      </div>
      <label className="diff-toggle"><input type="checkbox" checked={diffOnly} onChange={e => setDiffOnly(e.target.checked)}/> Differences only</label>
    </div>
    {pickable && <div className="compare-controls compare-focus">
      <span className="control-label" id="compare-focus-label">Show one car against {carName(bench)}</span>
      <div className="segmented" role="radiogroup" aria-labelledby="compare-focus-label">
        {others.map(c => <button key={c.id} type="button" role="radio" aria-checked={c.id === pickable.id} className={c.id === pickable.id ? 'on' : ''}
          onClick={() => onActive?.(c.id)}>{carName(c)}</button>)}
      </div>
    </div>}
    <div className="table-scroll"><table className="compare-table">
      <thead><tr><th/>{columns.map(i => <th key={cars[i].id} className={i === benchColumn ? 'bench-col' : ''}>
        {carName(cars[i])}<small>{i === benchColumn ? 'benchmark' : 'vs benchmark'}</small></th>)}</tr></thead>
      <tbody>
        {shown.map(row => {
          // The marker still ranks the whole shortlist; it is simply not drawn when the winning
          // car is off screen, so a hidden car is never implied to be second best.
          const best = bestIndex(cars, row);
          return <tr key={row.label}>
            <th scope="row">{row.label}{row.hint && <small>{row.hint}</small>}</th>
            {columns.map(i => {
              const c = cars[i];
              const d = row.delta && i !== benchColumn && row.rank ? delta(row.delta, row.rank(c, i), row.rank(bench, benchColumn), c, bench) : null;
              const msrpD = row.label.startsWith('% of original') && i !== benchColumn ? msrpPctDelta(c, bench) : null;
              return <td key={c.id} className={[i === best ? 'best' : '', i === benchColumn ? 'bench-col' : ''].join(' ').trim()}>
                {row.cell ? row.cell(c, i) : row.text(c, i)}
                {d && <span className={`delta ${d.tone}`}>{d.text}</span>}
                {msrpD && <span className={`delta ${msrpD.tone}`}>{msrpD.text}</span>}
                {i === best && <span className="best-tag">{row.best === 'min' ? 'lowest' : 'newest'}</span>}
              </td>;
            })}
          </tr>;
        })}
      </tbody>
    </table></div>
    <p className="compare-note">
      {pickable && <>One comparison car at a time on a small screen: {carName(pickable)} against {carName(bench)}. Switch cars above; “lowest” and “newest” still rank all {cars.length} cars. </>}
      {hidden > 0 && <>{hidden} {hidden === 1 ? 'row is' : 'rows are'} the same for {pickable ? 'both shown cars' : 'every car'} and hidden. </>}
      Green is better for you and amber is worse, compared with the benchmark.
      {crossModel
        ? ' Across models, prefer % of the MSRP you entered over raw asking-price gaps. Trade-offs use asking prices, not out-the-door prices.'
        : ' Trade-offs use asking prices, not out-the-door prices.'}
    </p>
  </div>;
}



function nhtsaFor(report: Report, c: Candidate): NHTSASafetyData | null {
  const raw = c.nhtsa_safety ?? report.nhtsa_data?.[c.id] ?? null;
  return raw ?? null;
}

function nhtsaScope(data: NHTSASafetyData) {
  return data.scope || data.scope_label || 'Model-Year Safety Data (not VIN-specific)';
}
function nhtsaRecalls(data: NHTSASafetyData) {
  return data.recalls_count ?? data.recall_count ?? data.recalls?.length ?? 0;
}
function nhtsaComplaints(data: NHTSASafetyData) {
  return data.complaints_count ?? data.complaint_count ?? data.complaints?.length ?? 0;
}
function nhtsaOverall(data: NHTSASafetyData) {
  return data.overall_rating ?? data.rating?.overall_rating ?? null;
}
// Last-resort target: NHTSA's own recall/complaint search. Reached only when the backend could not
// build a model-year link (missing year, make or model) — never a /vehicle/{VehicleId} URL, which 404s.
const NHTSA_LOOKUP = 'https://www.nhtsa.gov/recalls';
function nhtsaRecallsHub(data: NHTSASafetyData) {
  return safeUrl(data.recalls_url ?? null) ?? safeUrl(data.recalls?.[0]?.url ?? null) ?? NHTSA_LOOKUP;
}
function nhtsaComplaintsHub(data: NHTSASafetyData) {
  return safeUrl(data.complaints_url ?? null) ?? NHTSA_LOOKUP;
}
function NhtsaLink({ href, children }: { href: string; children: ReactNode }) {
  return <a className="nhtsa-link" href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

function NhtsaSection({ report }: { report: Report }) {
  const cars = report.candidates;
  const blocks = cars.map(c => ({ c, data: nhtsaFor(report, c) }));
  if (!blocks.some(b => b.data)) return null;
  return <section className="report-section nhtsa-section">
    <h3>Model-year safety</h3>
    <p className="nhtsa-scope"><CircleAlert size={14}/> Model-Year Safety Data (not VIN-specific). Counts and ratings apply to the model year, not this vehicle’s VIN.</p>
    <div className="nhtsa-grid">
      {blocks.map(({ c, data }) => <article className="nhtsa-card" key={c.id}>
        <h4>{carName(c)}</h4>
        {!data ? <p className="muted-cell">No model-year NHTSA block for this car.</p> : <>
          <p className="nhtsa-label">{nhtsaScope(data)}</p>
          <p className="nhtsa-counts">
            <NhtsaLink href={nhtsaRecallsHub(data)}><strong>{nhtsaRecalls(data)}</strong> recalls</NhtsaLink>
            {' · '}
            <NhtsaLink href={nhtsaComplaintsHub(data)}><strong>{nhtsaComplaints(data)}</strong> complaints</NhtsaLink>
            {nhtsaOverall(data) != null && <> · NHTSA overall {nhtsaOverall(data)}</>}
          </p>
          {!!data.recalls?.[0] && <p className="nhtsa-top">Top recall component: {data.recalls[0].component}</p>}
          {!!data.complaints?.[0] && <p className="nhtsa-top">Most-noted complaint area: {data.complaints[0].component}</p>}
          {!!(data.recalls?.length || data.complaints?.length) && <details className="review-more">
            <summary>Recalls &amp; complaints detail</summary>
            <ul className="nhtsa-list">
              {(data.recalls ?? []).slice(0, 5).map(r => <li key={r.campaign_number}>
                <strong>{r.component || 'Recall'}</strong> — {r.summary}{' '}
                <NhtsaLink href={safeUrl(r.url ?? null) ?? nhtsaRecallsHub(data)}>Recall {r.campaign_number} on NHTSA</NhtsaLink>
              </li>)}
              {/* NHTSA has no per-ODI permalink, so complaint rows land on the model-year complaints tab. */}
              {(data.complaints ?? []).slice(0, 5).map(r => <li key={r.odi_number}>
                <strong>{r.component || 'Complaint'}</strong> — {r.summary}{' '}
                <NhtsaLink href={safeUrl(r.url ?? null) ?? nhtsaComplaintsHub(data)}>Complaint {r.odi_number} on NHTSA</NhtsaLink>
              </li>)}
            </ul>
          </details>}
        </>}
      </article>)}
    </div>
  </section>;
}

// A citation has to be readable without a click and reachable with one. Hovering names the
// evidence; choosing it opens the source list, because an anchor into a collapsed <details> used
// to scroll to something still hidden.
function Cites({ claim, index, sources, onPick }: {
  claim: Claim; index: Map<string, number>; sources: Map<string, SourceRef>; onPick: (id: string) => void;
}) {
  const shown = claim.citations.filter(id => index.has(id) && sources.has(id));
  // A claim only reaches the page with citations, so an empty row means the source list lost them.
  // Say that rather than letting the sentence read as if nobody asked where it came from.
  if (!shown.length) {
    return <span className="cite missing"
      title="This statement was cited during the analysis, but its source is not in the list below.">no source</span>;
  }
  return <>{shown.map(id => {
    const number = index.get(id) as number;
    const source = sources.get(id) as SourceRef;
    const summary = `${source.label}${source.detail ? ` — ${source.detail}` : ''}`;
    return <button key={id} type="button" className="cite" title={summary}
      aria-label={`Source ${number}: ${summary}`} onClick={() => onPick(id)}>{number}</button>;
  })}</>;
}

function FlagList({ tone, label, claims, cites }: {
  tone: 'green' | 'red'; label: string; claims: Claim[]; cites: (claim: Claim) => ReactNode;
}) {
  if (!claims.length) return null;
  const Icon = tone === 'green' ? Check : CircleAlert;
  return <div className={`flag-group ${tone}`}>
    <p className="flag-head"><Icon size={13}/> {label} <span>{claims.length}</span></p>
    <ul>{claims.map((claim, i) => <li key={i}><span>{claim.text} {cites(claim)}</span></li>)}</ul>
  </div>;
}

// One caveat carried by the whole Dealer block. It is deliberately the first thing the section says:
// a dealer's rating, address or phone is about the business, and says nothing about this car.
const DEALER_CAVEAT = 'About the dealer, not this VIN.';

// A dialable string only; the reported text ("(512) 555-0100 ext 2") stays as the visible label.
function dialable(phone: string): string | null {
  const digits = phone.replace(/[^\d+]/g, '');
  return digits.replace(/\D/g, '').length >= 7 ? `tel:${digits}` : null;
}

function DealerRow({ label, children }: { label: string; children: ReactNode }) {
  return <p className="dealer-row"><span className="dealer-label">{label}</span><span>{children}</span></p>;
}

// What kind of page an excerpt came from, and how its own wording reads. Both are shown, because
// "a state regulator concluded something" and "somebody alleged something" are different facts.
const SIGNAL_KINDS: Record<string, string> = { official: 'Official page', news: 'Dated article' };
const SIGNAL_NATURES: Record<string, string> = {
  action: 'Concluded action', allegation: 'Allegation', unclear: 'Unclear from the excerpt',
};

// A dealer flag is only ever a reading of the excerpts listed under it, so it carries its own
// attribution: the numbered chips point into that card's excerpt list, and under the sentence sits
// the quote, source, date and link for each excerpt it used. A reader never has to take the flag on
// trust or go hunting for what it was built from.
function SignalCites({ claim, index, byId }: {
  claim: Claim; index: Map<string, number>; byId: Map<string, DealerSignal>;
}) {
  const shown = claim.citations.filter(id => index.has(id) && byId.has(id));
  if (!shown.length) return <span className="cite missing" title="The excerpt behind this statement is not listed.">no source</span>;
  return <>
    {shown.map(id => <span key={id} className="cite static" title={`Excerpt ${index.get(id)} below`}>{index.get(id)}</span>)}
    <span className="dealer-flag-sources">
      {shown.map(id => {
        const signal = byId.get(id) as DealerSignal;
        const url = safeUrl(signal.url);
        const quote = signal.excerpt.length > 150 ? `${signal.excerpt.slice(0, 150)}…` : signal.excerpt;
        return <span className="dealer-flag-source" key={id}>
          <span className="dealer-flag-quote" title={signal.excerpt}>“{quote}”</span>
          <span className="dealer-signal-meta">
            {signal.label || signal.host} · {signal.host} · {signal.published || 'undated'} ·{' '}
            {url
              ? <a className="dealer-link" href={url} target="_blank" rel="noopener noreferrer">source</a>
              : 'no usable link'}
            {' · '}{SIGNAL_NATURES[signal.nature ?? 'unclear']}
          </span>
        </span>;
      })}
    </span>
  </>;
}

function DealerFlagBlock({ signals }: { signals: DealerSignals | null | undefined }) {
  // Nothing to interpret, or the operator has not turned the pass on: say which, and stop there.
  if (!signals || signals.status === 'disabled' || (!signals.signals?.length && !signals.green?.length && !signals.red?.length)) {
    // An empty search is reported as an empty search. It is never rendered as a clean dealer.
    const searched = Boolean(signals && signals.status !== 'disabled' && signals.searches > 0);
    return <div className="dealer-flags">
      <span className="dealer-flags-label">
        Dealer green/red flags · {searched ? 'no official/news flags found' : signals ? 'not available' : 'coming'}
      </span>
      <p>{signals?.message
        || 'Coming — we won’t invent a dealer score or cite chips yet. Nothing here is read from review sites, and this is never a VIN vehicle flag.'}</p>
    </div>;
  }
  const list = signals.signals ?? [];
  const index = new Map(list.map((s, i) => [s.id, i + 1]));
  const byId = new Map(list.map(s => [s.id, s]));
  const cites = (claim: Claim) => <SignalCites claim={claim} index={index} byId={byId}/>;
  const green = signals.green ?? [];
  const red = signals.red ?? [];
  return <div className="dealer-flags dealer-flags-live">
    <span className="dealer-flags-label">Dealer green/red flags · about the business</span>
    {green.length || red.length
      ? <>
          <FlagList tone="green" label="Dealer green flags" claims={green} cites={cites}/>
          <FlagList tone="red" label="Dealer red flags" claims={red} cites={cites}/>
        </>
      : <p>{signals.message || 'No statement passed the citation checks, so none is shown.'}</p>}
    {list.length > 0 && <details className="review-more dealer-signal-list">
      <summary>What we found ({list.length}) — search excerpts, not verified</summary>
      <ol>
        {list.map((s, i) => {
          const url = safeUrl(s.url);
          const nature = s.nature ?? 'unclear';
          return <li key={s.id} id={`dealer-signal-${i + 1}`}>
            <span className="dealer-signal-kind">
              {SIGNAL_KINDS[s.category] ?? s.category}
              <span className={`dealer-nature ${nature}`}>{SIGNAL_NATURES[nature]}</span>
            </span>
            {url ? <a className="dealer-link" href={url} target="_blank" rel="noopener noreferrer">{s.label || s.host}</a> : (s.label || s.host)}
            <span className="dealer-signal-meta">{s.host}{s.published ? ` · ${s.published}` : ' · undated'}</span>
            <span className="dealer-signal-excerpt">“{s.excerpt}”</span>
          </li>;
        })}
      </ol>
    </details>}
    {(signals.caveats ?? []).length > 0 && <ul className="dealer-notes">
      {(signals.caveats ?? []).map(caveat => <li key={caveat}>{caveat}</li>)}
    </ul>}
    <p className="dealer-signal-meta">
      {signals.searches} dealer search{signals.searches === 1 ? '' : 'es'}
      {signals.credits ? ` · ${signals.credits} provider credit${signals.credits === 1 ? '' : 's'}` : ''}
      {signals.model ? ` · ${signals.model}` : ''}
    </p>
  </div>;
}

function DealerCard({ car, dealer, signals }: {
  car: Candidate; dealer: DealerInfo | null | undefined; signals?: DealerSignals | null;
}) {
  const website = safeUrl(dealer?.website ?? null);
  const maps = safeUrl(dealer?.maps_url ?? null);
  const listing = safeUrl(dealer?.vdp_url ?? null);
  const phone = dealer?.phone ?? null;
  const links = (dealer?.links ?? []).filter(link => safeUrl(link.url));
  // The section-level caveat already says this, so the note that repeats it is not shown twice.
  const notes = (dealer?.notes ?? []).filter(note => !/not this VIN/i.test(note));
  const identified = Boolean(dealer && (dealer.name || dealer.address || website || phone));
  return <article className="dealer-card">
    <h4>{carName(car)}</h4>
    {identified && dealer ? <>
      <p className="dealer-name">{dealer.name ?? <span className="muted-cell">Dealer name not in the record</span>}</p>
      {dealer.address
        ? <DealerRow label="Address">{dealer.address}{maps && <> · <a className="dealer-link" href={maps} target="_blank" rel="noopener noreferrer">Open in Maps</a></>}</DealerRow>
        : <DealerRow label="Address"><span className="muted-cell">Not in the record</span>{maps && <> · <a className="dealer-link" href={maps} target="_blank" rel="noopener noreferrer">Search the name in Maps</a></>}</DealerRow>}
      <DealerRow label="Website">{website
        ? <a className="dealer-link" href={website} target="_blank" rel="noopener noreferrer">{dealer.source_domain ?? hostOf(website)}</a>
        : <span className="muted-cell">Not in the record</span>}</DealerRow>
      {phone && <DealerRow label="Phone">{dialable(phone) ? <a className="dealer-link" href={dialable(phone)!}>{phone}</a> : phone}</DealerRow>}
      {listing && <DealerRow label="Listing"><a className="dealer-link" href={listing} target="_blank" rel="noopener noreferrer">The listing this record came from</a></DealerRow>}
      {links.length > 0 && <div className="dealer-lookups">
        <span className="dealer-label">Look up yourself</span>
        <ul className="dealer-lookup-list">
          {links.map(link => <li key={link.url}>
            <a className="dealer-link" href={safeUrl(link.url)!} target="_blank" rel="noopener noreferrer">
              {link.label}<ExternalLink size={12} aria-hidden="true"/>
              <span className="sr-only"> (opens on their site in a new tab)</span>
            </a>
            {link.note && <span className="dealer-link-note">{link.note}</span>}
          </li>)}
        </ul>
      </div>}
      {notes.length > 0 && <ul className="dealer-notes">{notes.map(note => <li key={note}>{note}</li>)}</ul>}
    </> : <p className="honest-empty" role="status">
      <CircleAlert size={14}/>
      No dealer record came with this car. Only a licensed inventory import carries dealer contact details, and we won’t guess a name or an address.
    </p>}
    <DealerFlagBlock signals={signals}/>
  </article>;
}

function DealerSection({ report, activeId, onActive }: {
  report: Report; activeId?: string; onActive?: (id: string) => void;
}) {
  const cars = report.candidates;
  // Same breakpoint as CompareTable one-car focus — not the Import side-panel hide.
  const narrow = useNarrowViewport(NARROW_COMPARE);
  // One active car for the whole report on a narrow screen, so this section rides with the car the
  // comparison is showing instead of keeping a second, silently different selection.
  const active = cars.find(c => c.id === activeId) ?? cars[0];
  const shown = narrow && active ? [active] : cars;
  return <section className="report-section dealer-section">
    <h3>Dealer{narrow && active ? `: ${carName(active)}` : ''}</h3>
    <p className="dealer-scope" role="note">
      <CircleAlert size={14}/>
      <span>Who is selling the car, not the car itself. {DEALER_CAVEAT} Contact details are as the licensed
        listing record reported them — not verified by RevRank, and not evidence about the vehicle. The
        vehicle’s own green and red flags are above, with model-year safety; everything in this section
        is about the business, and we won’t invent a dealer score.</span>
    </p>
    {narrow && cars.length > 1 && active && <div className="compare-controls dealer-focus">
      <span className="control-label" id="dealer-focus-label">Dealer for one car</span>
      <div className="segmented" role="radiogroup" aria-labelledby="dealer-focus-label">
        {cars.map(c => <button key={c.id} type="button" role="radio" aria-checked={c.id === active.id}
          className={c.id === active.id ? 'on' : ''} onClick={() => onActive?.(c.id)}>{carName(c)}</button>)}
      </div>
    </div>}
    <div className={narrow ? 'dealer-grid dealer-grid-narrow' : 'dealer-grid'}>
      {shown.map(c => <DealerCard key={c.id} car={c} dealer={c.dealer} signals={report.dealer_signals?.[c.id] ?? null}/>)}
    </div>
  </section>;
}

function AIComparison({ ai, cars }: { ai: AIAnalysis; cars: Candidate[] }) {
  const index = new Map(ai.sources.map((s, i) => [s.id, i + 1]));
  const byId = new Map(ai.sources.map(s => [s.id, s]));
  const name = (id: string | null) => cars.find(c => c.id === id);
  const [openSources, setOpenSources] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const pick = (id: string) => { setOpenSources(true); setPicked(id); };
  useEffect(() => {
    if (!picked || !openSources) return;
    document.getElementById(`source-${index.get(picked)}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [picked, openSources]);
  const cites = (claim: Claim) => <Cites claim={claim} index={index} sources={byId} onPick={pick}/>;
  // Present only when the model ordered every car and every position passed the citation gate.
  const ranking = [...(ai.ranking ?? [])].sort((a, b) => a.position - b.position);
  return <section className="ai-block">
    <p className="eyebrow"><Sparkles size={13}/> AI COMPARISON · CITED EVIDENCE ONLY</p>
    {ai.verdict && <p className="verdict">{ai.verdict.text} {cites(ai.verdict)}</p>}
    {ranking.length > 0 && <div className="ai-ranking">
      <p className="constraint-label">Shortlist order for your constraints · each position cites its evidence</p>
      <ol>{ranking.map(entry => {
        const car = name(entry.candidate_id);
        return <li key={entry.candidate_id}>
          <strong>{car ? carName(car) : 'Car'}</strong>
          <span>{entry.claim.text} {cites(entry.claim)}</span>
        </li>;
      })}</ol>
    </div>}
    <div className="ai-cars">{ai.vehicles.map(v => {
      const car = name(v.candidate_id);
      return <div className="ai-car" key={v.candidate_id}>
        <h4>{car ? carName(car) : 'Car'}</h4>
        {v.summary && <p>{v.summary.text} {cites(v.summary)}</p>}
        <FlagList tone="green" label="Green flags" claims={v.strengths} cites={cites}/>
        <FlagList tone="red" label="Red flags" claims={v.risks} cites={cites}/>
        {!v.strengths.length && !v.risks.length &&
          <p className="flag-empty">No green or red flag passed the evidence checks for this car.</p>}
      </div>;
    })}</div>
    {ai.comparisons.length > 0 && <div className="ai-points">{ai.comparisons.map((p, i) => {
      const favored = name(p.favors);
      return <div className="ai-point" key={i}>
        <span className="topic">{p.topic}</span>
        <p>{p.claim.text} {cites(p.claim)}</p>
        {favored && <span className="favors">Favors {carName(favored)}</span>}
      </div>;
    })}</div>}
    {ai.sources.length === 0
      ? <p className="honest-empty" role="status"><CircleAlert size={14}/> No clickable sources for this run — we don’t invent citations.</p>
      : <details className="review-more" open={openSources} onToggle={e => setOpenSources(e.currentTarget.open)}>
          <summary>Sources ({ai.sources.length})</summary>
          <ol className="source-list">{ai.sources.map((s, i) => {
            const url = safeUrl(s.url);
            return <li key={s.id} id={`source-${i + 1}`} className={s.id === picked ? 'cited-now' : undefined}>
              <strong>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{s.label}</a> : s.label}</strong>
              <span>{s.detail}</span>
            </li>;
          })}</ol>
        </details>}
    <p className="ai-meta">{ai.message} Model: {ai.model}.</p>
    {ai.dropped_claims > 0 && <p className="dropped-claims" role="status">
      <CircleAlert size={14}/> {ai.dropped_claims} claim{ai.dropped_claims === 1 ? '' : 's'} held back — not enough evidence.
    </p>}
  </section>;
}

function ComingModule({ title, body, caveats }: { title: string; body: string; caveats: string[] }) {
  return <section className="report-section coming-module">
    <h3>{title}</h3>
    <p className="coming-copy"><CircleAlert size={15}/> Coming next: {body} We won’t invent a number.</p>
    {caveats.length > 0 && <ul className="coming-caveats">{caveats.map(w => <li key={w}>{w}</li>)}</ul>}
  </section>;
}

export function ReportView({ report, preferences, setPreferences, onApply, onCancelCompare, compareError, buildSlow, busy, narrow, onBack, onReset }: {
  report: Report;
  preferences: Preferences;
  setPreferences: (p: Preferences) => void;
  onApply: () => void;
  onCancelCompare?: () => void;
  compareError?: string | null;
  buildSlow?: boolean;
  busy?: boolean;
  narrow?: boolean;
  onBack: () => void;
  onReset: () => void;
}) {
  const ai = report.ai_analysis;
  const cars = report.candidates;
  // The one car the narrow layout is showing. Shared, so the comparison's one-car picker and the
  // per-car sections below it can never drift onto different cars.
  const [pickedCarId, setPickedCarId] = useState(cars[0]?.id);
  const activeCarId = cars.some(c => c.id === pickedCarId) ? pickedCarId : cars[0]?.id;
  const aiQuestions = (id: string) => (ai?.questions ?? []).filter(q => q.candidate_id === id).map(q => q.text);
  const warnings = [...new Set(report.warnings)];
  const depCaveats = warnings.filter(w => /depreciat|resale|ownership|years kept|mileage when/i.test(w));
  const condCaveats = warnings.filter(w => /condition|feature|history|accident|title|option/i.test(w));
  const lifted = new Set([...depCaveats, ...condCaveats]);
  const remainingCaveats = warnings.filter(w => !lifted.has(w));
  const synthetic = cars.length > 0 && cars.every(c => c.source_kind === 'synthetic' || c.retrieval_method === 'synthetic');
  const hasObs = cars.some(c => (c.observations?.length ?? 0) > 0);
  const marketEmpty = !report.market.comparables?.length
    || /unavailable|not available|disabled|no market|synthetic/i.test(report.market.message || '')
    || report.market.status === 'unavailable';
  const panel = <ConstraintPanel mode="report" preferences={preferences} onChange={setPreferences} onApply={onApply} busy={busy} narrow={narrow} applied={report.preferences}/>;
  return <section className="workspace report-layout">
    {narrow && panel}
    <div className="report-wrap">
    <div className="report-toolbar">
      <button className="secondary-button" onClick={onBack}>← Edit cars</button>
      <button className="secondary-button" onClick={() => window.print()}>Print report</button>
      <button className="primary-button" onClick={onReset}>New comparison</button>
    </div>
    {compareError && !busy && <div className="compare-empty" role="alert">
      <strong><CircleAlert size={16}/> Re-rank didn’t finish</strong>
      <p>{compareError}</p>
      <div className="compare-empty-actions">
        <button type="button" className="primary-button" onClick={onApply}>Retry Apply</button>
      </div>
    </div>}
    {busy && <div className="compare-building" role="status">
      <LoaderCircle className="spin" size={16}/>
      <div>
        <strong>{buildSlow ? 'Still applying constraints…' : 'Building report…'}</strong>
        <p>{buildSlow
          ? 'Taking longer than usual. Cancel and retry anytime — your draft stays intact.'
          : 'Rebuilding the cited comparison with your constraints.'}</p>
      </div>
      {onCancelCompare && <button type="button" className="secondary-button" onClick={onCancelCompare}>Cancel</button>}
    </div>}
    <article className="report">
      <div className="report-head">
        <div>
          <p className="eyebrow">REVRANK REPORT · {new Date(report.created_at).toLocaleDateString()}</p>
          <h2>{cars.map(carName).join(' vs ')}</h2>
        </div>
        <span className="mode-pill">{report.analysis_mode === 'llm' ? 'AI assisted' : 'Rules-based'}</span>
      </div>

      {ai && ai.status === 'partial' && ai.message && /time limit|timed out|stopped at the server/i.test(ai.message) &&
        <div className="ai-timeout-note" role="status"><CircleAlert size={15}/><span>{ai.message}</span></div>}
      {ai && ai.status !== 'unavailable' ? <AIComparison ai={ai} cars={cars}/>
        : (() => {
          const timedOut = Boolean(ai?.message && /time limit|timed out|stopped at the server/i.test(ai.message));
          return <div className="ai-off"><Sparkles size={16}/><div>
            <strong>{timedOut ? 'AI stopped at the server time limit' : 'AI comparison not generated'}</strong>
            <p>{ai?.message || 'Add an LLM API key on the server to get a cited, side-by-side verdict.'}
              {' '}{timedOut
                ? 'The comparison, metrics and evidence below are complete — nothing was invented from the unfinished AI run.'
                : 'The table below is computed directly from your reviewed details.'}</p>
          </div></div>;
        })()}

      <section className="report-section">
        <h3>Side by side</h3>
        <CompareTable report={report} activeId={activeCarId} onActive={setPickedCarId}/>
      </section>

      {/* Per-car context, in one tier: model-year safety and then the seller. Both sit below the
          vehicle green/red flags in the AI block, never above them, and the Dealer heading and its
          own flag labels keep the seller's record from reading as a vehicle flag. */}
      <NhtsaSection report={report}/>
      <DealerSection report={report} activeId={activeCarId} onActive={setPickedCarId}/>

      <ComingModule title="Depreciation" body="ownership-horizon depreciation from cited market observations." caveats={depCaveats}/>
      <ComingModule title="Condition & feature vs price" body="condition and option content weighed against asking price with evidence." caveats={condCaveats}/>

      <section className="report-section">
        <h3>Ask each seller</h3>
        <div className="seller-questions">{cars.map(c => {
          const questions = [...new Set([...aiQuestions(c.id), ...(report.questions.find(q => q.candidate_id === c.id)?.questions ?? [])])];
          return <div key={c.id}>
            <strong>{carName(c)}</strong>
            <ul>{questions.slice(0, 4).map(q => <li key={q}>{q}</li>)}</ul>
            {questions.length > 4 && <details className="review-more"><summary>{questions.length - 4} more</summary>
              <ul>{questions.slice(4).map(q => <li key={q}>{q}</li>)}</ul></details>}
          </div>;
        })}</div>
      </section>

      <details className="report-details">
        <summary>Findings, sources and caveats</summary>
        <div className="report-section">
          <h3>What stands out</h3>
          {report.findings.map(f => <div className="finding" key={f.title}><strong>{f.title}</strong><p>{f.detail}</p></div>)}
        </div>
        {hasObs
          ? cars.filter(c => c.observations?.length).map(c => <div className="report-section" key={c.id}>
              <h3>Sources: {carName(c)}</h3><SourceTable candidate={c}/>
            </div>)
          : <div className="report-section">
              <h3>Sources</h3>
              <p className="honest-empty" role="status">
                <CircleAlert size={14}/>
                {synthetic
                  ? 'Synthetic examples have no listing source URLs — we don’t invent citations.'
                  : 'No source observations were returned for these cars.'}
              </p>
            </div>}
        <div className="report-section market-block">
          <h3>Market evidence</h3>
          {marketEmpty
            ? <p className="honest-empty" role="status">
                <CircleAlert size={14}/>
                {synthetic
                  ? 'Market evidence is unavailable for synthetic examples — not live market observations.'
                  : (report.market.message || 'Market evidence is unavailable for this comparison.')}
              </p>
            : <p>{report.market.message}</p>}
        </div>
        <div className="report-section">
          <h3>Caveats</h3>
          {remainingCaveats.length
            ? <ul className="notes">{remainingCaveats.map(w => <li key={w}>{w}</li>)}</ul>
            : <p className="muted">Other caveats already shown under Depreciation / Condition above.</p>}
        </div>
      </details>
    </article>
    </div>
    {!narrow && panel}
  </section>;
}
