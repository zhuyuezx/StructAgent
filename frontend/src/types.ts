// Shared types — mirror the Pydantic models in core/api.py.

export interface ToolSummary {
  name: string;
  level: number;
  params: string[];
  needs_ui_graph: boolean;
  description: string;
  is_leaf: boolean;
  children: string[];
  has_json: boolean;
}

export interface StepDef {
  tool: string;
  params: Record<string, unknown>;
}

export interface ToolDetail extends ToolSummary {
  steps?: StepDef[] | null;
  python_fn?: string | null;
  raw_definition?: Record<string, unknown> | null;
}

export interface SaveToolBody {
  name: string;
  description: string;
  params: string[];
  needs_ui_graph: boolean;
  steps: StepDef[];
  overwrite?: boolean;
}

export interface RunBody {
  params: Record<string, unknown>;
  countdown?: number;
}

export interface RunStepsBody {
  steps: StepDef[];
  params: Record<string, unknown>;
  countdown?: number;
}

export interface RunResult {
  status: string;
  tool: string | null;
  result: Record<string, unknown>;
  scene_graph: SceneGraph;
}

export interface SceneObject {
  id: string;
  type: string;
  label: string;
  bbox: [number, number, number, number] | null;
  selected: boolean;
}

export interface SceneEdge {
  id: string;
  source: string;
  target: string;
  source_anchor: string;
  target_anchor: string;
  label: string;
}

export interface SceneGraph {
  version: number;
  objects: SceneObject[];
  edges: SceneEdge[];
  metadata: { op_count: number; last_op: string | null };
}
