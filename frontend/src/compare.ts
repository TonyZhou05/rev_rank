import type { Candidate, Report } from './types';
import { money, unresolvedConflicts } from './utils';

// Side-by-side comparison against a benchmark car. Deltas and trade-offs are computed only between
// values that are comparable: a known price in the same currency, a confirmed mileage in the same unit.

export type DeltaKind = 'money' | 'distance' | 'year';
export interface Delta { text: string; tone: 'better' | 'worse' }
export interface TradeOff { text: string; tone: 'better' | 'worse' | 'mixed' }

export const priceValue = (c: Candidate) =>
  c.price !== null && c.currency !== 'UNK' && !unresolvedConflicts(c).includes('price') ? c.price : null;
export const mileageValue = (c: Candidate) =>
  c.mileage !== null && c.evidence.mileage_unit && !unresolvedConflicts(c).includes('mileage') ? c.mileage : null;

export function comparable(kind: DeltaKind, a: Candidate, b: Candidate): boolean {
  if (kind === 'money') return a.currency === b.currency && a.currency !== 'UNK';
  if (kind === 'distance') return a.mileage_unit === b.mileage_unit && Boolean(a.evidence.mileage_unit && b.evidence.mileage_unit);
  return true;
}

// Lower is better for money and distance; higher is better for model year.
export function delta(kind: DeltaKind, value: number | null, base: number | null, car: Candidate, bench: Candidate): Delta | null {
  if (value === null || base === null || !comparable(kind, car, bench)) return null;
  const d = Math.round(value - base);
  if (!d) return null;
  const sign = d > 0 ? '+' : '−', abs = Math.abs(d);
  const text = kind === 'money' ? `${sign}${money(abs, car.currency)}`
    : kind === 'distance' ? `${sign}${abs.toLocaleString()} ${car.mileage_unit}` : `${sign}${abs} yr`;
  return { text, tone: (kind === 'year' ? d > 0 : d < 0) ? 'better' : 'worse' };
}

// Small rates keep cents ("$0.47 per mi"); larger ones round like other prices.
function perUnit(amount: number, currency: string): string {
  if (amount >= 10) return money(amount, currency);
  try { return new Intl.NumberFormat('en', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount); }
  catch { return `${amount.toFixed(2)} ${currency}`; }
}

// What the price gap buys in mileage, relative to the benchmark. annual is the buyer's yearly
// distance in the shared unit, or null when the report could not confirm that unit.
export function tradeOff(car: Candidate, bench: Candidate, annual: number | null): TradeOff | null {
  const p = priceValue(car), bp = priceValue(bench), m = mileageValue(car), bm = mileageValue(bench);
  if (p === null || bp === null || m === null || bm === null) return null;
  if (!comparable('money', car, bench) || !comparable('distance', car, bench)) return null;
  const dp = Math.round(p - bp), dm = Math.round(m - bm), unit = car.mileage_unit;
  const cash = money(Math.abs(dp), car.currency), dist = `${Math.abs(dm).toLocaleString()} ${unit}`;
  const months = annual && annual > 0 && dm ? `, about ${Math.max(1, Math.round(Math.abs(dm) / (annual / 12)))} months of your driving` : '';
  if (!dp && !dm) return { text: 'Same price and mileage', tone: 'mixed' };
  if (dp <= 0 && dm <= 0) return { text: `${dp ? `${cash} less` : 'Same price'} and ${dm ? `${dist} fewer` : 'same mileage'}: better on both`, tone: 'better' };
  if (dp >= 0 && dm >= 0) return { text: `${dp ? `${cash} more` : 'Same price'} and ${dm ? `${dist} more` : 'same mileage'}: worse on both`, tone: 'worse' };
  const rate = perUnit(Math.abs(dp) / Math.abs(dm), car.currency);
  return dp > 0
    ? { text: `${cash} more for ${dist} fewer (${rate} per ${unit} avoided${months})`, tone: 'mixed' }
    : { text: `${cash} less for ${dist} more (saves ${rate} per extra ${unit}${months})`, tone: 'mixed' };
}

