// Types for the `tyche ui` JSON API (tyche/web/server.py). Keep in sync with the server contract.

export type StageName = "plan" | "survey" | "experiments" | "analysis" | "write" | "review" | "evolve" | "package";
export type StageStatus = "pending" | "running" | "done" | "failed";
export type RunStatus = "running" | "paused" | "done" | "failed" | "stopped" | "pending";
export type Direction = "context_engineering" | "memory_engine" | "self_evolution";

export interface ModelPublic {
  role: string;
  provider: string;
  model_name: string;
  api_base: string;
  api_key_env: string;
  temperature: number | null;
  max_tokens: number | null;
  extra_body: Record<string, unknown>;
  cache: string;
  cache_retention: string;
  context_window: number;
}

export interface DirectionPreset {
  name: Direction;
  title: string;
  summary: string;
  experiment_families: { name: string; description: string; metrics: string[] }[];
  angle_hints: string[];
}

export interface Meta {
  version: string;
  workspace: string;
  env_file: string | null;
  stages: StageName[];
  directions: DirectionPreset[];
  defaults: { engine: string; review_max_rounds: number; max_main_pages: number };
  roles: Record<string, ModelPublic>;
  model: {
    model_name: string;
    provider: string;
    api_base: string;
    context_window: number;
    max_tokens: number | null;
    timeout: number;
    reasoning_effort: string | null;
  };
  keys: Record<string, boolean>;
  env: Record<string, string>;
  reasoning_levels: string[];
}

export interface ModelInfo {
  id: string;
  context_length?: number | null;
  max_completion_tokens?: number | null;
  owned_by?: string | null;
}

export interface ModelsResponse {
  models: ModelInfo[];
  source: "endpoint" | "config";
  error: string | null;
}

export interface ProcessInfo {
  pid: number;
  started_at: string;
  source: "web" | "cli";
}

export interface RunSummary {
  run_id: string;
  title: string;
  topic: string;
  direction: Direction | string;
  created_at: string;
  updated_at: string;
  status: RunStatus;
  stage: StageName | null;
  stages_done: number;
  stages_total: number;
  method: string | null;
  synthetic: boolean;
  has_paper: boolean;
  composite: number | null;
  unverified: boolean;
  pinned: boolean;
  archived: boolean;
  process: ProcessInfo | null;
}

export interface StageInfo {
  name: StageName;
  status: StageStatus;
  running_at: string | null;
  done_at: string | null;
  duration_s: number | null;
  summary: Record<string, unknown>;
  error: string | null;
}

export interface UsageRow {
  calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  uncached_input_tokens: number;
  cache_hit_rate: number;
  calls_without_cache_report: number;
  prefix_reuse_rate: number;
  cache_breaks: number;
}

export interface Plan {
  working_title: string;
  problem: string;
  motivation: string;
  research_questions: string[];
  hypotheses: { statement: string; prediction: string }[];
  method_name: string;
  method_sketch: string;
  baselines: string[];
  experiment_family: string;
  task_description: string;
  metrics: string[];
  contributions: string[];
  scope_limits: string[];
  keywords: string[];
  search_queries: string[];
}

export type Dimension =
  | "originality"
  | "importance"
  | "claims_supported"
  | "experimental_soundness"
  | "clarity"
  | "community_value"
  | "contextualization";

export interface ReviewRound {
  round: number;
  accepted: boolean;
  composite: number;
  overall: number;
  dimensions: Record<Dimension, number>;
  delta?: number;
  gates_passed: boolean;
  blockers: number;
  sections_revised?: string[];
  findings_addressed?: string[];
  build?: { compiled: boolean; pages: number; main_pages: number; gates_passed: boolean; blockers: number };
}

export interface ReviewerReport {
  scores: Record<Dimension, number>;
  overall: number;
  confidence: number;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  findings: unknown[];
}

export interface GateFinding {
  gate: string;
  severity: "blocker" | "major" | "minor";
  section: string;
  message: string;
  context?: string;
}

export interface Gates {
  passed: boolean;
  stats: Record<string, unknown>;
  findings: GateFinding[];
}

export interface PaperInfo {
  url: string;
  thumb_url: string;
  source: "package" | "review";
  unverified: boolean;
  main_pages: number | null;
  title: string | null;
}

export interface RunDetail extends RunSummary {
  stages: StageInfo[];
  config: {
    engine: string;
    review_max_rounds: number;
    max_main_pages: number;
    roles: Record<string, ModelPublic>;
  } | null;
  plan: Plan | null;
  notes: string | null;
  usage: { total: UsageRow; by_stage: Record<string, UsageRow>; by_model: Record<string, Partial<UsageRow>> } | null;
  review: { rounds: ReviewRound[]; reviews: Record<string, ReviewerReport>; stop_reason: string | null } | null;
  gates: Gates | null;
  paper: PaperInfo | null;
}

export interface RunEvent {
  seq: number;
  at: string;
  kind: string;
  [key: string]: unknown;
}

export interface ExperimentEvent {
  attempt: string;
  ts: string;
  event: string;
  module?: string;
  round?: number;
  outcome?: string;
}

