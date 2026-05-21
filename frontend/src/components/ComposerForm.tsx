// ComposerForm — form-based compound tool builder.
//
// Authoring a new L2+ tool:
//   1. Set top-level metadata (name, description, $-params, needs_ui_graph).
//   2. Add steps: pick a tool from the catalog, fill its params (literal or
//      "$param" reference to a top-level param).
//   3. Reorder / delete steps.
//   4. "Test draft" runs the current step list without saving.
//   5. "Save" persists the compound via POST /api/tools.

import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { RunResult, StepDef, ToolDetail, ToolSummary } from '../types';

interface Props {
  tools: ToolSummary[];
  prefill: ToolDetail | null;
  onSaved: () => void;
}

interface DraftStep {
  tool: string;
  params: Record<string, string>; // values kept as strings, parsed on submit
}

const EMPTY_DRAFT = (): DraftStep => ({ tool: '', params: {} });

function parseValue(raw: string): unknown {
  // Treat values beginning with $ as parameter references (kept as string).
  // Otherwise try to parse as JSON (numbers, booleans, arrays); fall back
  // to the raw string. This matches the existing JSON tool format.
  if (raw.startsWith('$')) return raw;
  if (raw === '') return '';
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function ComposerForm({ tools, prefill, onSaved }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [paramsText, setParamsText] = useState(''); // comma-separated $-params
  const [needsUiGraph, setNeedsUiGraph] = useState(true);
  const [overwrite, setOverwrite] = useState(false);
  const [steps, setSteps] = useState<DraftStep[]>([EMPTY_DRAFT()]);
  const [countdown, setCountdown] = useState(5);

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    kind: 'info' | 'error' | 'success';
    text: string;
  } | null>(null);
  const [lastResult, setLastResult] = useState<RunResult | null>(null);

  // Pre-fill from another tool ("Edit in composer" button on ToolDetail).
  useEffect(() => {
    if (!prefill) return;
    setName(prefill.name + '_copy');
    setDescription(prefill.description ?? '');
    setParamsText(prefill.params.join(', '));
    setNeedsUiGraph(prefill.needs_ui_graph);
    setOverwrite(false);
    setSteps(
      (prefill.steps ?? []).map((s) => ({
        tool: s.tool,
        params: Object.fromEntries(
          Object.entries(s.params).map(([k, v]) => [
            k,
            typeof v === 'string' ? v : JSON.stringify(v),
          ]),
        ),
      })),
    );
    setMessage({
      kind: 'info',
      text: `Loaded from "${prefill.name}". Rename before saving (or check overwrite).`,
    });
  }, [prefill]);

  const toolsByName = useMemo(
    () => new Map(tools.map((t) => [t.name, t])),
    [tools],
  );

  function updateStep(i: number, fn: (s: DraftStep) => DraftStep) {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? fn(s) : s)));
  }
  function removeStep(i: number) {
    setSteps((prev) => prev.filter((_, idx) => idx !== i));
  }
  function moveStep(i: number, delta: number) {
    setSteps((prev) => {
      const next = [...prev];
      const target = i + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[i], next[target]] = [next[target], next[i]];
      return next;
    });
  }
  function addStep() {
    setSteps((prev) => [...prev, EMPTY_DRAFT()]);
  }

  function buildStepDefs(): StepDef[] {
    return steps
      .filter((s) => s.tool)
      .map((s) => {
        const toolMeta = toolsByName.get(s.tool);
        const expected = toolMeta?.params ?? [];
        // Strip params not declared by the tool, parse the rest.
        const params: Record<string, unknown> = {};
        for (const key of expected) {
          if (s.params[key] !== undefined && s.params[key] !== '') {
            params[key] = parseValue(s.params[key]);
          }
        }
        return { tool: s.tool, params };
      });
  }

  function buildTopLevelParams(): string[] {
    return paramsText
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);
  }

  async function handleSave() {
    if (!name.trim()) {
      setMessage({ kind: 'error', text: 'Name is required.' });
      return;
    }
    const stepDefs = buildStepDefs();
    if (stepDefs.length === 0) {
      setMessage({ kind: 'error', text: 'Need at least one step.' });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api.saveTool({
        name: name.trim(),
        description: description.trim(),
        params: buildTopLevelParams(),
        needs_ui_graph: needsUiGraph,
        steps: stepDefs,
        overwrite,
      });
      setMessage({ kind: 'success', text: `Saved "${name}".` });
      onSaved();
    } catch (e) {
      setMessage({ kind: 'error', text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function handleTestRun() {
    const stepDefs = buildStepDefs();
    if (stepDefs.length === 0) {
      setMessage({ kind: 'error', text: 'Need at least one step to test.' });
      return;
    }
    // Resolve top-level params from current values typed under "Top-level params".
    // For testing we treat $foo references as literals if undefined.
    const topParams: Record<string, unknown> = {};
    setBusy(true);
    setMessage({
      kind: 'info',
      text: `Running draft (${countdown}s countdown — switch to draw.io)…`,
    });
    setLastResult(null);
    try {
      const res = await api.runSteps({
        steps: stepDefs,
        params: topParams,
        countdown,
      });
      setLastResult(res);
      setMessage({
        kind: res.status === 'ok' ? 'success' : 'error',
        text: `Draft finished: ${res.status}`,
      });
    } catch (e) {
      setMessage({ kind: 'error', text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel composer">
      <header className="panel__header">
        <h2>Compose new tool</h2>
      </header>

      <fieldset disabled={busy}>
        <div className="composer__meta">
          <label>
            <span>Name</span>
            <input
              value={name}
              placeholder="my_compound_tool"
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            <span>Top-level params (comma-sep)</span>
            <input
              value={paramsText}
              placeholder="e.g. shape, label"
              onChange={(e) => setParamsText(e.target.value)}
            />
          </label>
          <label className="composer__full">
            <span>Description</span>
            <input
              value={description}
              placeholder="What does this tool do?"
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label className="composer__inline">
            <input
              type="checkbox"
              checked={needsUiGraph}
              onChange={(e) => setNeedsUiGraph(e.target.checked)}
            />
            <span>needs_ui_graph</span>
          </label>
          <label className="composer__inline">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
            />
            <span>overwrite if exists</span>
          </label>
        </div>

        <h3>Steps</h3>
        <ol className="composer__steps">
          {steps.map((step, i) => {
            const toolMeta = toolsByName.get(step.tool);
            return (
              <li key={i} className="composer__step">
                <div className="composer__step-header">
                  <span className="composer__step-idx">{i + 1}.</span>
                  <select
                    value={step.tool}
                    onChange={(e) =>
                      updateStep(i, () => ({ tool: e.target.value, params: {} }))
                    }
                  >
                    <option value="">— pick a tool —</option>
                    {tools.map((t) => (
                      <option key={t.name} value={t.name}>
                        L{t.level} · {t.name}
                      </option>
                    ))}
                  </select>
                  <span className="composer__step-spacer" />
                  <button
                    className="link"
                    onClick={() => moveStep(i, -1)}
                    disabled={i === 0}
                    title="Move up"
                  >
                    ↑
                  </button>
                  <button
                    className="link"
                    onClick={() => moveStep(i, +1)}
                    disabled={i === steps.length - 1}
                    title="Move down"
                  >
                    ↓
                  </button>
                  <button
                    className="link danger"
                    onClick={() => removeStep(i)}
                    title="Remove"
                  >
                    ✕
                  </button>
                </div>
                {toolMeta && (
                  <div className="composer__step-params">
                    {toolMeta.params.length === 0 ? (
                      <em>(no params)</em>
                    ) : (
                      toolMeta.params.map((p) => (
                        <label key={p}>
                          <span>{p}</span>
                          <input
                            value={step.params[p] ?? ''}
                            placeholder='literal, or "$param"'
                            onChange={(e) =>
                              updateStep(i, (s) => ({
                                ...s,
                                params: { ...s.params, [p]: e.target.value },
                              }))
                            }
                          />
                        </label>
                      ))
                    )}
                    {toolMeta.description && (
                      <div className="composer__step-desc">
                        {toolMeta.description}
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        <button className="link" onClick={addStep}>
          + add step
        </button>

        <div className="composer__actions">
          <label>
            <span>Countdown (s)</span>
            <input
              type="number"
              min={0}
              max={30}
              value={countdown}
              onChange={(e) => setCountdown(Number(e.target.value))}
            />
          </label>
          <button onClick={handleTestRun}>Test draft</button>
          <button className="primary" onClick={handleSave}>
            Save tool
          </button>
        </div>
      </fieldset>

      {message && (
        <div className={`composer__msg composer__msg--${message.kind}`}>
          {message.text}
        </div>
      )}

      {lastResult && (
        <details className="composer__result" open>
          <summary>Last run result</summary>
          <pre>{JSON.stringify(lastResult, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
