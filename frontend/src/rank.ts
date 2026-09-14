import type { Candidate, Report } from './types';
import { isCrossModel, metric, mileageValue, mustHaveMetrics, numberIn, pctOfMsrp, priceValue } from './compare';
import { carName, money } from './utils';

export type RankFactorId = 'price' | 'msrp_pct' | 'mileage' | 'ownership';

export interface RankFactor {
  id: RankFactorId;
  label: string;
  // Higher is better for the buyer after normalization.
  score: number | null;
  rawLabel: string | null;
  omitted: string | null;
}

export interface Knockout {
  label: string;
  status: 'listed' | 'not_mentioned';
}

export interface RankedCar {
  candidate: Candidate;
  index: number;
  knockouts: Knockout[];
  softFlags: number;
  factors: RankFactor[];
  // 0–100 fit after weights; null if nothing scorable.
  fit: number | null;
  contributions: { id: RankFactorId; label: string; weight: number; points: number }[];
  omitted: string[];
}

export interface RankingResult {
  crossModel: boolean;
  weights: Record<RankFactorId, number>;
  ranked: RankedCar[];
  sensitivity: string | null;
  notes: string[];
}

const FACTOR_LABEL: Record<RankFactorId, string> = {
  price: 'Asking price',
  msrp_pct: '% of original MSRP',
  mileage: 'Mileage',
  ownership: 'Mileage when you sell',
};

function normKey(s: string) { return s.toLowerCase(); }

// Map free-text priorities onto score factors (transparent, no ML).
export function factorsFromPriorities(priorities: string[], crossModel: boolean): RankFactorId[] {
  const ids = new Set<RankFactorId>();
  for (const raw of priorities) {
    const p = normKey(raw);
    if (/(msrp|sticker|deal|value for money|% of)/.test(p)) ids.add('msrp_pct');
    if (/(price|cost|budget|cheap|afford)/.test(p)) ids.add(crossModel ? 'msrp_pct' : 'price');
    if (/(mile|odometer|km)/.test(p)) ids.add('mileage');
    if (/(own|horizon|resale|years held|when you sell)/.test(p)) ids.add('ownership');
    if (/(value)/.test(p) && !ids.has('msrp_pct') && !ids.has('price')) ids.add(crossModel ? 'msrp_pct' : 'price');
  }
  // Always include available value lenses with a baseline so empty priorities still rank.
  if (!ids.size) {
    if (crossModel) ids.add('msrp_pct');
    else { ids.add('price'); ids.add('mileage'); }
  }
  if (crossModel) {
    ids.add('msrp_pct');
    ids.delete('price'); // don't lead rank key with raw $ across models
  } else {
    if (!ids.has('price') && !ids.has('msrp_pct')) ids.add('price');
    if (!ids.has('mileage')) ids.add('mileage');
  }
  return [...ids];
}

export function defaultWeights(ids: RankFactorId[]): Record<RankFactorId, number> {
  const w = { price: 0, msrp_pct: 0, mileage: 0, ownership: 0 } as Record<RankFactorId, number>;
  if (!ids.length) return w;
  const each = Math.round((1000 / ids.length)) / 10;
  let used = 0;
  ids.forEach((id, i) => {
    if (i === ids.length - 1) w[id] = Math.round((100 - used) * 10) / 10;
    else { w[id] = each; used += each; }
  });
  return w;
}

function minMaxScores(values: (number | null)[], lowerIsBetter: boolean): (number | null)[] {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return values.map(v => v === null ? null : 100);
  const lo = Math.min(...known), hi = Math.max(...known);
  if (lo === hi) return values.map(v => v === null ? null : 100);
  return values.map(v => {
    if (v === null) return null;
    const t = (v - lo) / (hi - lo);
    const better = lowerIsBetter ? 1 - t : t;
    return Math.round(better * 1000) / 10;
  });
}

function knockoutsFor(report: Report, index: number): Knockout[] {
  return mustHaveMetrics(report).map(m => {
    const raw = (m.values[index] ?? '').toLowerCase();
    const status: Knockout['status'] = raw === 'listed' ? 'listed' : 'not_mentioned';
    return { label: m.label.replace(/^Must-have:\s*/i, ''), status };
  }).filter(k => k.status !== 'listed');
}

function rawFactors(report: Report, c: Candidate, index: number): Omit<RankFactor, 'score'>[] {
  const price = priceValue(c);
  const pct = pctOfMsrp(c);
  const miles = mileageValue(c);
  const odo = metric(report, 'Projected odometer after');
  const odoN = odo ? numberIn(odo.values[index]) : null;
  return [
    {
      id: 'price', label: FACTOR_LABEL.price,
      rawLabel: price === null ? null : money(price, c.currency),
      omitted: price === null ? 'Asking price unknown or currency unconfirmed' : null,
    },
    {
      id: 'msrp_pct', label: FACTOR_LABEL.msrp_pct,
      rawLabel: pct === null ? null : `${pct}%`,
      omitted: pct === null ? 'Original MSRP not entered on Review' : null,
    },
    {
      id: 'mileage', label: FACTOR_LABEL.mileage,
      rawLabel: miles === null ? null : `${miles.toLocaleString()} ${c.mileage_unit}`,
      omitted: miles === null ? 'Mileage unknown or unit unconfirmed' : null,
    },
    {
      id: 'ownership', label: FACTOR_LABEL.ownership,
      rawLabel: odoN === null ? null : (odo?.values[index] ?? null),
      omitted: odoN === null ? 'Ownership-horizon mileage not available (mixed or unconfirmed units)' : null,
    },
  ];
}

