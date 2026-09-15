
export type RecoveryStatus =
  | 'recovered' | 'identity_only' | 'identity_conflict' | 'not_found'
  | 'not_listing' | 'failed' | 'disabled' | 'unavailable';

export interface NHTSARecall {
  campaign_number: string; component: string; summary: string;
  consequence?: string | null; remedy?: string | null; report_date?: string | null;
  url?: string | null;
}
// NHTSA has no stable permalink per ODI number, so `url` is usually absent for complaints.
export interface NHTSAComplaint {
  odi_number: string; component: string; summary: string;
  crash?: boolean; fire?: boolean; injuries?: number; deaths?: number; date_filed?: string | null;
  url?: string | null;
}
export interface NHTSARating {
  overall_rating?: number | null; frontal_crash?: number | null;
  side_crash?: number | null; rollover?: number | null;
}
// Model-year scope only — never treat as VIN-specific.
// PR #2 wire shape (primary); optional nested fields kept for forward-compat.
export interface NHTSASafetyData {
  scope?: string;
  scope_label?: string;
  year?: number | null;
  make?: string | null;
  model?: string | null;
  recalls_count?: number | null;
  complaints_count?: number | null;
  recall_count?: number | null;
  complaint_count?: number | null;
  overall_rating?: string | number | null;
  frontal_rating?: string | number | null;
  side_rating?: string | number | null;
  rollover_rating?: string | number | null;
  rating?: NHTSARating | null;
  recalls?: NHTSARecall[];
  complaints?: NHTSAComplaint[];
  // Model-year pages for the clickable counts: a trim deep link with a #recalls / #complaints tab
  // anchor when NHTSA gave us a body style and drive type, else the year/make/model search landing.
  recalls_url?: string | null;
  complaints_url?: string | null;
}

// A search URL the backend constructed from the dealer's own name and place. RevRank does not read
// or score what these pages say, so there is never a rating to render beside them.
export interface DealerLink { label: string; url: string; note?: string }
// The selling business as the licensed listing reported it — business level, never VIN level.
// Every field can be null: an absent one means the record did not carry it, not that it is unknown
// to the dealer. `maps_url` is a Google Maps search over the reported text, never a coordinate pin.
export interface DealerInfo {
  scope?: string;
  name?: string | null;
  website?: string | null;
  phone?: string | null;
  street?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  address?: string | null;
  vehicle_location?: string | null;
  maps_url?: string | null;
  vdp_url?: string | null;
  source_domain?: string | null;
  source?: string;
  notes?: string[];
  links?: DealerLink[];
}

// One search excerpt about the dealer, as the search provider returned it. RevRank never opens
// these pages, and review platforms are filtered out server-side, so no rating reaches this shape.
export interface DealerSignal {
  id: string;
  // official: a public body's own page (attorney general, DMV, licensing board, FTC).
  // news: a dated, attributable article. Review and complaint platforms stay link-outs, not signals.
  category: 'official' | 'news';
  label: string;
  url: string;
  host: string;
  excerpt: string;
  // How the excerpt reads: a concluded action, an allegation, or neither. Never upgraded.
  nature?: 'action' | 'allegation' | 'unclear';
  published?: string | null;
  query?: string;
}
// Cited dealer flags plus the excerpts they came from. Never a score: `green`/`red` are capped,
// cited sentences, and `status` explains an empty result instead of implying a clean record.
export interface DealerSignals {
  scope?: string;
  status: 'complete' | 'partial' | 'unavailable' | 'disabled';
  message?: string;
  dealer_name?: string | null;
  model?: string;
  searches: number;
  credits: number;
  signals?: DealerSignal[];
  green?: Claim[];
  red?: Claim[];
  caveats?: string[];
  dropped_claims?: number;
}

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
  // Original MSRP: buyer-entered, or decoded from a known VIN by MarketCheck NeoVIN; never invented.
  msrp?: number | null;
  // Derived at compare: (price/msrp)*100; NOT user-editable. Prefer API value when present.
  percent_of_msrp?: number | null;
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
  // Days on market from licensed inventory when already fetched; never invented.
  dom?: number | null;
  dom_active?: number | null;
  first_seen_at?: string | null;
  nhtsa_safety?: NHTSASafetyData | null;
  // Dealer contact details from the licensed inventory record; null on every other import path.
  dealer?: DealerInfo | null;
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
  // Odometer ceiling in the listing's own unit; null means no ceiling.
  max_mileage?: number | null;
  transmission?: 'manual' | 'automatic' | null;
  // Things the buyer rules out. A silent listing is never counted as passing one of these.
  excludes?: string[];
}
// Which preference field the constraint chat wrote. Never a listing fact.
export type ConstraintField = 'budget' | 'annual_mileage' | 'ownership_years' | 'max_mileage'
  | 'transmission' | 'location' | 'must_haves' | 'excludes' | 'priorities';
