// ExecutePanel — runs the currently selected tool with user-supplied params.
// Shows the dispatched result and updates the live scene graph view above it.

import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { RunResult, ToolDetail } from '../types';

interface Props {
  tool: ToolDetail | null;
  onSceneGraphUpdated: () => void;
}

export function ExecutePanel({ tool, onSceneGraphUpdated }: Props) {
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [countdown, setCountdown] = useState(5);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset form whenever the selected tool changes.
  useEffect(() => {
    setParamValues({});
    setResult(null);
    setError(null);
  }, [tool?.name]);

  const requiredParams = useMemo(() => tool?.params ?? [], [tool]);

  async function handleRun() {
    if (!tool) return;
    const params: Record<string, unknown> = {};
    for (const key of requiredParams) {
      const raw = paramValues[key];
      if (raw === undefined || raw === '') continue;
      try {
        params[key] = JSON.parse(raw);
      } catch {
        params[key] = raw;
      }
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.runTool(tool.name, { params, countdown });
      setResult(r);
      onSceneGraphUpdated();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!tool) {
    return (
      <div className="panel execute execute--empty">
        <p>Pick a tool from the catalog to run it.</p>
      </div>
    );
  }

  return (
    <div className="panel execute">
      <header className="panel__header">
        <h2>
          Execute · <code>{tool.name}</code>
        </h2>
      </header>
      <fieldset disabled={busy}>
        {requiredParams.length === 0 ? (
          <p className="execute__no-params">
            <em>This tool takes no parameters.</em>
          </p>
        ) : (
          <div className="execute__params">
            {requiredParams.map((p) => (
              <label key={p}>
                <span>{p}</span>
                <input
                  value={paramValues[p] ?? ''}
                  placeholder="literal value (JSON-parsed if possible)"
                  onChange={(e) =>
                    setParamValues((prev) => ({
                      ...prev,
                      [p]: e.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
        )}
        <div className="execute__actions">
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
          <button className="primary" onClick={handleRun}>
            Run
          </button>
        </div>
      </fieldset>

      {error && <div className="composer__msg composer__msg--error">{error}</div>}

      {result && (
        <details className="execute__result" open>
          <summary>
            Result · status=<strong>{result.status}</strong>
          </summary>
          <pre>{JSON.stringify(result.result, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
