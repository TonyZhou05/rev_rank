import { Check, CircleAlert, Sparkles } from 'lucide-react';
import { SourceTable } from './Review';
import type { AIAnalysis, Candidate, Claim, Report } from './types';
import { carName, money, safeUrl, unresolvedConflicts } from './utils';

type Row = { label: string; value: (c: Candidate) => string; rank?: (c: Candidate) => number | null; best?: 'min' | 'max' };

const priceText = (c: Candidate) => c.price === null ? (unresolvedConflicts(c).includes('price') ? 'Sources disagree'
    : c.evidence.last_listed_price ? `Unknown (last listed ${c.evidence.last_listed_price.value})` : 'Unknown')
  : c.currency === 'UNK' ? `${c.price.toLocaleString()} (currency?)` : money(c.price, c.currency);
const mileageText = (c: Candidate) => c.mileage === null ? (unresolvedConflicts(c).includes('mileage') ? 'Sources disagree' : 'Unknown')
  : `${c.mileage.toLocaleString()} ${c.mileage_unit}`;
const text = (value: string | number | null | undefined) => value === null || value === undefined || value === '' ? '—' : String(value);

const ROWS: Row[] = [
  { label: 'Asking price', value: priceText, rank: c => c.currency !== 'UNK' ? c.price : null, best: 'min' },
  { label: 'Mileage', value: mileageText, rank: c => c.evidence.mileage_unit ? c.mileage : null, best: 'min' },
  { label: 'Model year', value: c => text(c.year), rank: c => c.year, best: 'max' },
  { label: 'Trim', value: c => text(c.trim) },
  { label: 'Transmission', value: c => text(c.transmission) },
  { label: 'Engine', value: c => text(c.engine) },
  { label: 'Drivetrain', value: c => text(c.drivetrain) },
  { label: 'Body', value: c => text(c.body) },
  { label: 'Location', value: c => text(c.location) },
];

// The "best" marker only appears when every car has a comparable value (same currency / unit).
function bestIndex(cars: Candidate[], row: Row): number | null {
  if (!row.rank || !row.best || cars.length < 2) return null;
  const values = cars.map(row.rank);
  if (values.some(v => v === null)) return null;
  if (row.label === 'Asking price' && new Set(cars.map(c => c.currency)).size > 1) return null;
  if (row.label === 'Mileage' && new Set(cars.map(c => c.mileage_unit)).size > 1) return null;
  const target = row.best === 'min' ? Math.min(...(values as number[])) : Math.max(...(values as number[]));
  return values.filter(v => v === target).length === 1 ? values.indexOf(target) : null;
}

function CompareTable({ report }: { report: Report }) {
  const cars = report.candidates;
  const budget = report.metrics.find(m => m.label === 'Budget headroom');
  return <div className="table-scroll"><table className="compare-table">
    <thead><tr><th/>{cars.map(c => <th key={c.id}>{carName(c)}</th>)}</tr></thead>
    <tbody>
      {ROWS.map(row => {
        const best = bestIndex(cars, row);
        return <tr key={row.label}><th scope="row">{row.label}</th>{cars.map((c, i) =>
          <td key={c.id} className={i === best ? 'best' : ''}>{row.value(c)}{i === best && <span className="best-tag">{row.best === 'min' ? 'lowest' : 'newest'}</span>}</td>)}</tr>;
      })}
      {budget && report.preferences.budget !== null && <tr><th scope="row">Budget headroom</th>{budget.values.map((v, i) => <td key={i}>{v}</td>)}</tr>}
    </tbody>
  </table></div>;
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
