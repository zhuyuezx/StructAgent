// PlanPanel — Phase 2 + 3 orchestrator UI with a persistent planning chat.
//
//   • Chat: a long-lived thread with the planner. The first message drafts a
//     plan; every later message refines it ("make them bigger", "add a third").
//     The model re-emits the full plan each turn; its reasoning is the reply.
//   • Edit: the draft plan is editable by hand (tool, params, order, add/remove).
//   • Run: execute it one SEGMENT at a time. The run pauses at every checkpoint,
//     captures a screenshot, and waits for verification before continuing —
//     either the user eyeballs the screenshot (manual, default) or, when "Let
//     AI verify" is on, a vision critic judges it. Only a PASS resumes the plan.
//     (Scene-graph assertions are shown as secondary hints, never the gate —
//     the graph goes stale the moment the live UI drifts from it.)
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
  SceneGraph,
  ToolSummary,
  TraceEntry,
} from '../types';

interface Props {
  tools: ToolSummary[];
  onSceneGraphUpdated: () => void;
  onToolSaved: () => void;
}

// A checkpoint reached during a run, awaiting a pass/fail decision before the
// plan may continue.
interface Pending {
  step: number; // 1-based step# that paused us
  description: string;
  screenshot: string | null;
  nextIndex: number; // resume from here on PASS
  done: boolean; // this was the last step in the plan
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
function assistantRaw(content: string): string | null {
  try {
    const o = JSON.parse(content);
    return typeof o.raw_response === 'string' && o.raw_response.trim()
      ? o.raw_response
      : null;
  } catch {
    return null;
  }
}

export function PlanPanel({ tools, onSceneGraphUpdated, onToolSaved }: Props) {
  const [convo, setConvo] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [useScreenshot, setUseScreenshot] = useState(false);
  const [countdown, setCountdown] = useState(5);
  const [aiVerify, setAiVerify] = useState(false);

  const [sending, setSending] = useState(false);
  const [running, setRunning] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [steps, setSteps] = useState<PlanStep[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);

  // ── Run state (segmented, verification-gated) ───────────────────
  const [runTrace, setRunTrace] = useState<TraceEntry[]>([]);
  const [runScene, setRunScene] = useState<SceneGraph | null>(null);
  const [runActive, setRunActive] = useState(false); // a run is in progress/paused
  const [runFinished, setRunFinished] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);

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
  const busy = sending || running || verifying || repairing || saving;
  // Editing the plan / starting a new run is locked while one is mid-flight
  // (running, paused at a checkpoint, or the critic is judging) — index changes
  // would desync the resume cursor.
  const editLocked = busy || runActive;
  const originalTask =
    convo.find((m) => m.role === 'user')?.content ?? '';

