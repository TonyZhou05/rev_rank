import type { Candidate, Health, ImportRequest, ImportResult, Preferences, Report, ReportSummary, SourceInfo } from './types';

// Must match API_REVISION in backend/app/main.py.
export const API_REVISION = 2;

export class ApiError extends Error {
  constructor(message: string, public result: Partial<ImportResult>) { super(message); }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), body ? 120_000 : 20_000);
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
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('The request timed out. Your draft is intact. Please try again; check saved reports before regenerating a report.');
    if (error instanceof TypeError) throw new Error('Could not reach the RevRank API. Check your connection and that the backend is running on port 8000.');
    throw error;
  } finally { window.clearTimeout(timer); }
}

export const api = {
  health: () => request<Health>('/health'),
  sources: () => request<SourceInfo>('/sources'),
  demo: () => request<{ candidates: Candidate[] }>('/demo'),
  import: (body: ImportRequest) => request<ImportResult>('/import', body),
  compare: (candidates: Candidate[], preferences: Preferences) => request<Report>('/compare', { candidates, preferences }),
  reports: () => request<{ reports: ReportSummary[] }>('/reports'),
  report: (id: string) => request<Report>(`/reports/${encodeURIComponent(id)}`),
};
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : 'An unexpected error occurred. Please try again.'; }