export interface ExperimentsInfo {
  engine: string;
  status: "running" | "completed" | "failed" | "pending";
  synthetic: boolean;
  variants: string[];
  notes: string;
  design_md: string | null;
  attempts: string[];
  timeline: ExperimentEvent[];
  live: {
    attempt: string;
    module: string;
    round: number;
    model_calls: number;
    since: string;
    last_event_at: string;
  } | null;
  metrics: Record<string, Record<string, number>>;
  files: { path: string; size: number }[];
  files_root: "artifact" | "live" | null;
  reflections: { name: string; text: string }[];
}

export interface Reference {
  key: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string;
  url: string;
  doi: string;
  arxiv_id: string;
  citation_count: number | null;
  role: string;
  relevance: number;
  sources: string[];
  abstract: string;
  cited: boolean;
  cards: { claim: string; quote: string }[];
}

export interface ReferencesInfo {
  papers: Reference[];
  excluded: unknown[];
  stats: Record<string, unknown>;
  synthesis: Record<string, unknown>;
}

export interface MetricStat {
  value: number;
  n?: number;
  mean?: number;
  std?: number;
  ci_low?: number;
  ci_high?: number;
}

export interface Comparison {
  metric: string;
  proposed: string;
  baseline: string;
  n: number;
  diff: number;
  ci_low: number | null;
  ci_high: number | null;
  p_value: number | null;
  relative: number | null;
  better: boolean;
}

export interface Analysis {
  confidence: number;
  proposed: string;
  baselines: string[];
  metrics: string[];
  lower_is_better: Record<string, boolean>;
  variants: Record<string, Record<string, MetricStat>>;
  comparisons: Comparison[];
  figure_url?: string;
}

export interface LedgerEntry {
  id: string;
  round_opened: number;
  source: string;
  severity: "blocker" | "major" | "minor";
  dimension: string;
  section: string;
  quote: string;
  problem: string;
  fix: string;
  close_criterion: string;
  status: "open" | "resolved" | "wontfix" | "unaddressed";
  reflags: number;
  response: string;
  history: string[];
  revision_accepted?: boolean;
  score_delta?: number;
}

export interface ArtifactVersion {
  version: number;
  id: string;
  stage: string;
  sha256: string;
  path: string;
  size: number;
  created_at: string;
}

export interface ArtifactInfo {
  name: string;
  kind: "json" | "md" | "bib" | "tex" | "pdf" | "dir" | "other";
  versions: ArtifactVersion[];
}

export interface LibraryPaper {
  run_id: string;
  title: string;
  direction: string;
  created_at: string;
  updated_at: string;
  composite: number | null;
  main_pages: number | null;
  unverified: boolean;
  synthetic: boolean;
  gates_passed: boolean | null;
  pdf_url: string;
  thumb_url: string;
}

export interface Lesson {
  id: string;
  status: "candidate" | "active" | "retired" | string;
  category: string;
  guidance: string;
  sections: string[];
  runs: number;
  helped: number;
  misses: number;
  created_at: string;
  updated_at: string;
}

export interface Doctor {
  tools: Record<string, string | null>;
  openjiuwen: boolean;
  reference_docs: boolean;
  keys: Record<string, boolean>;
  roles: Record<string, { model_name: string; api_base: string; cache_profile: string; cache_note: string }>;
  sources: Record<string, string>;
}

// --- Traceability layer (tyche/trace) ---

export type ClaimStatus = "verified" | "weak" | "unverified";

export interface ClaimNumber {
  text: string;
  percent: boolean;
  match: {
    label: string;
    value: number;
    kind: string;
    variant: string | null;
    metric: string | null;
    stat: string | null;
    comparison: Record<string, unknown> | null;
    source: "analysis" | "setup" | string;
    metrics_file: string | null;
  } | null;
  /** Other registered values the number also rounds to, best-ranked first. */
  alternatives?: string[];
  /** The attribution is a guess: equally ranked values differ, or only a fraction x 100 fits. */
  ambiguous?: boolean;
}

export interface ClaimCitation {
  key: string;
  known: boolean;
  title: string | null;
  year: number | null;
  url: string | null;
  cards: { claim: string; quote: string }[];
  carded: boolean;
}

export interface Claim {
  id: string;
  section: string;
  sentence: string;
  latex: string;
  kind: "numeric" | "citation" | "mixed";
  status: ClaimStatus;
  numbers: ClaimNumber[];
  citations: ClaimCitation[];
}

export interface ClaimMap {
  version: number;
  stats: {
    claims: number;
    verified: number;
    weak: number;
    unverified: number;
    numbers: number;
    numbers_matched: number;
    citations: number;
    citations_carded: number;
  };
  claims: Claim[];
}

export interface RevisionRound {
  round: number;
  accepted: boolean;
  composite: number | null;
  delta: number | null;
  note?: string;
  sections: { name: string; before_words: number; after_words: number; diff: string }[];
  findings: Partial<LedgerEntry>[];
}

export interface LineageGraph {
  nodes: { id: string; name: string; version: number; stage: string; sha256: string; path: string; latest: boolean }[];
  edges: { from: string; to: string; kind: "input" | "parent" }[];
  stages: string[];
}

export interface NewRunRequest {
  topic: string;
  direction: Direction;
  notes: string;
  run_id: string | null;
  stop_after: StageName | null;
  engine: string | null;
  results_dir: string | null;
  model: {
    model_name: string | null;
    reasoning_effort: string | null;
    max_tokens: number | null;
    timeout: number | null;
    reviewer_model: string | null;
  };
  settings: { review_max_rounds: number | null; max_main_pages: number | null };
}