  // Derived run outcome (from the accumulated trace).
  const execOk =
    runTrace.length > 0 &&
    runTrace.every(
      (e) => (e.result as { status?: string }).status === 'ok',
    );
  const checkpointsOk = runTrace.every(
    (e) => e.checkpoint?.verification?.passed !== false,
  );

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
        { role: 'assistant', content: JSON.stringify({ reasoning: p.reasoning, steps: p.steps, raw_response: p.raw_response }) },
      ]);
      setSteps(p.steps);
      resetRunState();
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  // ── Run (segmented, verification-gated) ─────────────────────────
  function resetRunState() {
    setRunTrace([]);
    setRunScene(null);
    setRunActive(false);
    setRunFinished(false);
    setPending(null);
    setFlagged(new Set());
    setInfo(null);
    setError(null);
  }

  async function handleRunClick() {
    if (!steps.length || editLocked) return;
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
    startRun(false);
  }

  async function startRun(clearFirst: boolean) {
    setClearPrompt(null);
    resetRunState();
    setRunActive(true);
    await runSegmentFrom(0, clearFirst, true);
  }

  function finishRun() {
    setRunActive(false);
    setRunFinished(true);
    setPending(null);
  }

  // Run steps[start..next checkpoint] then pause for verification (or finish).
  async function runSegmentFrom(
    start: number,
    clearFirst: boolean,
    isFirst: boolean,
  ) {
    setRunning(true);
    setError(null);
    try {
      const seg = await api.runPlanSegment({
        steps,
        start,
        clear_canvas: isFirst && clearFirst,
        // First segment always counts down (time to focus draw.io). Later
        // segments need it only in manual mode — the user just clicked in the
        // browser and must refocus draw.io; in AI mode focus never left.
        countdown: isFirst ? countdown : aiVerify ? 0 : countdown,
      });
      setRunTrace((prev) => [...prev, ...seg.trace]);
      setRunScene(seg.scene_graph);
      onSceneGraphUpdated();

      // A dispatch error inside the segment stops the whole run.
      const errored = seg.trace.some(
        (e) => (e.result as { status?: string }).status === 'error',
      );
      if (errored) {
        setError('A step failed — run stopped. Flag/fix below.');
        finishRun();
        return;
      }

      if (seg.checkpoint_step != null) {
        const cp = seg.trace.find(
          (e) => e.step === seg.checkpoint_step,
        )?.checkpoint;
        const p: Pending = {
          step: seg.checkpoint_step,
          description: cp?.description ?? '',
          screenshot: cp?.screenshot ?? null,
          nextIndex: seg.next_index,
          done: seg.done,
        };
        setPending(p);
        // AI mode auto-verifies (needs a screenshot); otherwise wait for the
        // user's manual verdict.
        if (aiVerify && p.screenshot) {
          await runCritic(p);
        }
      } else if (seg.done) {
        finishRun();
      } else {
        // No checkpoint but not done — shouldn't happen; continue defensively.
        await runSegmentFrom(seg.next_index, false, false);
      }
    } catch (e) {
      setError(String(e));
      finishRun();
    } finally {
      setRunning(false);
    }
  }

  function recordVerdict(
    step: number,
    mode: 'manual' | 'ai',
    passed: boolean,
    reasoning?: string,
  ) {
    setRunTrace((prev) =>
      prev.map((e) =>
        e.step === step && e.checkpoint
          ? {
              ...e,
              checkpoint: {
                ...e.checkpoint,
                verification: { mode, passed, reasoning },
              },
            }
          : e,
      ),
    );
  }

  async function runCritic(p: Pending) {
    if (!p.screenshot) return;
    setVerifying(true);
    try {
      const v = await api.critic({
        screenshot: p.screenshot,
        description: p.description,
      });
      recordVerdict(p.step, 'ai', v.passed, v.reasoning);
      if (v.passed) {
        await continueAfter(p);
      } else {
        setInfo(
          `AI critic rejected checkpoint ${p.step}: ${v.reasoning || '(no reason given)'}`,
        );
        finishRun();
      }
    } catch (e) {
      // Critic unavailable → fall back to a manual decision (leave pending).
      setError(`Critic failed: ${String(e)} — verify this checkpoint manually.`);
    } finally {
      setVerifying(false);
    }
  }

  async function continueAfter(p: Pending) {
    setPending(null);
    if (p.done) finishRun();
    else await runSegmentFrom(p.nextIndex, false, false);
  }

  function approveCheckpoint() {
    if (!pending) return;
    recordVerdict(pending.step, 'manual', true);
    void continueAfter(pending);
  }

  function rejectCheckpoint() {
    if (!pending) return;
    recordVerdict(pending.step, 'manual', false);
    finishRun();
  }

  // ── Repair ──────────────────────────────────────────────────────
  async function handleRepair() {
    if (!runTrace.length) return;
    const failed: TraceEntry[] = runTrace
      .filter(
        (e) =>
          flagged.has(e.step) ||
          e.checkpoint?.verification?.passed === false ||
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
        { role: 'assistant', content: JSON.stringify({ reasoning: p.reasoning, steps: p.steps, raw_response: p.raw_response }) },
      ]);
      setSteps(p.steps);
      resetRunState();
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
                resetRunState();
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
                {m.role === 'assistant' && assistantRaw(m.content) && (
                  <details className="plan__raw">
                    <summary>Raw model response</summary>
                    <pre>{assistantRaw(m.content)}</pre>
                  </details>
                )}
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
                    disabled={editLocked}
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
                  <button className="link plan__icon" title="Move up" disabled={editLocked || i === 0} onClick={() => moveStep(i, -1)}>↑</button>
                  <button className="link plan__icon" title="Move down" disabled={editLocked || i === steps.length - 1} onClick={() => moveStep(i, 1)}>↓</button>
                  <button className="link danger plan__icon" title="Remove step" disabled={editLocked} onClick={() => removeStep(i)}>✕</button>
                </div>
                {paramsOf(s.tool).length > 0 && (
                  <div className="plan__params-edit">
                    {paramsOf(s.tool).map((p) => (
                      <label key={p}>
                        <span>{p}</span>
                        <input
                          value={paramInputValue(s.params?.[p])}
                          disabled={editLocked}
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
                    <button className="link danger plan__ckpt-drop" disabled={editLocked} onClick={() => dropCheckpoint(i)}>
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
            <button className="link" onClick={addStep} disabled={editLocked}>+ Add step</button>
            <label
              className="plan__inline"
              title="When on, a vision critic judges each checkpoint screenshot. When off, you approve each checkpoint by hand."
            >
              <input
                type="checkbox"
                checked={aiVerify}
                disabled={editLocked}
                onChange={(e) => setAiVerify(e.target.checked)}
              />
              <span>Let AI verify checkpoints</span>
            </label>
            <button className="primary" onClick={handleRunClick} disabled={editLocked}>
              {running ? 'Running…' : runActive ? 'Run in progress…' : `Run plan (${steps.length})`}
            </button>
          </div>
          <p className="plan__run-hint">
            The run pauses at every checkpoint to capture a screenshot and{' '}
            {aiVerify
              ? 'let the AI critic verify it'
              : 'wait for you to verify it'}
            . Only a PASS continues the plan.
          </p>

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

      {/* ── Run trace (live) + verification + summary ──────────── */}
      {(runActive || runFinished) && runTrace.length > 0 && (
        <div className="plan__result">
          {runFinished && (
            <div className="plan__summary">
              <span className={`pill ${execOk ? 'pill--ok' : 'pill--bad'}`}>
                {execOk ? '✓ executed' : '✗ execution error'}
              </span>
              <span className={`pill ${checkpointsOk ? 'pill--ok' : 'pill--bad'}`}>
                {checkpointsOk ? '✓ checkpoints verified' : '✗ checkpoint rejected'}
              </span>
              {runScene && <SceneSummary sg={runScene} />}
            </div>
          )}

          <ol className="plan__trace">
            {runTrace.map((e) => (
              <TraceRow
                key={e.step}
                entry={e}
                flagged={flagged.has(e.step)}
                onFlag={() => toggleFlag(e.step)}
                onShot={setLightbox}
              />
            ))}
          </ol>

          {/* Verification gate — shown while paused at a checkpoint. */}
          {pending && (
            <VerificationPrompt
              pending={pending}
              aiVerify={aiVerify}
              verifying={verifying}
              onShot={setLightbox}
              onApprove={approveCheckpoint}
              onReject={rejectCheckpoint}
            />
          )}

          {running && !pending && (
            <div className="plan__running-banner">running steps…</div>
          )}

          {/* Repair — available once the run has finished. */}
          {runFinished && (
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
                  {!checkpointsOk ? ' · rejected checkpoints included' : ''}
                </span>
                <button className="primary" onClick={handleRepair} disabled={busy}>
                  {repairing ? 'Asking agent…' : 'Ask agent to fix'}
                </button>
              </div>
            </div>
          )}
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
              <button onClick={() => startRun(false)}>Keep &amp; run</button>
              <button className="primary" onClick={() => startRun(true)}>Clear &amp; run</button>
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
  // The verification verdict (human/AI from the screenshot) is authoritative.
  const v = cp.verification;
  const cls = !v
    ? 'plan__ckpt--pending'
    : v.passed
      ? 'plan__ckpt--ok'
      : 'plan__ckpt--bad';
  const mark = !v ? '…' : v.passed ? '✓' : '✗';
  const verdict = !v
    ? 'awaiting verification'
    : `${v.passed ? 'verified' : 'rejected'} · ${v.mode === 'ai' ? 'AI critic' : 'manual'}`;
  return (
    <div className={`plan__ckpt ${cls}`}>
      <div className="plan__ckpt-head">
        <span className="plan__ckpt-mark">{mark}</span>
        <strong>Checkpoint</strong>
        <span className="plan__ckpt-verdict">{verdict}</span>
        {cp.description && <span className="plan__ckpt-desc">{cp.description}</span>}
      </div>
      {v?.reasoning && <div className="plan__ckpt-reason">“{v.reasoning}”</div>}
      {cp.screenshot && (
        <button className="plan__shot" onClick={() => onShot(cp.screenshot as string)} title="Click to enlarge">
          <img src={api.screenshotUrl(cp.screenshot)} alt="checkpoint" />
        </button>
      )}
      {cp.screenshot_error && (
        <div className="plan__shot-err">screenshot failed: {cp.screenshot_error}</div>
      )}
      {/* Scene-graph assertions — secondary hint only, not the gate. */}
      {(cp.results?.length ?? 0) > 0 && (
        <details className="plan__ckpt-hints">
          <summary>structural hints (scene graph · may be stale)</summary>
          <ul className="plan__asserts-results">
            {(cp.results ?? []).map((r, i) => (
              <li key={i} className={r.passed ? 'is-ok' : 'is-bad'}>
                <span>{r.passed ? '✓' : '✗'}</span> {r.detail}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function VerificationPrompt({
  pending,
  aiVerify,
  verifying,
  onShot,
  onApprove,
  onReject,
}: {
  pending: Pending;
  aiVerify: boolean;
  verifying: boolean;
  onShot: (name: string) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const aiAuto = aiVerify && !!pending.screenshot;
  return (
    <div className="plan__verify">
      <div className="plan__verify-head">
        <span className="badge badge--ckpt">checkpoint {pending.step}</span>
        <strong>Verify before continuing</strong>
      </div>
      {pending.description && (
        <p className="plan__verify-desc">Expected: {pending.description}</p>
      )}
      {pending.screenshot ? (
        <button
          className="plan__shot plan__shot--lg"
          onClick={() => onShot(pending.screenshot as string)}
          title="Click to enlarge"
        >
          <img src={api.screenshotUrl(pending.screenshot)} alt="checkpoint screenshot" />
        </button>
      ) : (
        <p className="plan__verify-noshot">
          No screenshot was captured — verify on the draw.io canvas directly.
        </p>
      )}
      {aiAuto ? (
        <div className="plan__verify-ai">
          {verifying ? 'AI critic is verifying…' : 'AI critic is deciding…'}
        </div>
      ) : (
        <div className="plan__verify-actions">
          {aiVerify && !pending.screenshot && (
            <span className="plan__verify-fallback">
              AI verify needs a screenshot — decide manually:
            </span>
          )}
          <button className="primary" onClick={onApprove}>
            ✓ Looks right — continue
          </button>
          <button className="danger" onClick={onReject}>
            ✗ Wrong — stop
          </button>
        </div>
      )}
    </div>
  );
}
