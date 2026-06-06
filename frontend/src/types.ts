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

// === Planner + checkpoints (Phase 2) ======================================

export interface Assertion {
  check: string;
  op?: string;
  value?: unknown;
  label?: string;
  id?: string;
  source?: string;
  target?: string;
  directed?: boolean;
}

export interface Checkpoint {
  description?: string;
  screenshot?: boolean;
  assert: Assertion[];
}

export interface PlanStep {
  tool: string;
  params: Record<string, unknown>;
  reasoning?: string;
  checkpoint?: Checkpoint;
}

export interface PlanBody {
  task: string;
  use_screenshot?: boolean;
  countdown?: number;
}

export interface PlanResult {
  reasoning: string;
  steps: PlanStep[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatPlanBody {
  messages: ChatMessage[];
  use_screenshot?: boolean;
  countdown?: number;
}

export interface AssertionResult {
  check: string | null;
  passed: boolean;
  detail: string;
  spec: Assertion;
}

// How a checkpoint was verified (Phase 3). The screenshot/critic/human verdict
// is authoritative; `passed` (SG assertions) is kept only as a secondary hint.
export interface CheckpointVerification {
  mode: 'manual' | 'ai';
  passed: boolean;
  reasoning?: string; // critic's explanation (ai mode)
}

export interface CheckpointResult {
  passed: boolean | null; // SG-assertion result — secondary hint, not the gate
  description: string;
  results?: AssertionResult[];
  screenshot?: string | null; // filename, served by GET /api/screenshot/{name}
  screenshot_error?: string;
  skipped?: boolean;
  reason?: string;
  verification?: CheckpointVerification; // set by the client once decided
}

export interface TraceEntry {
  step: number;
  tool: string;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  checkpoint?: CheckpointResult;
  flagged_wrong?: boolean;
}

export interface RepairBody {
  task: string;
  failed_steps: TraceEntry[];
  user_note?: string;
  use_screenshot?: boolean;
  countdown?: number;
}

export interface RunPlanBody {
  steps: PlanStep[];
  countdown?: number;
  stop_on_checkpoint_fail?: boolean;
  clear_canvas?: boolean;
}

export interface RunPlanResult {
  ok: boolean;
  checkpoints_ok: boolean;
  trace: TraceEntry[];
  scene_graph: SceneGraph;
}

// === Captured icons (left panel) ==========================================

export interface CapturedIcon {
  name: string; // dispatch key for place_shape's tool_name
  label: string; // humanized shape family
  category: string; // group header
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface UiGraphResult {
  domain: string;
  sidebar_shapes: string[];
  icons: CapturedIcon[];
}

// === Segmented, verification-gated run (Phase 3) ==========================

export interface RunPlanSegmentBody {
  steps: PlanStep[];
  start: number;
  countdown?: number;
  clear_canvas?: boolean;
}

export interface SegmentResult {
  trace: TraceEntry[];
  next_index: number;
  done: boolean;
  checkpoint_step: number | null; // 1-based step# that paused us, if any
  scene_graph: SceneGraph;
}

export interface CriticBody {
  screenshot: string;
  description: string;
}

export interface CriticResult {
  passed: boolean;
  reasoning: string;
}

// === Explore — sidebar detection + labeling ================================

export interface ExploreIcon {
  x: number;   // logical center-x
  y: number;   // logical center-y
  w: number;   // logical width
  h: number;   // logical height
  label?: string | null;
}

export interface DetectResult {
  screenshot: string;      // filename served via /api/screenshot/{name}
  logical_width: number;
  logical_height: number;
  screen_scale: number;
  icons: ExploreIcon[];
}

export interface LabelBody {
  icons: ExploreIcon[];
  indices?: number[] | null;   // null = label all
  domain?: string;             // interface to label for
  countdown?: number;
}

export interface LabelResult {
  icons: ExploreIcon[];
}

export interface SaveExploreBody {
  icons: ExploreIcon[];
  domain?: string;             // interface to write (defaults to active)
}

export interface SaveExploreResult {
  saved: number;
  path: string;
}

export interface DetectBody {
  countdown?: number;
}

// === Interface (domain) switching =========================================

export interface DomainsResult {
  active: string;
  available: string[];
}

export interface SetDomainBody {
  domain: string;
}

export interface SetDomainResult {
  active: string;
  available: string[];
  tool_count: number;
}
