import type { CommandResult, EffectMode, Layout, NodeView, OtaJob } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      // The status text is the useful fallback.
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  login: (password: string) =>
    request<{ status: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ status: string }>("/api/v1/auth/logout", { method: "POST" }),
  nodes: () => request<NodeView[]>("/api/v1/nodes"),
  layout: () => request<Layout>("/api/v1/layout"),
  saveLayout: (layout: Layout) =>
    request<Layout>("/api/v1/layout", { method: "PUT", body: JSON.stringify(layout) }),
  effect: (nodeIds: string[], mode: EffectMode, periodMs: number, brightness: number) =>
    request<CommandResult>("/api/v1/effects", {
      method: "POST",
      body: JSON.stringify({ node_ids: nodeIds, mode, period_ms: periodMs, brightness }),
    }),
  allOff: () => request<CommandResult>("/api/v1/all-off", { method: "POST" }),
  ota: (firmware: File, targets: string[], version: string) => {
    const body = new FormData();
    body.append("firmware", firmware);
    body.append("targets", JSON.stringify(targets));
    body.append("version", version);
    return request<{ job_id: string; sha256: string; size: number; state: string }>("/api/v1/ota", {
      method: "POST",
      body,
    });
  },
  otaJob: (id: string) => request<OtaJob>(`/api/v1/ota/${id}`),
};

