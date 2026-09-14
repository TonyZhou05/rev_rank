import { API_REVISION } from './api';
import type { ImportRequest, ImportResult, ImportSlot, Preferences, RecoverySource } from './types';

// Browser-local persistence. Storage can be full, disabled, or cleared: every access is
// best-effort and the app works without it.
const DRAFT_KEY = 'revrank.draft.v1';
const CACHE_KEY = 'revrank.imports.v1';
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHE_LIMIT = 20;

function read<T>(key: string): T | null {
  try { const raw = window.localStorage.getItem(key); return raw ? JSON.parse(raw) as T : null; }
  catch { return null; }
}
function write(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* not persisted */ }
}

export interface Draft { slots: ImportSlot[]; preferences: Preferences }

export function loadDraft(): Draft | null {
  const draft = read<Draft>(DRAFT_KEY);
  if (!draft || !Array.isArray(draft.slots) || !draft.slots.length || draft.slots.length > 3
      || typeof draft.preferences !== 'object' || !draft.preferences) return null;
  return draft;
}
export const saveDraft = (draft: Draft) => write(DRAFT_KEY, draft);
export function clearDraft() { try { window.localStorage.removeItem(DRAFT_KEY); } catch { /* nothing kept */ } }

interface CachedImport { key: string; at: number; result: ImportResult }
// Results from an older API revision miss newer fields, so the revision is part of the key.
// The recovery source is part of the key, so switching providers never replays the other provider's result.
const cacheKey = (body: ImportRequest) => JSON.stringify([API_REVISION, body.url ?? '', body.text ?? '', body.vin ?? '', body.recover ?? true, body.recovery_source ?? 'auto']);
const fresh = (entry: CachedImport) => Date.now() - entry.at < CACHE_TTL_MS;

// Imports can spend search/provider credits, so identical requests reuse a recent result.
export function cachedImport(body: ImportRequest): { result: ImportResult; at: number } | null {
  const entries = read<CachedImport[]>(CACHE_KEY);
  return (Array.isArray(entries) ? entries : []).find(entry => entry.key === cacheKey(body) && fresh(entry)) ?? null;
}
export function cacheImport(body: ImportRequest, result: ImportResult) {
  if (!result.candidate) return; // Failures are retried, never replayed.
  const key = cacheKey(body);
  const entries = read<CachedImport[]>(CACHE_KEY);
  const kept = (Array.isArray(entries) ? entries : []).filter(entry => entry.key !== key && fresh(entry));
  write(CACHE_KEY, [{ key, at: Date.now(), result }, ...kept].slice(0, CACHE_LIMIT));
}

const SOURCE_KEY = 'revrank.recoverySource.v1';
export function loadRecoverySource(): RecoverySource {
  const value = read<string>(SOURCE_KEY);
  return value === 'marketcheck' || value === 'search' ? value : 'auto';
}
export const saveRecoverySource = (source: RecoverySource) => write(SOURCE_KEY, source);