// Report metrics computed by the backend; values follow report.candidates order.
export function metric(report: Report, prefix: string) {
  return report.metrics.find(m => m.label.startsWith(prefix)) ?? null;
}
export const mustHaveMetrics = (report: Report) => report.metrics.filter(m => m.label.startsWith('Must-have: '));

// The yearly distance in the shared unit; only defined when the backend projected the odometer.
export function sharedAnnual(report: Report): number | null {
  return metric(report, 'Projected odometer after') ? report.preferences.annual_mileage : null;
}

export const numberIn = (text: string | undefined) => {
  if (!text || !/\d/.test(text)) return null;
  const n = Number(text.replace(/[^\d.]/g, ''));
  return Number.isFinite(n) ? n : null;
};

// Rows whose shown values are identical for every car carry no decision information.
export const allSame = (values: string[]) => values.every(v => v === values[0]);


// How the backend labels an MSRP it decoded from the VIN; see docs/API_CONTRACT.md.
const NEOVIN_MSRP = /^MarketCheck NeoVIN (?:msrp labeled )?(oem_msrp|original_msrp|combined_msrp)\b/;
const NEOVIN_FIELDS: Record<string, string> = { oem_msrp: 'OEM build', original_msrp: 'original sticker', combined_msrp: 'combined sticker' };

// Short, honest note on where the shown MSRP came from; null when nothing sourced it.
export function msrpOrigin(c: Candidate): string | null {
  if (c.verified_fields.includes('msrp')) return 'you entered';
  const decoded = c.evidence.msrp && NEOVIN_MSRP.exec(c.evidence.msrp.source);
  return decoded ? 'Factory MSRP · NeoVIN' : null;
}

/** Plain NeoVIN field kind under the MSRP input (OEM build / original / combined). */
export function msrpNeoVinKind(c: Candidate): string | null {
  if (c.verified_fields.includes('msrp')) return null;
  const decoded = c.evidence.msrp && NEOVIN_MSRP.exec(c.evidence.msrp.source);
  return decoded ? (NEOVIN_FIELDS[decoded[1]] ?? null) : null;
}

export const msrpValue = (c: Candidate) =>
  c.msrp != null && c.msrp > 0 && c.currency !== 'UNK' && msrpOrigin(c) !== null ? c.msrp : null;

// Prefer Candidate.percent_of_msrp from compare. FE fallback uses the same gates: price+msrp set,
// currency not UNK, MSRP buyer-confirmed or NeoVIN-sourced. Not a user-editable input.
export function pctOfMsrp(c: Candidate): number | null {
  if (c.percent_of_msrp != null && Number.isFinite(c.percent_of_msrp)) return c.percent_of_msrp;
  return derivePercentOfMsrp(c);
}

export function derivePercentOfMsrp(c: Candidate): number | null {
  const p = priceValue(c), m = msrpValue(c);
  if (p === null || m === null || m <= 0) return null;
  return Math.round((10000 * p) / m) / 100; // two decimals, match backend round(pct, 2)
}

export function pctOfMsrpText(c: Candidate): string | null {
  const pct = pctOfMsrp(c);
  return pct === null ? null : `${pct}% of original MSRP (${msrpOrigin(c) ?? 'sourced'})`;
}

export function isCrossModel(cars: Candidate[]): boolean {
  if (cars.length < 2) return false;
  const key = (c: Candidate) => `${(c.make ?? '').trim().toLowerCase()}|${(c.model ?? '').trim().toLowerCase()}`;
  const first = key(cars[0]);
  // Missing make/model on any car counts as cross-model — we cannot claim same-model.
  if (!cars[0].make || !cars[0].model) return true;
  return cars.some(c => !c.make || !c.model || key(c) !== first);
}

// %-of-MSRP gap vs benchmark: lower % is better value vs original sticker.
export function msrpPctDelta(car: Candidate, bench: Candidate): Delta | null {
  const a = pctOfMsrp(car), b = pctOfMsrp(bench);
  if (a === null || b === null || !comparable('money', car, bench)) return null;
  const d = Math.round((a - b) * 10) / 10;
  if (!d) return null;
  const sign = d > 0 ? '+' : '−';
  return { text: `${sign}${Math.abs(d)} pts of MSRP`, tone: d < 0 ? 'better' : 'worse' };
}
