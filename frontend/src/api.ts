// HTTP client. All routes are proxied to the FastAPI backend by Vite
// (see vite.config.ts), so we can use relative URLs.

import type {
  RunBody,
  RunResult,
  RunStepsBody,
  SaveToolBody,
  SceneGraph,
  ToolDetail,
  ToolSummary,
} from './types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail: string;
    try {
      detail = (await res.json()).detail ?? res.statusText;
    } catch {
      detail = res.statusText;
    }
    throw new Error(`${res.status} ${detail}`);
  }
  // 204 / empty body
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export interface ReloadResult {
  added: string[];
  removed: string[];
  total: number;
  tools: ToolSummary[];
}

export const api = {
  listTools: () => request<ToolSummary[]>('/tools'),
  reloadTools: () =>
    request<ReloadResult>('/reload-tools', { method: 'POST' }),
  getTool: (name: string) =>
    request<ToolDetail>(`/tools/${encodeURIComponent(name)}`),
  saveTool: (body: SaveToolBody) =>
    request<ToolDetail>('/tools', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  deleteTool: (name: string) =>
    request<{ status: string; deleted: string }>(
      `/tools/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
  runTool: (name: string, body: RunBody) =>
    request<RunResult>(`/tools/${encodeURIComponent(name)}/run`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runSteps: (body: RunStepsBody) =>
    request<RunResult>('/run-steps', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getSceneGraph: () => request<SceneGraph>('/scene-graph'),
  resetSceneGraph: () =>
    request<SceneGraph>('/scene-graph/reset', { method: 'POST' }),
  getUiGraph: () =>
    request<{ domain: string; sidebar_shapes: string[] }>('/ui-graph'),
};
