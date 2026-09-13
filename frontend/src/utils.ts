import type { Candidate, EvidenceStatus, ImportRequest, ImportSlot, Preferences } from './types';

export const evidenceLabels: Record<EvidenceStatus, string> = {
  seller_claim: 'Seller claim', user_confirmed: 'User input', extracted: 'Extracted', synthetic: 'Synthetic',
};
export const defaultPreferences: Preferences = {
  budget: null, annual_mileage: 12000, ownership_years: 3, location: '',
  priorities: ['Lower asking price', 'Lower mileage'], must_haves: [],
};
export const freshSlot = (): ImportSlot => ({ id: crypto.randomUUID(), url: '', text: '', vin: '', recover: true, candidate: null });
// Saved drafts may come from an older page version: fill missing fields, never trust shapes.
export const restoreSlot = (saved: Partial<ImportSlot>): ImportSlot => {
  const slot = { ...freshSlot(), ...saved, editing: false };
  return { ...slot, url: String(slot.url ?? ''), text: String(slot.text ?? ''), vin: String(slot.vin ?? ''),
           candidate: slot.candidate && typeof slot.candidate === 'object' ? slot.candidate : null };
};
// Send only what this import needs. Blank fields are omitted, and `recover` is sent only to opt
// out of the server default on a URL fetch (pasted text never fetches or recovers).
export const importBody = (slot: Pick<ImportSlot, 'url' | 'text' | 'vin' | 'recover'>): ImportRequest => {
  const url = slot.url.trim(), text = slot.text.trim(), vin = slot.vin.replace(/\s+/g, '').toUpperCase();
  return {
    ...(url ? { url } : {}),
    ...(text ? { text } : {}),
    ...(vin ? { vin } : {}),
    ...(url && !text && !slot.recover ? { recover: false } : {}),
  };
};
export const money = (price: number | null, currency: string) => {
  if (price === null) return 'Price unknown';
  try { return new Intl.NumberFormat('en', { style: 'currency', currency, maximumFractionDigits: 0 }).format(price); }
  catch { return `${price.toLocaleString()} ${currency}`; }
};
export const mileage = (candidate: Candidate) => candidate.mileage === null ? 'Mileage unknown' : `${candidate.mileage.toLocaleString()} ${candidate.mileage_unit}`;
export const readableField = (field: string) => field.replaceAll('_', ' ').replace(/^./, (s) => s.toUpperCase());
export const dateLabel = (date: string) => {
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};
export function safeUrl(url: string | null) {
  if (!url) return null;
  try { const parsed = new URL(url); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : null; }
  catch { return null; }
}
export function sourceLabel(candidate: Candidate) {
  if (candidate.source_kind === 'synthetic') return 'Synthetic example';
  const url = safeUrl(candidate.source_url);
  return url ? new URL(url).hostname.replace(/^www\./, '') : 'User-provided details';
}
export function editCandidate(candidate: Candidate, field: keyof Candidate, value: unknown): Candidate {
  const previous = candidate.evidence[field];
  const previousValue = candidate[field];
  const display = Array.isArray(value) ? value.join(', ') : String(value ?? 'Unknown');
  // Preserve the original field evidence inside the contract's source string.
  // Repeated edits retain that original source instead of nesting correction histories.
  const original = previous?.status === 'user_confirmed' ? previous.source
    : `User correction. Previous value: ${Array.isArray(previousValue) ? previousValue.join(', ') : String(previousValue ?? 'Unknown')}. Previous evidence: ${previous ? `${previous.status}; ${previous.source}; ${previous.value}` : 'not supplied'}`;
  return {
    ...candidate, [field]: value,
    evidence: { ...candidate.evidence, [field]: { value: display, source: original, status: 'user_confirmed' } },
    verified_fields: [...new Set([...candidate.verified_fields, field])],
  };
}
export function manualCandidate(): Candidate {
  return {
    id: crypto.randomUUID(), title: 'Untitled vehicle', make: null, model: null, trim: null, generation: null,
    year: null, price: null, currency: 'USD', mileage: null, mileage_unit: 'mi', transmission: null,
    location: null, features: [], history: null, source_url: null, source_kind: 'user', evidence: {},
    warnings: ['Manually entered candidate. Blank fields remain unknown.'], verified_fields: [],
  };
}
