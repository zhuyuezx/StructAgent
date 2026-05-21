# StructAgent Studio — Visual Orchestrator for Closed-UI Automation

## TL;DR

A ComfyUI-style node-based editor on top of the existing tool tree, where:

- Tools (L0–L2+) appear as nodes with typed input/output ports.
- The user composes, edits, and saves workflows as **graphs**, not flat traces.
- The LLM's job narrows to **translating a text prompt into a draft graph** (planner), not driving execution turn-by-turn.
- The framework **executes the graph deterministically**, firing **checkpoints** between nodes that verify the live scene graph against the planned one.
- When a checkpoint fails, the LLM proposes a **repair** (insert/replace/delete nodes); the user can also intervene manually in the same canvas.

Humans and the LLM become co-authors of the same artifact, with the framework refereeing.

## Why this is the right next step

Today the executor is the bottleneck: every step is an LLM turn, and on failure the only recourse is to write a more prescriptive prompt. `save_trace_as_tool` is a partial fix — it caches successful explorations — but the unit it saves is a flat sequence, which is hard for users to inspect, edit, or reuse.

The Studio reframes the loop:

| Current | Studio |
|---|---|
| LLM picks one tool per turn | LLM emits a draft graph once |
| Execution = N inference calls | Execution = 0 inference calls (until a checkpoint fails) |
| Save artifact = opaque JSON sequence | Save artifact = inspectable, editable typed graph |
| Failure recovery = re-prompt with stricter rules | Failure recovery = LLM patches the graph, or user does |
| Human in the loop = read logs, retry | Human in the loop = first-class graph editor |

Key architectural insight: the **scene graph already gives you a deterministic ground truth** for what the canvas should look like at each step. Checkpoints are cheap *because* of that — you don't need the LLM to validate, you compare graph deltas.

## System architecture

Three actors, one shared artifact.

```
   ┌───────────┐      ┌──────────────┐      ┌───────────────┐
   │   User    │      │   Planner    │      │   Executor    │
   │ (browser) │      │   (LLM)      │      │  (framework)  │
   └─────┬─────┘      └──────┬───────┘      └───────┬───────┘
         │                   │                      │
         │  text prompt      │                      │
         │──────────────────►│                      │
         │                   │   draft graph        │
         │                   │─────────────────────►│
         │                   │                      │
         │  edits / overrides│                      │   dispatch tools
         │──────────────────►│◄─── checkpoint fail──┤   + scene_graph
         │                   │   repair proposal    │
         │                   │─────────────────────►│
         └──────────────────────────────────────────┘
                          shared:
                ┌────────────────────────────┐
                │   Orchestrator Graph (OG)  │
                │  nodes = tools             │
                │  edges = typed dataflow    │
                │  checkpoints = expected SG │
                └────────────────────────────┘
```

## The Orchestrator Graph

A typed dataflow graph stored as JSON.

**Node** = one tool invocation
- Tool name (any registered L0/L1/L2+)
- Param bindings — literal values or `$ref` to upstream node outputs
- Optional pre/post checkpoint

**Port** = typed input or output
- Types: `string`, `position`, `direction`, `scene_object`, `scene_edge`, `tool_name`
- Outputs come from each tool's declared `outputs:` field (see the typed-tool work in [save_tool.py](core/tools/save_tool.py))

**Edge** = wires an upstream output port → downstream input port
- Type-checked at composition time
- Rendered as a visible wire in the UI

**Checkpoint** = a structural assertion about `scene_graph` after a node runs
- e.g. `objects_count == 2`, `obj.label == "Source"`, `edges_count >= 1`
- Generated automatically by the planner from the textual intent
- User-editable: tighten, relax, or remove

## Execution model

1. Load OG → topological sort → walk nodes.
2. For each node:
   - Resolve params (literals + `$ref` from prior outputs).
   - Dispatch the underlying tool via the existing `dispatch()` path.
   - Capture outputs into the node's output ports.
   - If a post-checkpoint is attached, evaluate it against `scene_graph`.
3. On checkpoint failure:
   - Pause execution.
   - Capture screenshot + current `scene_graph` + the failed checkpoint + a window of the OG around the failure.
   - Hand to the Planner for a **repair proposal** (a set of graph edits).
   - Show the proposal as a diff in the UI; user can accept, reject, or hand-edit.
   - Resume from the failed node.

Checkpoints are the only place screenshots are taken during execution — everything else is symbolic. This makes the system fast (no per-step VLM) and auditable (every screenshot is tied to a failed assertion).

## LLM's narrowed role

