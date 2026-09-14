import { useState, type ReactNode } from 'react';
import { Check, CircleAlert, Sparkles } from 'lucide-react';
import { allSame, comparable, delta, isCrossModel, metric, mileageValue, msrpPctDelta, msrpValue, mustHaveMetrics, numberIn, pctOfMsrp, pctOfMsrpText, priceValue, sharedAnnual, tradeOff, type DeltaKind } from './compare';
import { SourceTable } from './Review';
import type { AIAnalysis, Candidate, Claim, NHTSASafetyData, Report } from './types';
import { rankShortlist, type RankFactorId, type RankingResult } from './rank';
import { carName, dateLabel, money, safeUrl, unresolvedConflicts } from './utils';

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
      hint: 'you entered',
      text: (c, i) => {
        const fromMetric = metric(report, '% of original MSRP')?.values[i];
        if (fromMetric && fromMetric !== 'N/A' && fromMetric !== 'MSRP not confirmed') return `${fromMetric} of original MSRP (you entered)`;
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
          return <span className="msrp-pct">{fromMetric} of original MSRP (you entered)</span>;
        }
        if (fromMetric === 'MSRP not confirmed') {
          return <span className="muted-cell msrp-cta">MSRP present but not marked user-confirmed — re-enter on Review</span>;
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
        <p className={pct ? 'value-msrp' : 'value-msrp muted-cta'}>{pct ? pct : 'No MSRP entered — add original MSRP on Review to see % of sticker'}</p>
        {msrp !== null && <p className="value-msrp-raw">MSRP you entered: {money(msrp, c.currency)}</p>}
        <p className="value-miles">{mileageText(c)}</p>
        {(c.make || c.model) && <p className="value-model">{[c.year, c.make, c.model, c.trim].filter(Boolean).join(' ')}</p>}
      </article>;
    })}
  </div>;
}