export function rankShortlist(report: Report, weightOverride?: Partial<Record<RankFactorId, number>>): RankingResult {
  const cars = report.candidates;
  const crossModel = report.cross_model ?? isCrossModel(cars);
  const wanted = factorsFromPriorities(report.preferences.priorities, crossModel);
  let weights = defaultWeights(wanted);
  if (weightOverride) {
    weights = { ...weights };
    for (const id of Object.keys(weights) as RankFactorId[]) {
      if (weightOverride[id] != null) weights[id] = weightOverride[id]!;
    }
    // Renormalize to 100 among factors that still have positive weight intent
    const active = wanted.filter(id => (weights[id] ?? 0) > 0);
    const sum = active.reduce((s, id) => s + weights[id], 0) || 1;
    for (const id of Object.keys(weights) as RankFactorId[]) {
      weights[id] = active.includes(id) ? Math.round((1000 * weights[id] / sum)) / 10 : 0;
    }
  }

  const notes: string[] = [];
  if (crossModel) notes.push('Cross-model shortlist: ranking leans on fit + % of MSRP, not raw asking price.');
  if (!report.preferences.priorities.length) notes.push('No priorities set — using default value weights. Add priorities on Review to steer the score.');

  // Build raw columns then normalize per factor (lower raw = better for all four).
  const base = cars.map((c, i) => ({ c, i, raw: rawFactors(report, c, i), knockouts: knockoutsFor(report, i) }));
  const byId: Record<RankFactorId, (number | null)[]> = {
    price: base.map(b => priceValue(b.c)),
    msrp_pct: base.map(b => pctOfMsrp(b.c)),
    mileage: base.map(b => mileageValue(b.c)),
    ownership: base.map(b => {
      const odo = metric(report, 'Projected odometer after');
      return odo ? numberIn(odo.values[b.i]) : null;
    }),
  };
  const scored: Record<RankFactorId, (number | null)[]> = {
    price: minMaxScores(byId.price, true),
    msrp_pct: minMaxScores(byId.msrp_pct, true),
    mileage: minMaxScores(byId.mileage, true),
    ownership: minMaxScores(byId.ownership, true),
  };

  const ranked: RankedCar[] = base.map((b, bi) => {
    const factors: RankFactor[] = b.raw.map(f => ({
      ...f,
      score: scored[f.id][bi],
    }));
    const contributions: RankedCar['contributions'] = [];
    const omitted: string[] = [];
    let fitNum = 0;
    let weightUsed = 0;
    for (const id of wanted) {
      const f = factors.find(x => x.id === id)!;
      const w = weights[id] ?? 0;
      if (w <= 0) continue;
      if (f.score === null) {
        omitted.push(f.omitted ?? `${f.label} unavailable`);
        continue;
      }
      const points = Math.round(f.score * w) / 100;
      contributions.push({ id, label: f.label, weight: w, points });
      fitNum += f.score * w;
      weightUsed += w;
    }
    const fit = weightUsed > 0 ? Math.round(fitNum / weightUsed * 10) / 10 : null;
    return {
      candidate: b.c,
      index: b.i,
      knockouts: b.knockouts,
      softFlags: b.knockouts.filter(k => k.status === 'not_mentioned').length,
      factors,
      fit,
      contributions: contributions.sort((a, b) => b.points - a.points),
      omitted,
    };
  });

  ranked.sort((a, b) => {
    if (a.softFlags !== b.softFlags) return a.softFlags - b.softFlags;
    if (a.fit === null && b.fit === null) return a.index - b.index;
    if (a.fit === null) return 1;
    if (b.fit === null) return -1;
    if (b.fit !== a.fit) return b.fit - a.fit;
    return a.index - b.index;
  });

  return {
    crossModel,
    weights,
    ranked,
    sensitivity: sensitivityLine(ranked, wanted, weights),
    notes,
  };
}

// Simple flip: "#2 wins unless <factor> weight > X%" when only that weight varies vs equal rest.
function sensitivityLine(ranked: RankedCar[], wanted: RankFactorId[], weights: Record<RankFactorId, number>): string | null {
  if (ranked.length < 2) return null;
  const a = ranked[0], b = ranked[1];
  if (a.fit === null || b.fit === null || a.softFlags !== b.softFlags) return null;
  // Prefer a factor where B is stronger than A and A currently wins overall.
  for (const id of wanted) {
    const fa = a.factors.find(f => f.id === id)?.score;
    const fb = b.factors.find(f => f.id === id)?.score;
    if (fa == null || fb == null || fb <= fa) continue;
    const others = wanted.filter(x => x !== id);
    const avg = (car: RankedCar) => {
      const vals = others.map(oid => car.factors.find(f => f.id === oid)?.score).filter((v): v is number => v != null);
      return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
    };
    const ao = avg(a), bo = avg(b);
    if (ao == null || bo == null) continue;
    // w*fb + (1-w)*bo > w*fa + (1-w)*ao  => w*(fb-fa) > (1-w)*(ao-bo)
    const dF = fb - fa; // > 0
    const dO = ao - bo;
    if (dO <= 0) continue; // B already wins on others too
    // w * dF > (1-w) * dO => w * dF > dO - w*dO => w*(dF+dO) > dO => w > dO/(dF+dO)
    const wFlip = dO / (dF + dO);
    const pct = Math.round(wFlip * 1000) / 10;
    if (pct <= 0 || pct >= 100) continue;
    const current = weights[id] ?? 0;
    if (current >= pct) continue; // already above flip; not insightful
    return `${carName(b.candidate)} wins unless ${FACTOR_LABEL[id].toLowerCase()} weight is above ${pct}% (now ${current}%).`;
  }
  return null;
}

