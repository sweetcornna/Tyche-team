import type {
  Analysis,
  ArtifactInfo,
  ClaimMap,
  Doctor,
  ExperimentEvent,
  ExperimentsInfo,
  LedgerEntry,
  LibraryPaper,
  Lesson,
  LineageGraph,
  Meta,
  ModelsResponse,
  NewRunRequest,
  ProcessInfo,
  ReferencesInfo,
  RevisionRound,
  RunDetail,
  RunEvent,
  RunSummary,
  StageInfo,
  StageName,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the Tyche server. Is `tyche ui` still running?");
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText || "Request failed";
    try {
      const body = await res.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      } else if (body?.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

const enc = encodeURIComponent;
const run = (id: string) => `/api/runs/${enc(id)}`;

export const api = {
  meta: () => request<Meta>("/api/meta"),
  models: () => request<ModelsResponse>("/api/models"),
  runs: (archived = false) => request<{ runs: RunSummary[] }>(`/api/runs?archived=${archived}`).then((r) => r.runs),
  run: (id: string) => request<RunDetail>(run(id)),
  events: (id: string, since = 0, limit = 1000) =>
    request<{ events: RunEvent[]; next: number }>(`${run(id)}/events?since=${since}&limit=${limit}`),
  references: (id: string) => request<ReferencesInfo>(`${run(id)}/references`),
  experiments: (id: string) => request<ExperimentsInfo>(`${run(id)}/experiments`),
  experimentFile: (id: string, path: string) => request<string>(`${run(id)}/experiments/file?path=${enc(path)}`),
  analysis: (id: string) => request<Analysis>(`${run(id)}/analysis`),
  ledger: (id: string) => request<{ reflag_cap: number; entries: LedgerEntry[] }>(`${run(id)}/ledger`),
  report: (id: string) => request<string>(`${run(id)}/report`),
  log: (id: string, tail = 400) => request<{ lines: string[]; path: string | null }>(`${run(id)}/log?tail=${tail}`),
  artifacts: (id: string) => request<{ artifacts: ArtifactInfo[] }>(`${run(id)}/artifacts`).then((r) => r.artifacts),
  artifactText: (id: string, name: string, version: number, path?: string) =>
    request<string>(`${run(id)}/artifacts/${enc(name)}/${version}${path ? `?path=${enc(path)}` : ""}`),
  artifactDir: (id: string, name: string, version: number) =>
    request<{ files: { path: string; size: number }[] }>(`${run(id)}/artifacts/${enc(name)}/${version}`),
  claims: (id: string) => request<ClaimMap>(`${run(id)}/claims`),
  revisions: (id: string) => request<{ rounds: RevisionRound[] }>(`${run(id)}/revisions`),
  lineage: (id: string) => request<LineageGraph>(`${run(id)}/lineage`),
  environment: (id: string) => request<Record<string, unknown>>(`${run(id)}/environment`),
  create: (body: NewRunRequest) =>
    request<{ run_id: string; process: ProcessInfo }>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  /** `stage` reruns exactly one stage; `from_stage` reruns that stage and everything after it. */
  resume: (id: string, body: ResumeRequest) =>
    request<{ run_id: string; process: ProcessInfo }>(`${run(id)}/resume`, { method: "POST", body: JSON.stringify(body) }),
  stop: (id: string) => request<{ stopping: boolean }>(`${run(id)}/stop`, { method: "POST", body: "{}" }),
  patch: (id: string, body: { title?: string; pinned?: boolean; archived?: boolean }) =>
    request<RunSummary>(run(id), { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => request<{ trashed: string }>(run(id), { method: "DELETE" }),
  library: () => request<{ papers: LibraryPaper[] }>("/api/library").then((r) => r.papers),
  lessons: () => request<{ lessons: Lesson[] }>("/api/lessons").then((r) => r.lessons),
  doctor: () => request<Doctor>("/api/doctor"),
  saveEnv: (values: Record<string, string>, secrets: Record<string, string>) =>
    request<Meta>("/api/settings/env", { method: "PUT", body: JSON.stringify({ values, secrets }) }),
};

export interface ResumeRequest {
  stage?: StageName | null;
  from_stage?: StageName | null;
  stop_after?: StageName | null;
  allow_gate_failures?: boolean;
  /** Replaces the operator notes the planner sees (only read when planning reruns). */
  notes?: string | null;
}

export const files = {
  paper: (id: string) => `${run(id)}/files/paper.pdf`,
  thumb: (id: string) => `${run(id)}/files/paper-thumb.png`,
  figure: (id: string) => `${run(id)}/files/figure.png`,
  bundle: (id: string) => `${run(id)}/files/bundle.zip`,
};

export type StreamHandlers = {
  summary?: (s: RunSummary & { stages: StageInfo[] }) => void;
  event?: (e: RunEvent) => void;
  experiment?: (e: ExperimentEvent) => void;
  status?: (connected: boolean) => void;
};

/** Subscribe to a run's SSE stream; reconnects with backoff. Returns an unsubscribe function. */
export function subscribeRun(id: string, since: number, handlers: StreamHandlers): () => void {
  let source: EventSource | null = null;
  let closed = false;
  let retry = 1000;
  let cursor = since;
  let timer: number | undefined;

  const connect = () => {
    if (closed) return;
    source = new EventSource(`${run(id)}/stream?since=${cursor}`);
    source.onopen = () => {
      retry = 1000;
      handlers.status?.(true);
    };
    // One malformed frame must not throw inside the EventSource callback and stall the stream.
    const parsed = <T,>(e: Event): T | undefined => {
      try {
        return JSON.parse((e as MessageEvent).data) as T;
      } catch {
        return undefined;
      }
    };
    source.addEventListener("summary", (e) => {
      const data = parsed<RunSummary & { stages: StageInfo[] }>(e);
      if (data) handlers.summary?.(data);
    });
    source.addEventListener("event", (e) => {
      const data = parsed<RunEvent>(e);
      if (!data) return;
      cursor = Math.max(cursor, data.seq + 1);
      handlers.event?.(data);
    });
    source.addEventListener("experiment", (e) => {
      const data = parsed<ExperimentEvent>(e);
      if (data) handlers.experiment?.(data);
    });
    source.onerror = () => {
      handlers.status?.(false);
      source?.close();
      if (closed) return;
      timer = window.setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    };
  };
  connect();
  return () => {
    closed = true;
    if (timer) window.clearTimeout(timer);
    source?.close();
  };
}