The Planner is invoked in three places, not on every step:

1. **Prompt → draft graph.** Input: text, current `scene_graph`, tool catalog (with types). Output: an OG with checkpoints.
2. **Checkpoint failure → repair.** Input: failed checkpoint, screenshot, `scene_graph` delta, surrounding graph. Output: a diff of graph edits.
3. **Generalization (offline).** When two saved graphs differ only in literals, propose a unified parameterized graph.

This is a much smaller LLM footprint than today's per-turn executor. It shifts the LLM toward what it's best at (planning and patching structured artifacts) and away from what it's worst at (running long sequential procedures without drift).

## User's role

First-class, not an escape hatch.

- Browse the catalog (tool tree, by level).
- Compose new tools by dragging nodes and wiring ports.
- Inspect any saved graph; see the trace, the checkpoints, and where it has been used.
- Pause execution at any checkpoint; modify the graph in place; resume.
- Save the running graph as a new compound tool (one-click `save_trace_as_tool`).
- Branch a graph into variants (e.g., one for 3 nodes, one for 5).

## Why this beats Claude Code / Computer Use / ComfyUI

| | Computer Use | Claude Code | ComfyUI | StructAgent Studio |
|---|---|---|---|---|
| Per-step LLM cost | linear | linear | n/a | one plan + checkpoints only |
| Reusable artifact | none | flat code/skills | graph | typed graph |
| User can edit artifacts | n/a | as code | visual | visual + code |
| Failure recovery | re-prompt | re-prompt | none | structural diff against scene_graph |
| Long-horizon stability | drifts | drifts on GUI | n/a | bounded by checkpoint count |
| Targets external stateful UIs | yes (brittle) | no | no | yes (verified) |
| Human-AI collaboration grain | message | message | none | node/edge edits in the same canvas |

The one-line pitch: *ComfyUI was for stateless pipelines. Studio is for stateful external interfaces — closed UIs, legacy software, design tools — where the framework owns the verification step that ComfyUI didn't need.*

## What needs to be built

### Phase 0 — prerequisites (partially in motion)
- Typed inputs/outputs on tools (evolution of [save_tool.py](core/tools/save_tool.py)).
- Auto-parameterize varying literals across traces.

### Phase 1 — graph data model + headless execution
- `state/graphs/*.json` schema (nodes, edges, ports, checkpoints).
- A `run_graph(graph, ui_graph)` driver alongside the existing `dispatch()`.
- Checkpoint DSL: a small predicate language over `scene_graph`.
- Planner adapter: existing executor reframed to emit a full graph from a prompt, instead of one tool per turn.

### Phase 2 — repair loop
- Failure handler that bundles `{failed_checkpoint, screenshot, sg, surrounding_graph}`.
- Planner mode that returns a `GraphPatch` (insert / delete / replace nodes, retie edges).
- Patch-applier + replay-from-failed-node.

### Phase 3 — frontend
- React/Svelte web app, talks to a thin FastAPI wrapping `core/tools` + `run_graph`.
- Node-based canvas (use `react-flow` or `litegraph.js`).
- Tool catalog sidebar (renders the existing tool tree).
- Execution overlay: live highlight of the running node, checkpoint pass/fail badges, diff view for repair proposals.
- Save / load / fork graphs against `state/graphs/`.

### Phase 4 — generalization
- Cross-domain demo (iMovie or Keynote) proving the orchestrator is not draw.io-specific.
- "Refactor this graph": LLM mode that proposes extracting a subgraph into a new reusable tool.

## Open questions

- **Checkpoint expressiveness.** A predicate DSL over `scene_graph` is enough for diagrams; for timelines (iMovie) the schema differs and checkpoints become domain-aware. Likely one base checkpoint type plus domain extensions.
- **Granularity of LLM repair.** Should repair edit the surrounding graph, or only insert correction nodes before the failed one? Local repair is safer; global repair is more powerful.
- **User-LLM conflict resolution.** If the user edits a node while the LLM proposes a repair, whose version wins? Likely: user edits always win, LLM proposes against the current user-edited state.
- **Recording vs authoring.** Does running an existing graph also count as authoring (i.e., a successful run becomes a new saved variant)? Probably yes, with explicit user opt-in.

---

This shifts the project's center of gravity. The framework is no longer *"an LLM driving a closed UI"* — it becomes *"a visual orchestrator for closed UIs, where the LLM is one of several planners and the human is a first-class graph editor."* Same backend (tool tree, scene graph, save_tool); much bigger surface and a much clearer differentiation from Claude Code, Computer Use, and ComfyUI.
