import type { Candidate, EvidenceStatus, ImportRequest, ImportSlot, Preferences, RecoverySource, RecoveryStatus } from './types';

export const evidenceLabels: Record<EvidenceStatus, string> = {
  seller_claim: 'Seller claim', user_confirmed: 'User input', extracted: 'Extracted', synthetic: 'Synthetic',
};
export const defaultPreferences: Preferences = {
  budget: null, annual_mileage: 12000, ownership_years: 3, location: '',
  priorities: ['Lower asking price', 'Lower mileage'], must_haves: [],
  max_mileage: null, transmission: null, excludes: [],
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
export const importBody = (slot: Pick<ImportSlot, 'url' | 'text' | 'vin' | 'recover'>, source: RecoverySource = 'auto'): ImportRequest => {
  const url = slot.url.trim(), text = slot.text.trim(), vin = slot.vin.replace(/\s+/g, '').toUpperCase();
  return {
    ...(url ? { url } : {}),
    ...(text ? { text } : {}),
    ...(vin ? { vin } : {}),
    ...(url && !text && !slot.recover ? { recover: false } : {}),
    // Only sent when it changes something: a URL import that may recover, with a non-default source.
    ...(url && !text && slot.recover && source !== 'auto' ? { recovery_source: source } : {}),
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
    year: null, price: null, msrp: null, currency: 'USD', mileage: null, mileage_unit: 'mi', transmission: null,
    body: null, engine: null, drivetrain: null, fuel_type: null,
    location: null, features: [], history: null, source_url: null, source_kind: 'user', evidence: {},
    warnings: ['Manually entered candidate. Blank fields remain unknown.'], verified_fields: [],
  };
}

export const carName = (c: Candidate) => [c.year, c.make, c.model].filter(Boolean).join(' ') || c.title;

export interface Provenance { label: string; tone: 'registry' | 'listing' | 'search' | 'user' | 'inferred' | 'licensed' | 'demo'; source: string }
// Short, human label for where a field's value came from; the full source string stays in the tooltip.
export function provenance(c: Candidate, field: string): Provenance | null {
  const evidence = c.evidence[field];
  if (!evidence) return null;
  const source = evidence.source;
  if (evidence.status === 'user_confirmed') return { label: 'You', tone: 'user', source };
  if (source.startsWith('NHTSA vPIC')) return { label: 'NHTSA', tone: 'registry', source };
  if (source.startsWith('MarketCheck NeoVIN')) return { label: field === 'msrp' ? 'Factory MSRP · NeoVIN' : 'NeoVIN', tone: 'licensed', source };
  if (source.startsWith('Inferred from source')) return { label: 'Inferred', tone: 'inferred', source };
  if (source.startsWith('Licensed inventory')) return { label: 'Licensed', tone: 'licensed', source };
  if (source.startsWith('Private in-app browse')) return { label: 'Private browse', tone: 'listing', source };
  if (c.source_kind === 'synthetic') return { label: 'Demo', tone: 'demo', source };
  if (c.retrieval_method === 'browse') return { label: 'Private browse', tone: 'listing', source };
  if (c.retrieval_method === 'search') return { label: 'Search', tone: 'search', source };
  if (c.source_kind === 'user') return { label: 'Pasted', tone: 'listing', source };
  return { label: 'Listing', tone: 'listing', source };
}

export const hostOf = (url: string | null) => { const safe = safeUrl(url); return safe ? new URL(safe).hostname.replace(/^www\./, '') : ''; };

// Distinct values the sources reported for a field, for one-click conflict resolution.
export function fieldOptions(c: Candidate, field: string): { value: string; hosts: string[] }[] {
  const options = new Map<string, Set<string>>();
  for (const o of c.observations ?? []) {
    if (o.field !== field) continue;
    const value = /^\d+\.0$/.test(o.value) ? o.value.slice(0, -2) : o.value;
    options.set(value, (options.get(value) ?? new Set()).add(o.method === 'registry' ? 'NHTSA' : hostOf(o.source_url) || o.method));
  }
  return [...options].map(([value, hosts]) => ({ value, hosts: [...hosts] }));
}

export const unresolvedConflicts = (c: Candidate) => (c.conflicts ?? []).filter(field => !c.verified_fields.includes(field));


/** Suggested badge copy for ImportResponse.recovery_status (frontend owns final wording). */
export const recoveryBadge = (status: RecoveryStatus | null | undefined): string | null => {
  if (!status) return null;
  const labels: Record<RecoveryStatus, string> = {
    recovered: 'Recovered from other sources',
    identity_only: 'Identity only',
    identity_conflict: 'Identity conflict',
    not_found: 'Not found',
    not_listing: 'Not a listing',
    failed: 'Recovery failed',
    disabled: 'Recovery disabled',
    unavailable: 'Source unavailable',
  };
  return labels[status] ?? readableField(status);
};