export interface Constraint {
  field: ConstraintField;
  label: string;
  value: string;
  // The buyer's own contiguous phrase behind the value; the backend requires it for LLM mappings.
  quote: string;
  source: 'rules' | 'llm';
}
export interface ConstraintResult {
  mode: 'llm' | 'rules';
  preferences: Preferences;
  constraints: Constraint[];
  // Composed by the backend from the accepted constraints, never model prose.
  reply: string;
  unmapped: string[];
  notes: string[];
}
export interface ConstraintCheck {
  field: ConstraintField;
  constraint: string;
  // 'not_established' means the listing is silent, which is never shown as a "no".
  status: 'meets' | 'conflicts' | 'not_established' | 'unknown';
  detail: string;
}
export interface ShortlistEntry {
  candidate_id: string;
  position: number;
  meets: number;
  conflicts: number;
  open_items: number;
  checks: ConstraintCheck[];
  rationale: string;
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
  // True when any make/model differs; backend will set; FE computes until then.
  cross_model?: boolean;
  // Optional map from candidate id → model-year NHTSA block (PR #1).
  nhtsa_data?: Record<string, NHTSASafetyData | null>;
  // Optional map from candidate id → search-derived dealer flags; absent when no car has a dealer.
  dealer_signals?: Record<string, DealerSignals | null>;
  // Deterministic constraint-fit order, and what the cited re-rank falls back to.
  shortlist?: ShortlistEntry[];
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
  // Present only when the model ordered every car and every position passed the citation gate.
  ranking?: { candidate_id: string; position: number; claim: Claim }[];
  sources: SourceRef[];
  tool_calls: number;
  dropped_claims: number;
}
export interface ReportSummary { id: string; title: string; created_at: string; analysis_mode: 'llm' | 'rules' }
export interface ImportResult {
  attempts?: ImportAttempt[];
  recovery_status?: RecoveryStatus | null;
  status: 'success' | 'partial' | 'restricted' | 'unsupported' | 'blocked' | 'failed';
  candidate: Candidate | null;
  message: string;
}
export interface SourceInfo { sources: { domain: string; name: string; status: string; reason: string }[]; live_fetch_enabled: boolean }
// llm_model and llm_endpoint_host name the configured model; the API key never leaves the server.
export interface Health { status: string; api_revision?: number; llm_enabled: boolean; llm_model?: string; llm_endpoint_host?: string; market_enabled: boolean; search_enabled?: boolean; search_provider?: string; licensed_inventory_enabled?: boolean; vin_decode_enabled?: boolean; neovin_msrp_enabled?: boolean; compare_timeout_seconds?: number; usage?: Record<string, ProviderUsage> }
export interface ProviderUsage { used: number; limit: number; unit: string; month: string }
export interface ImportSlot {
  id: string;
  url: string;
  text: string;
  vin: string;
  recover: boolean;
  attempts?: ImportAttempt[];
  recovery_status?: RecoveryStatus | null;
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
