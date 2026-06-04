// PlanPanel — Phase 2 + 3 orchestrator UI with a persistent planning chat.
//
//   • Chat: a long-lived thread with the planner. The first message drafts a
//     plan; every later message refines it ("make them bigger", "add a third").
//     The model re-emits the full plan each turn; its reasoning is the reply.
//   • Edit: the draft plan is editable by hand (tool, params, order, add/remove).
//   • Run: execute it (optionally clearing the draw.io canvas first), with a
//     checkpoint screenshot + pass/fail after each checkpointed step.
//   • Fix: flag wrong steps + a note → "Ask agent to fix" re-plans from the
//     current canvas. (The fix is also threaded back into the chat.)
//   • Save: persist the current plan as a reusable compound tool.

import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type {
  Assertion,
  ChatMessage,
  CheckpointResult,
  PlanStep,
  RunPlanResult,
  SceneGraph,
  ToolSummary,
  TraceEntry,
} from '../types';

interface Props {
  tools: ToolSummary[];
  onSceneGraphUpdated: () => void;
  onToolSaved: () => void;
}

function fmtAssertion(a: Assertion): string {
  const { check, ...rest } = a;
  const parts = Object.entries(rest)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return parts.length ? `${check} · ${parts.join(' ')}` : String(check);
}
function fmtParams(params: Record<string, unknown>): string {
  return Object.entries(params ?? {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ');
}
function paramInputValue(v: unknown): string {
  if (v === undefined || v === null) return '';
  return typeof v === 'string' ? v : JSON.stringify(v);
}
function parseParamInput(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}
// An assistant turn stores the plan JSON; show its reasoning in the bubble.
function assistantText(content: string): string {
  try {
    const o = JSON.parse(content);
    return o.reasoning || '(plan updated)';
  } catch {
    return content;
  }
}

export function PlanPanel({ tools, onSceneGraphUpdated, onToolSaved }: Props) {
  const [convo, setConvo] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [useScreenshot, setUseScreenshot] = useState(false);
  const [countdown, setCountdown] = useState(5);
  const [stopOnFail, setStopOnFail] = useState(false);

  const [sending, setSending] = useState(false);
  const [running, setRunning] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [steps, setSteps] = useState<PlanStep[]>([]);
  const [result, setResult] = useState<RunPlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const [flagged, setFlagged] = useState<Set<number>>(new Set());
  const [repairNote, setRepairNote] = useState('');
  const [clearPrompt, setClearPrompt] = useState<SceneGraph | null>(null);

  const [toolName, setToolName] = useState('');
  const [toolDesc, setToolDesc] = useState('');
  const [overwrite, setOverwrite] = useState(false);

  const threadRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [convo, sending]);

  const toolNames = tools.map((t) => t.name);
  const paramsOf = (name: string): string[] =>
    tools.find((t) => t.name === name)?.params ?? [];
  const busy = sending || running || repairing || saving;
  const originalTask =
    convo.find((m) => m.role === 'user')?.content ?? '';

  // ── Chat ────────────────────────────────────────────────────────
  async function sendChat() {
    const text = chatInput.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...convo, { role: 'user', content: text }];
    setConvo(next);
    setChatInput('');
    setSending(true);
    setError(null);
    setInfo(null);
    try {
      const p = await api.planChat({
        messages: next,
        use_screenshot: useScreenshot,
        countdown: useScreenshot ? countdown : 0,
      });
      setConvo([
        ...next,
        { role: 'assistant', content: JSON.stringify({ reasoning: p.reasoning, steps: p.steps }) },
      ]);
      setSteps(p.steps);
      setResult(null);
      setFlagged(new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  // ── Run (with clear-or-keep gate) ───────────────────────────────
  async function handleRunClick() {
    if (!steps.length) return;
    setError(null);
    try {
      const sg = await api.getSceneGraph();
      if ((sg.objects?.length ?? 0) > 0) {
        setClearPrompt(sg);
        return;
      }
    } catch {
      /* run anyway if we can't read it */
    }
    doRun(false);
  }
  async function doRun(clearFirst: boolean) {
    setClearPrompt(null);
    setRunning(true);
    setError(null);
    setInfo(null);
    setResult(null);
    setFlagged(new Set());
    try {
      const r = await api.runPlan({
        steps,
        countdown,
        stop_on_checkpoint_fail: stopOnFail,
        clear_canvas: clearFirst,
      });
      setResult(r);
      onSceneGraphUpdated();
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  // ── Repair ──────────────────────────────────────────────────────
  async function handleRepair() {
    if (!result) return;
    const failed: TraceEntry[] = result.trace
      .filter(
        (e) =>
          flagged.has(e.step) ||
          e.checkpoint?.passed === false ||
          (e.result as { status?: string }).status === 'error',
      )
      .map((e) => ({ ...e, flagged_wrong: flagged.has(e.step) }));
    setRepairing(true);
    setError(null);
    setInfo(null);
    try {
      const p = await api.repair({
        task: originalTask,
        failed_steps: failed,
        user_note: repairNote,
        use_screenshot: useScreenshot,
        countdown: useScreenshot ? countdown : 0,
      });
      // thread the fix back into the conversation for continuity
      setConvo([
        ...convo,
        { role: 'user', content: `[Fix] ${repairNote || 'fix the flagged steps'}` },
        { role: 'assistant', content: JSON.stringify({ reasoning: p.reasoning, steps: p.steps }) },
      ]);
      setSteps(p.steps);
      setResult(null);
      setFlagged(new Set());
      setRepairNote('');
      setInfo(`Loaded corrective plan (${p.steps.length} steps) — review and Run.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setRepairing(false);
    }
  }

  // ── Save as tool ────────────────────────────────────────────────
  async function handleSaveTool() {
    if (!toolName.trim() || !steps.length) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      await api.saveTool({
        name: toolName.trim(),
        description: toolDesc.trim(),
        params: [],
        needs_ui_graph: true,
        steps: steps.map((s) => ({ tool: s.tool, params: s.params })),
        overwrite,
      });
      setInfo(`Saved “${toolName.trim()}” to the catalog.`);
      onToolSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  // ── Step editing ────────────────────────────────────────────────
  function updateStep(idx: number, next: PlanStep) {
    setSteps((prev) => prev.map((s, i) => (i === idx ? next : s)));
  }
  function changeTool(idx: number, tool: string) {
    const keep = paramsOf(tool);
    const old = steps[idx].params ?? {};
    const params: Record<string, unknown> = {};
    for (const k of keep) if (k in old) params[k] = old[k];
    updateStep(idx, { ...steps[idx], tool, params });
  }
  function setParam(idx: number, key: string, raw: string) {
    updateStep(idx, {
      ...steps[idx],
      params: { ...steps[idx].params, [key]: parseParamInput(raw) },
    });
  }
  function removeStep(idx: number) {
    setSteps((prev) => prev.filter((_, i) => i !== idx));
  }
  function moveStep(idx: number, dir: -1 | 1) {
    setSteps((prev) => {
      const j = idx + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  }
  function dropCheckpoint(idx: number) {
    const { checkpoint: _d, ...rest } = steps[idx];
    void _d;
    updateStep(idx, rest as PlanStep);
  }
  function addStep() {
    setSteps((prev) => [...prev, { tool: toolNames[0] ?? 'place_shape', params: {} }]);
  }
  function toggleFlag(step: number) {
    setFlagged((prev) => {
      const next = new Set(prev);
      next.has(step) ? next.delete(step) : next.add(step);
      return next;
    });
  }

  return (
    <div className="panel plan">
      <header className="panel__header">
        <h2>
          Plan <span className="badge">ORCHESTRATOR</span>
        </h2>
        {convo.length > 0 && (
          <div className="panel__actions">
            <button
              className="link"
              disabled={busy}
              onClick={() => {
                setConvo([]);
                setSteps([]);
                setResult(null);
                setInfo(null);
                setError(null);
              }}
            >
              New chat
            </button>
          </div>
        )}
      </header>

      {/* ── Chat thread ────────────────────────────────────────── */}
      <div className="plan__chat" ref={threadRef}>
        {convo.length === 0 ? (
          <p className="plan__chat-empty">
            Describe a task to draft a plan — then keep chatting to refine it
            ("make the boxes bigger", "add a third node and connect it").
          </p>
        ) : (
          convo.map((m, i) => (
            <div key={i} className={`plan__msg plan__msg--${m.role}`}>
              <span className="plan__msg-role">
                {m.role === 'user' ? 'you' : 'planner'}
              </span>
              <div className="plan__msg-body">
                {m.role === 'assistant' ? assistantText(m.content) : m.content}
              </div>
            </div>
          ))
        )}
        {sending && <div className="plan__msg plan__msg--assistant plan__msg--typing">planning…</div>}
      </div>

      {/* ── Chat input (always present) ────────────────────────── */}
      <div className="plan__chat-input">
        <textarea
          rows={2}
          placeholder={
            convo.length
              ? 'Refine the plan… (Enter to send, Shift+Enter for newline)'
              : 'Describe the task… (Enter to send)'
          }
          value={chatInput}
          disabled={busy}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              sendChat();
            }
          }}
        />
        <div className="plan__chat-controls">
          <label className="plan__inline">
            <input
              type="checkbox"
              checked={useScreenshot}
              onChange={(e) => setUseScreenshot(e.target.checked)}
            />
            <span>Send screenshot</span>
          </label>
          <label className="plan__num">
            <span>Countdown</span>
            <input
              type="number"
              min={0}
              max={30}
              value={countdown}
              onChange={(e) => setCountdown(Number(e.target.value))}
            />
          </label>
          <button className="primary" onClick={sendChat} disabled={busy || !chatInput.trim()}>
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>

      {info && <div className="composer__msg composer__msg--info">{info}</div>}
      {error && <div className="composer__msg composer__msg--error">{error}</div>}

      {/* ── Editable plan ──────────────────────────────────────── */}
      {steps.length > 0 && (
        <>
          <h3 className="plan__section">
            Plan · {steps.length} step{steps.length === 1 ? '' : 's'}
            <span className="plan__hint"> · editable</span>
          </h3>
          <ol className="plan__steps">
            {steps.map((s, i) => (
              <li key={i} className="plan__step">
                <div className="plan__step-head">
                  <span className="plan__step-idx">{i + 1}</span>
                  <select
                    className="plan__tool-select"
                    value={s.tool}
                    disabled={busy}
                    onChange={(e) => changeTool(i, e.target.value)}
                  >
                    {!toolNames.includes(s.tool) && (
                      <option value={s.tool}>{s.tool} (unknown)</option>
                    )}
                    {toolNames.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                  <span className="plan__step-spacer" />
                  <button className="link plan__icon" title="Move up" disabled={busy || i === 0} onClick={() => moveStep(i, -1)}>↑</button>
                  <button className="link plan__icon" title="Move down" disabled={busy || i === steps.length - 1} onClick={() => moveStep(i, 1)}>↓</button>
                  <button className="link danger plan__icon" title="Remove step" disabled={busy} onClick={() => removeStep(i)}>✕</button>
                </div>
                {paramsOf(s.tool).length > 0 && (
                  <div className="plan__params-edit">
                    {paramsOf(s.tool).map((p) => (
                      <label key={p}>
                        <span>{p}</span>
                        <input
                          value={paramInputValue(s.params?.[p])}
                          disabled={busy}
                          placeholder="value"
                          onChange={(e) => setParam(i, p, e.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                )}
                {s.checkpoint && (
                  <div className="plan__ckpt-draft">
                    <span className="badge badge--ckpt">checkpoint</span>
                    {s.checkpoint.description && (
                      <span className="plan__ckpt-desc">{s.checkpoint.description}</span>
                    )}
                    <button className="link danger plan__ckpt-drop" disabled={busy} onClick={() => dropCheckpoint(i)}>
                      remove checkpoint
                    </button>
                    <div className="plan__asserts">
                      {s.checkpoint.assert.map((a, j) => (
                        <span key={j} className="chip chip--assert">{fmtAssertion(a)}</span>
                      ))}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ol>

          <div className="plan__run-actions">
            <button className="link" onClick={addStep} disabled={busy}>+ Add step</button>
            <label className="plan__inline">
              <input type="checkbox" checked={stopOnFail} onChange={(e) => setStopOnFail(e.target.checked)} />
              <span>Stop on checkpoint failure</span>
            </label>
            <button className="primary" onClick={handleRunClick} disabled={busy}>
              {running ? 'Running…' : `Run plan (${steps.length})`}
            </button>
          </div>

          {/* ── Save as tool ─────────────────────────────────── */}
          <details className="plan__save">
            <summary>Save this plan as a reusable tool</summary>
            <div className="plan__save-body">
              <label>
                <span>tool name</span>
                <input
                  value={toolName}
                  placeholder="e.g. server_client_star"
                  disabled={busy}
                  onChange={(e) => setToolName(e.target.value)}
                />
              </label>
              <label>
                <span>description</span>
                <input
                  value={toolDesc}
                  placeholder="what it builds"
                  disabled={busy}
                  onChange={(e) => setToolDesc(e.target.value)}
                />
              </label>
              <label className="plan__inline">
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                <span>overwrite if exists</span>
              </label>
              <button className="primary" onClick={handleSaveTool} disabled={busy || !toolName.trim()}>
                {saving ? 'Saving…' : 'Save tool'}
              </button>
            </div>
          </details>
        </>
      )}

      {/* ── Run results ────────────────────────────────────────── */}
      {result && (
        <div className="plan__result">
          <div className="plan__summary">
            <span className={`pill ${result.ok ? 'pill--ok' : 'pill--bad'}`}>
              {result.ok ? '✓ executed' : '✗ execution error'}
            </span>
            <span className={`pill ${result.checkpoints_ok ? 'pill--ok' : 'pill--bad'}`}>
              {result.checkpoints_ok ? '✓ checkpoints' : '✗ checkpoints'}
            </span>
            <SceneSummary sg={result.scene_graph} />
          </div>
          <ol className="plan__trace">
            {result.trace.map((e) => (
              <TraceRow key={e.step} entry={e} flagged={flagged.has(e.step)} onFlag={() => toggleFlag(e.step)} onShot={setLightbox} />
            ))}
          </ol>
          <div className="plan__repair">
            <h3 className="plan__section">Fix</h3>
            <p className="plan__repair-hint">
              Flag wrong steps above, then edit the plan by hand and re-run, or
              describe the problem and let the agent re-plan from the current
              canvas (the fix is added to the chat).
            </p>
            <textarea
              className="plan__task"
              rows={2}
              placeholder="What's wrong / how to fix? (optional)"
              value={repairNote}
              onChange={(e) => setRepairNote(e.target.value)}
              disabled={busy}
            />
            <div className="plan__repair-actions">
              <span className="plan__repair-count">
                {flagged.size} flagged
                {!result.checkpoints_ok ? ' · checkpoint failures included' : ''}
              </span>
              <button className="primary" onClick={handleRepair} disabled={busy}>
                {repairing ? 'Asking agent…' : 'Ask agent to fix'}
              </button>
            </div>
          </div>
        </div>
      )}

      {clearPrompt && (
        <div className="plan__modal-overlay" onClick={() => setClearPrompt(null)}>
          <div className="plan__modal" onClick={(e) => e.stopPropagation()}>
            <h3>Existing scene graph</h3>
            <p>
              The scene graph already has{' '}
              <strong>{clearPrompt.objects.length} object(s)</strong> and{' '}
              <strong>{clearPrompt.edges.length} edge(s)</strong>.{' '}
              <em>Clear &amp; run</em> wipes the draw.io canvas (select-all +
              delete) and the scene graph first; <em>Keep &amp; run</em> appends.
            </p>
            <div className="plan__modal-actions">
              <button onClick={() => setClearPrompt(null)}>Cancel</button>
              <button onClick={() => doRun(false)}>Keep &amp; run</button>
              <button className="primary" onClick={() => doRun(true)}>Clear &amp; run</button>
            </div>
          </div>
        </div>
      )}

      {lightbox && (
        <div className="plan__lightbox" onClick={() => setLightbox(null)}>
          <img src={api.screenshotUrl(lightbox)} alt="checkpoint screenshot" />
        </div>
      )}
    </div>
  );
}

function SceneSummary({ sg }: { sg: SceneGraph }) {
  const labels = sg.objects.map((o) => o.label || o.id).join(', ');
  return (
    <span className="plan__scene-summary" title={labels}>
      scene: {sg.objects.length} obj · {sg.edges.length} edge
      {sg.metadata?.last_op ? ` · last ${sg.metadata.last_op}` : ''}
    </span>
  );
}

function TraceRow({
  entry,
  flagged,
  onFlag,
  onShot,
}: {
  entry: TraceEntry;
  flagged: boolean;
  onFlag: () => void;
  onShot: (name: string) => void;
}) {
  const status = String((entry.result as { status?: string }).status ?? '?');
  const err = (entry.result as { error?: string }).error;
  const cp = entry.checkpoint;
  return (
    <li className={`plan__trace-row${flagged ? ' is-flagged' : ''}`}>
      <div className="plan__step-head">
        <span className="plan__step-idx">{entry.step}</span>
        <code className="plan__step-tool">{entry.tool}</code>
        <span className="plan__step-params">{fmtParams(entry.params)}</span>
        <span className={`tag tag--${status}`}>{status}</span>
        <button className={`link plan__flag${flagged ? ' is-on' : ''}`} title="Mark this step wrong" onClick={onFlag}>
          {flagged ? '⚑ flagged' : '⚐ mark wrong'}
        </button>
      </div>
      {err && <div className="plan__step-err">{err}</div>}
      {cp && <CheckpointCard cp={cp} onShot={onShot} />}
    </li>
  );
}

function CheckpointCard({ cp, onShot }: { cp: CheckpointResult; onShot: (name: string) => void }) {
  if (cp.skipped) {
    return <div className="plan__ckpt plan__ckpt--skip">checkpoint skipped ({cp.reason})</div>;
  }
  const cls = cp.passed ? 'plan__ckpt--ok' : 'plan__ckpt--bad';
  return (
    <div className={`plan__ckpt ${cls}`}>
      <div className="plan__ckpt-head">
        <span className="plan__ckpt-mark">{cp.passed ? '✓' : '✗'}</span>
        <strong>Checkpoint</strong>
        {cp.description && <span className="plan__ckpt-desc">{cp.description}</span>}
      </div>
      <ul className="plan__asserts-results">
        {(cp.results ?? []).map((r, i) => (
          <li key={i} className={r.passed ? 'is-ok' : 'is-bad'}>
            <span>{r.passed ? '✓' : '✗'}</span> {r.detail}
          </li>
        ))}
      </ul>
      {cp.screenshot && (
        <button className="plan__shot" onClick={() => onShot(cp.screenshot as string)} title="Click to enlarge">
          <img src={api.screenshotUrl(cp.screenshot)} alt="checkpoint" />
        </button>
      )}
      {cp.screenshot_error && (
        <div className="plan__shot-err">screenshot failed: {cp.screenshot_error}</div>
      )}
    </div>
  );
}
