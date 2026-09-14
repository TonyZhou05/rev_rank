export type EvidenceStatus = 'seller_claim' | 'user_confirmed' | 'extracted' | 'synthetic';
export interface Evidence { value: string; source: string; status: EvidenceStatus }
export interface Observation {
  field: string; value: string; source_url: string; retrieved_at: string;
  observed_at: string | null; method: 'search' | 'direct' | 'licensed' | 'registry'; vin: string | null;
}
export interface ImportAttempt { method: string; status: string; detail: string }
// Debug switch for which paid recovery provider the server may call; omitted means "auto".
export type RecoverySource = 'auto' | 'marketcheck' | 'search';
export interface ImportRequest { url?: string; text?: string; vin?: string; recover?: boolean; recovery_source?: Exclude<RecoverySource, 'auto'> }
export interface Candidate {
  retrieval_method?: 'direct' | 'search' | 'licensed' | 'registry' | 'paste' | 'synthetic';
  observations?: Observation[];
  conflicts?: string[];
  id: string;
  title: string;
  make: string | null;
  model: string | null;
  trim: string | null;
  generation: string | null;
  year: number | null;
  price: number | null;
  currency: string;
  mileage: number | null;
  mileage_unit: 'mi' | 'km';
  transmission: string | null;
  // Build details (often from the NHTSA VIN decode); absent in drafts saved by older versions.
  body?: string | null;
  engine?: string | null;
  drivetrain?: string | null;
  fuel_type?: string | null;
  location: string | null;
  features: string[];
  history: string | null;
  source_url: string | null;
  source_kind: 'synthetic' | 'user' | 'listing';
  evidence: Record<string, Evidence>;
  warnings: string[];
  verified_fields: string[];
}
export interface Preferences {
  budget: number | null;
  annual_mileage: number;
  ownership_years: number;
  location: string;
  priorities: string[];
  must_haves: string[];
}
export interface Report {
  id: string;
  created_at: string;
  title: string;
  summary: string;
  analysis_mode: 'llm' | 'rules';
  preferences: Preferences;
  candidates: Candidate[];
  findings: { title: string; detail: string; candidate_ids: string[]; evidence_fields: string[] }[];
  metrics: { label: string; values: string[] }[];
  questions: { candidate_id: string; questions: string[] }[];
  market: { status: string; message: string; comparables: Record<string, unknown>[] };
  warnings: string[];
  ai_analysis?: AIAnalysis | null;
}
export interface Claim { text: string; citations: string[] }
export interface SourceRef { id: string; label: string; url: string | null; detail: string }
export interface AIAnalysis {
  status: 'complete' | 'partial' | 'unavailable';
  message: string;
  model: string;
  verdict: Claim | null;
  vehicles: { candidate_id: string; summary: Claim | null; strengths: Claim[]; risks: Claim[] }[];
  comparisons: { topic: string; claim: Claim; favors: string | null }[];
  questions: { candidate_id: string; text: string }[];
  sources: SourceRef[];
  tool_calls: number;
  dropped_claims: number;
}
export interface ReportSummary { id: string; title: string; created_at: string; analysis_mode: 'llm' | 'rules' }
export interface ImportResult {
  attempts?: ImportAttempt[];
  recovery_status?: string | null;
  status: 'success' | 'partial' | 'restricted' | 'unsupported' | 'blocked' | 'failed';
  candidate: Candidate | null;
  message: string;
}
export interface SourceInfo { sources: { domain: string; name: string; status: string; reason: string }[]; live_fetch_enabled: boolean }
export interface Health { status: string; api_revision?: number; llm_enabled: boolean; market_enabled: boolean; search_enabled?: boolean; search_provider?: string; licensed_inventory_enabled?: boolean; vin_decode_enabled?: boolean; usage?: Record<string, ProviderUsage> }
export interface ProviderUsage { used: number; limit: number; unit: string; month: string }
export interface ImportSlot {
  id: string;
  url: string;
  text: string;
  vin: string;
  recover: boolean;
  attempts?: ImportAttempt[];
  recovery_status?: string | null;
  candidate: Candidate | null;
  status?: ImportResult['status'];
  message?: string;
  // When the shown result came from the local import cache instead of a new request.
  cachedAt?: number;
  // Re-opens the input form for a slot that already holds a vehicle.
  editing?: boolean;
  // The last raw /api/import exchange for this car, shown for debugging.
  raw?: { request: unknown; status: number | string; response: unknown };
}
export type Step = 'import' | 'review' | 'report';