function CompareTable({ report }: { report: Report }) {
  const cars = report.candidates;
  const crossModel = report.cross_model ?? isCrossModel(cars);
  const [benchId, setBenchId] = useState(cars[0]?.id);
  const [diffOnly, setDiffOnly] = useState(true);
  const bench = cars.find(c => c.id === benchId) ?? cars[0];
  // The benchmark leads; the others keep their order. Indexes stay tied to report.candidates.
  const order = [cars.indexOf(bench), ...cars.map((_, i) => i).filter(i => cars[i] !== bench)];
  const rows = rowsFor(report, bench, crossModel);
  const shown = rows.filter(row => row.always || !diffOnly || !allSame(cars.map((c, i) => row.text(c, i))));
  const hidden = rows.length - shown.length;
  return <>
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
    <div className="table-scroll"><table className="compare-table">
      <thead><tr><th/>{order.map(i => <th key={cars[i].id} className={i === order[0] ? 'bench-col' : ''}>
        {carName(cars[i])}<small>{i === order[0] ? 'benchmark' : 'vs benchmark'}</small></th>)}</tr></thead>
      <tbody>
        {shown.map(row => {
          const best = bestIndex(cars, row);
          return <tr key={row.label}>
            <th scope="row">{row.label}{row.hint && <small>{row.hint}</small>}</th>
            {order.map(i => {
              const c = cars[i];
              const d = row.delta && i !== order[0] && row.rank ? delta(row.delta, row.rank(c, i), row.rank(bench, order[0]), c, bench) : null;
              const msrpD = row.label.startsWith('% of original') && i !== order[0] ? msrpPctDelta(c, bench) : null;
              return <td key={c.id} className={[i === best ? 'best' : '', i === order[0] ? 'bench-col' : ''].join(' ').trim()}>
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
      {hidden > 0 && <>{hidden} {hidden === 1 ? 'row is' : 'rows are'} the same for every car and hidden. </>}
      Green is better for you and amber is worse, compared with the benchmark.
      {crossModel
        ? ' Across models, prefer % of the MSRP you entered over raw asking-price gaps. Trade-offs use asking prices, not out-the-door prices.'
        : ' Trade-offs use asking prices, not out-the-door prices.'}
    </p>
  </>;
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
            <strong>{nhtsaRecalls(data)}</strong> recalls · <strong>{nhtsaComplaints(data)}</strong> complaints
            {nhtsaOverall(data) != null && <> · NHTSA overall {nhtsaOverall(data)}</>}
          </p>
          {!!data.recalls?.[0] && <p className="nhtsa-top">Top recall component: {data.recalls[0].component}</p>}
          {!!data.complaints?.[0] && <p className="nhtsa-top">Most-noted complaint area: {data.complaints[0].component}</p>}
          {!!(data.recalls?.length || data.complaints?.length) && <details className="review-more">
            <summary>Recalls &amp; complaints detail</summary>
            <ul className="nhtsa-list">
              {(data.recalls ?? []).slice(0, 5).map(r => <li key={r.campaign_number}><strong>{r.component}</strong> — {r.summary}</li>)}
              {(data.complaints ?? []).slice(0, 5).map(r => <li key={r.odi_number}><strong>{r.component}</strong> — {r.summary}</li>)}
            </ul>
          </details>}
        </>}
      </article>)}
    </div>
  </section>;
}

function RankingSection({ report }: { report: Report }) {
  const base = rankShortlist(report);
  const [weights, setWeights] = useState(base.weights);
  const result: RankingResult = rankShortlist(report, weights);
  const active = (Object.keys(result.weights) as RankFactorId[]).filter(id => result.weights[id] > 0);

  return <section className="ranking-block">
    <div className="ranking-head">
      <div>
        <p className="eyebrow">DETERMINISTIC · YOUR WEIGHTS</p>
        <h3>Your ranking</h3>
      </div>
      <p className="muted ranking-lede">Ordered by must-have flags first, then a transparent fit score from your priorities. Missing inputs are omitted — never invented.</p>
    </div>
    {result.notes.map(n => <p className="ranking-note" key={n}><CircleAlert size={14}/> {n}</p>)}
    <div className="rank-weights">
      {active.map(id => <label key={id} className="rank-weight">
        <span>{result.ranked[0]?.factors.find(f => f.id === id)?.label ?? id} <em>{result.weights[id]}%</em></span>
        <input type="range" min={0} max={100} value={result.weights[id]}
          onChange={e => {
            const next = { ...weights, [id]: Number(e.target.value) };
            setWeights(next);
          }}/>
      </label>)}
    </div>
    <ol className="rank-cards">
      {result.ranked.map((row, place) => <li key={row.candidate.id} className={`rank-card${row.softFlags ? ' flagged' : ''}`}>
        <div className="rank-card-top">
          <span className="rank-place">#{place + 1}</span>
          <div>
            <strong>{carName(row.candidate)}</strong>
            <p className="rank-fit">{row.fit == null ? 'Not enough inputs to score' : `Fit ${row.fit}`}</p>
          </div>
        </div>
        {row.softFlags > 0 && <p className="rank-knock">
          Must-have not mentioned: {row.knockouts.map(k => k.label).join(', ')} — unknown, not a confirmed miss.
        </p>}
        {row.contributions[0] && <p className="rank-why">Top factors: {row.contributions.slice(0, 3).map(c => `${c.label} (${c.points})`).join(' · ')}</p>}
        <details className="rank-breakdown">
          <summary>Score breakdown</summary>
          <ul>
            {row.contributions.map(c => <li key={c.id}><span>{c.label}</span><span>{c.weight}% → {c.points} pts</span></li>)}
            {row.omitted.map(o => <li key={o} className="omitted">Omitted: {o}</li>)}
            {!row.contributions.length && !row.omitted.length && <li className="omitted">No scorable factors for this car.</li>}
          </ul>
        </details>
      </li>)}
    </ol>
    {result.sensitivity && <p className="rank-sensitivity">{result.sensitivity}</p>}
  </section>;
}

function Cites({ claim, index }: { claim: Claim; index: Map<string, number> }) {
  return <>{claim.citations.map(id => index.has(id) &&
    <a key={id} className="cite" href={`#source-${index.get(id)}`} title={id}>{index.get(id)}</a>)}</>;
}

function AIComparison({ ai, cars }: { ai: AIAnalysis; cars: Candidate[] }) {
  const index = new Map(ai.sources.map((s, i) => [s.id, i + 1]));
  const name = (id: string | null) => cars.find(c => c.id === id);
  return <section className="ai-block">
    <p className="eyebrow"><Sparkles size={13}/> AI COMPARISON · CITED</p>
    {ai.verdict && <p className="verdict">{ai.verdict.text} <Cites claim={ai.verdict} index={index}/></p>}
    <div className="ai-cars">{ai.vehicles.filter(v => v.strengths.length || v.risks.length || v.summary).map(v => {
      const car = name(v.candidate_id);
      return <div className="ai-car" key={v.candidate_id}>
        <h4>{car ? carName(car) : 'Car'}</h4>
        {v.summary && <p>{v.summary.text} <Cites claim={v.summary} index={index}/></p>}
        <ul>
          {v.strengths.map((c, i) => <li key={`s${i}`} className="plus"><Check size={13}/><span>{c.text} <Cites claim={c} index={index}/></span></li>)}
          {v.risks.map((c, i) => <li key={`r${i}`} className="minus"><CircleAlert size={13}/><span>{c.text} <Cites claim={c} index={index}/></span></li>)}
        </ul>
      </div>;
    })}</div>
    {ai.comparisons.length > 0 && <div className="ai-points">{ai.comparisons.map((p, i) => {
      const favored = name(p.favors);
      return <div className="ai-point" key={i}>
        <span className="topic">{p.topic}</span>
        <p>{p.claim.text} <Cites claim={p.claim} index={index}/></p>
        {favored && <span className="favors">Favors {carName(favored)}</span>}
      </div>;
    })}</div>}
    <details className="review-more">
      <summary>Sources ({ai.sources.length})</summary>
      <ol className="source-list">{ai.sources.map((s, i) => {
        const url = safeUrl(s.url);
        return <li key={s.id} id={`source-${i + 1}`}><strong>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{s.label}</a> : s.label}</strong><span>{s.detail}</span></li>;
      })}</ol>
    </details>
    <p className="ai-meta">{ai.message} Model: {ai.model}.</p>
  </section>;
}

export function ReportView({ report, onBack, onReset }: { report: Report; onBack: () => void; onReset: () => void }) {
  const ai = report.ai_analysis;
  const cars = report.candidates;
  const aiQuestions = (id: string) => (ai?.questions ?? []).filter(q => q.candidate_id === id).map(q => q.text);
  return <section className="report-wrap">
    <div className="report-toolbar">
      <button className="secondary-button" onClick={onBack}>← Edit cars</button>
      <button className="secondary-button" onClick={() => window.print()}>Print report</button>
      <button className="primary-button" onClick={onReset}>New comparison</button>
    </div>
    <article className="report">
      <div className="report-head">
        <div>
          <p className="eyebrow">REVRANK REPORT · {new Date(report.created_at).toLocaleDateString()}</p>
          <h2>{cars.map(carName).join(' vs ')}</h2>
        </div>
        <span className="mode-pill">{report.analysis_mode === 'llm' ? 'AI assisted' : 'Rules-based'}</span>
      </div>

      {ai && ai.status !== 'unavailable' ? <AIComparison ai={ai} cars={cars}/>
        : <div className="ai-off"><Sparkles size={16}/><div><strong>AI comparison not generated</strong>
            <p>{ai?.message || 'Add an LLM API key on the server to get a cited, side-by-side verdict.'} The table below is computed directly from your reviewed details.</p></div></div>}

      <section className="report-section">
        <RankingSection report={report}/>
      </section>

      <NhtsaSection report={report}/>

      <section className="report-section">
        <h3>Side by side</h3>
        <CompareTable report={report}/>
      </section>

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
        {cars.filter(c => c.observations?.length).map(c => <div className="report-section" key={c.id}>
          <h3>Sources: {carName(c)}</h3><SourceTable candidate={c}/>
        </div>)}
        <div className="report-section market-block"><h3>Market evidence</h3><p>{report.market.message}</p></div>
        <div className="report-section">
          <h3>Caveats</h3>
          <ul className="notes">{[...new Set(report.warnings)].map(w => <li key={w}>{w}</li>)}</ul>
        </div>
      </details>
    </article>
  </section>;
}
