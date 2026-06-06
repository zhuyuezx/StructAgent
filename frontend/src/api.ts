// HTTP client. All routes are proxied to the FastAPI backend by Vite
// (see vite.config.ts), so we can use relative URLs.

import type {
  ChatPlanBody,
  CriticBody,
  CriticResult,
  PlanBody,
  PlanResult,
  RepairBody,
  RunBody,
  RunPlanBody,
  RunPlanResult,
  RunPlanSegmentBody,
  RunResult,
  RunStepsBody,
  SaveToolBody,
  SceneGraph,
  SegmentResult,
  ToolDetail,
  ToolSummary,
  UiGraphResult,
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
  getUiGraph: () => request<UiGraphResult>('/ui-graph'),
  dedupeIcons: () =>
    request<UiGraphResult>('/ui-graph/dedupe', { method: 'POST' }),
  // Planner + orchestrator (Phase 2)
  plan: (body: PlanBody) =>
    request<PlanResult>('/plan', { method: 'POST', body: JSON.stringify(body) }),
  planChat: (body: ChatPlanBody) =>
    request<PlanResult>('/plan/chat', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runPlan: (body: RunPlanBody) =>
    request<RunPlanResult>('/run-plan', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runPlanSegment: (body: RunPlanSegmentBody) =>
    request<SegmentResult>('/run-plan/segment', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  critic: (body: CriticBody) =>
    request<CriticResult>('/critic', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  repair: (body: RepairBody) =>
    request<PlanResult>('/repair', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  screenshotUrl: (name: string) =>
    `${BASE}/screenshot/${encodeURIComponent(name)}`,
};
