import type { Candidate, ConstraintResult, Health, ImportRequest, ImportResult, Preferences, Report, ReportSummary, SourceInfo } from './types';

// Must match API_REVISION in backend/app/main.py.
export const API_REVISION = 7;

export class ApiError extends Error {
  constructor(message: string, public result: Partial<ImportResult>) { super(message); }
}

// Every API exchange, newest first, for the on-page inspector.
export interface ApiLogEntry {
  id: number; at: string; method: string; endpoint: string; request?: unknown;
  status: number | 'pending' | 'network error' | 'cached'; ms?: number; response?: unknown; note?: string;
}
let log: ApiLogEntry[] = [];
let nextId = 1;
const listeners = new Set<(entries: ApiLogEntry[]) => void>();
const publish = () => listeners.forEach(listener => listener(log));
export const apiLog = {
  entries: () => log,
  subscribe(listener: (entries: ApiLogEntry[]) => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  clear() { log = []; publish(); },
  add(entry: Omit<ApiLogEntry, 'id' | 'at'>) {
    const full = { ...entry, id: nextId++, at: new Date().toISOString() };
    log = [full, ...log].slice(0, 40); publish(); return full.id;
  },
  update(id: number, patch: Partial<ApiLogEntry>) { log = log.map(e => e.id === id ? { ...e, ...patch } : e); publish(); },
};

async function request<T>(path: string, body?: unknown, timeoutMs?: number, external?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const limit = timeoutMs ?? (body ? 120_000 : 20_000);
  let timedOut = false;
  const onExternal = () => controller.abort('cancel');
  if (external) {
    if (external.aborted) controller.abort('cancel');
    else external.addEventListener('abort', onExternal, { once: true });
  }
  // Local flag — abort reason is not reliably visible on the thrown AbortError in all browsers.
  const timer = window.setTimeout(() => { timedOut = true; controller.abort('timeout'); }, limit);
  const started = performance.now();
  const entry = apiLog.add({ method: body === undefined ? 'GET' : 'POST', endpoint: `/api${path}`, request: body, status: 'pending' });
  try {
    const response = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw new Error(`The API returned ${response.status} without JSON. Check that the RevRank backend is running on port 8000.`);
    }
    const data = await response.json();
    apiLog.update(entry, { status: response.status, ms: Math.round(performance.now() - started), response: data });
    if (!response.ok) {
      const items: { loc?: string[]; msg?: string; type?: string }[] = Array.isArray(data.detail) ? data.detail : [];
      let detail = typeof data.detail === 'string' ? data.detail
        : items.length ? items.map(item => `${item.loc?.join('.') ?? 'Input'}: ${item.msg ?? 'invalid value'}`).join('; ')
        : data.detail?.message || data.message || response.statusText;
      // The page only sends fields it knows; rejecting one means the API process predates this page.
      if (items.some(item => item.type === 'extra_forbidden')) detail += '. The running backend is older than this page: restart scripts/dev.py.';
      // Some servers return import diagnostics inside an HTTP error detail object.
      const diagnostics = data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail) ? { ...data, ...data.detail } : data;
      throw new ApiError(`${response.status}: ${detail}`, diagnostics);
    }
    return data as T;
  } catch (error) {
    const aborted = (error instanceof DOMException && error.name === 'AbortError')
      || (error instanceof Error && error.name === 'AbortError');
    if (aborted) {
      const secs = Math.round(limit / 1000);
      const msg = timedOut || controller.signal.reason === 'timeout'
        ? (path === '/compare'
          ? `Timed out after ${secs}s — try again. Your draft is intact.`
          : `The request timed out after ${secs}s. Your draft is intact — please try again.`)
        : (path === '/compare'
          ? 'Report build cancelled. Your draft is intact.'
          : 'The request was cancelled. Your draft is intact.');
      apiLog.update(entry, { status: 'network error', ms: Math.round(performance.now() - started), note: msg });
      throw new Error(msg);
    }
    if (!(error instanceof ApiError)) apiLog.update(entry, { status: 'network error', ms: Math.round(performance.now() - started), note: error instanceof Error ? error.message : String(error) });
    if (error instanceof TypeError) throw new Error('Could not reach the RevRank API. Check your connection and that the backend is running on port 8000.');
    throw error;
  } finally {
    window.clearTimeout(timer);
    if (external) external.removeEventListener('abort', onExternal);
  }
}

export const api = {
  health: () => request<Health>('/health'),
  sources: () => request<SourceInfo>('/sources'),
  demo: () => request<{ candidates: Candidate[] }>('/demo'),
  import: (body: ImportRequest) => request<ImportResult>('/import', body),
  // Free-form constraints to validated preferences. The server maps language onto the preference
  // schema only and never returns a vehicle fact, so one transport retry is safe here: it cannot
  // duplicate anything or spend a paid listing lookup.
  constraints: async (message: string, preferences: Preferences) => {
    for (let attempt = 0; ; attempt++) {
      try {
        return await request<ConstraintResult>('/constraints', { message, preferences }, 45_000);
      } catch (error) {
        const unreachable = error instanceof Error && error.message.startsWith('Could not reach');
        if (attempt >= 1 || !unreachable) throw error;
        await new Promise(resolve => window.setTimeout(resolve, 1200));
      }
    }
  },
  // Client abort sits just above health.compare_timeout_seconds (App passes the ms); fallback 90s.
  compare: (candidates: Candidate[], preferences: Preferences, signal?: AbortSignal, timeoutMs = 90_000) =>
    request<Report>('/compare', { candidates, preferences }, timeoutMs, signal),
  reports: () => request<{ reports: ReportSummary[] }>('/reports'),
  report: (id: string) => request<Report>(`/reports/${encodeURIComponent(id)}`),
};
export function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    // Prefer the server detail string over a bare "503: …" status wrapper.
    const stripped = error.message.replace(/^\d{3}:\s*/, '').trim();
    return stripped || error.message;
  }
  return error instanceof Error ? error.message : 'An unexpected error occurred. Please try again.';
}

/** Client compare abort budget: a few seconds above the server limit so a 200 timed-out report wins the race. */
export function compareClientTimeoutMs(serverSeconds?: number | null) {
  const server = typeof serverSeconds === 'number' && serverSeconds > 0 ? serverSeconds : 85;
  return Math.round((server + 5) * 1000);
}
