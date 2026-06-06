// ToolDetail — shows the selected tool's metadata, params, children, and
// (for compound tools) the full step list. Pure inspection — execution and
// editing live in their own panels.

import type { ToolDetail as Detail } from '../types';

interface Props {
  tool: Detail | null;
  onDelete: (name: string) => void;
  onCloneToComposer: (tool: Detail) => void;
}

export function ToolDetail({ tool, onDelete, onCloneToComposer }: Props) {
  if (!tool) {
    return (
      <div className="panel tool-detail tool-detail--empty">
        <p>Select a tool from the catalog to inspect it.</p>
      </div>
    );
  }
  return (
    <div className="panel tool-detail">
      <header className="panel__header">
        <h2>
          <span className="badge">L{tool.level}</span>
          {tool.name}
        </h2>
        <div className="panel__actions">
          {tool.steps && tool.steps.length > 0 && (
            <button onClick={() => onCloneToComposer(tool)}>
              Edit in composer
            </button>
          )}
          {/* Delete is offered only for L1+ tools — these are JSON-backed
              (operands / compounds) and safe to remove. L0 atoms are Python
              primitives with no file to delete. */}
          {tool.level >= 1 && tool.has_json && (
            <button
              className="danger"
              title={`Delete this L${tool.level} tool (removes its JSON from state/tools/)`}
              onClick={() => {
                if (
                  confirm(
                    `Delete L${tool.level} tool "${tool.name}"? This removes its definition from state/tools/.`,
                  )
                )
                  onDelete(tool.name);
              }}
            >
              Delete
            </button>
          )}
        </div>
      </header>
      <p className="tool-detail__desc">{tool.description || '(no description)'}</p>

      <dl className="tool-detail__meta">
        <dt>Level</dt>
        <dd>L{tool.level}</dd>
        <dt>Leaf</dt>
        <dd>{tool.is_leaf ? 'yes' : 'no'}</dd>
        <dt>Params</dt>
        <dd>
          {tool.params.length === 0 ? (
            <em>(none)</em>
          ) : (
            tool.params.map((p) => (
              <code key={p} className="chip">
                {p}
              </code>
            ))
          )}
        </dd>
        <dt>Children</dt>
        <dd>
          {tool.children.length === 0 ? (
            <em>(none)</em>
          ) : (
            tool.children.map((c) => (
              <code key={c} className="chip">
                {c}
              </code>
            ))
          )}
        </dd>
        {tool.python_fn && (
          <>
            <dt>Python fn</dt>
            <dd>
              <code>{tool.python_fn}</code>
            </dd>
          </>
        )}
      </dl>

      {tool.steps && tool.steps.length > 0 && (
        <section>
          <h3>Steps</h3>
          <ol className="tool-detail__steps">
            {tool.steps.map((s, i) => (
              <li key={i}>
                <code>{s.tool}</code>
                <span className="tool-detail__step-params">
                  {Object.keys(s.params).length === 0
                    ? ''
                    : `(${Object.entries(s.params)
                        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                        .join(', ')})`}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {tool.raw_definition && (
        <details className="tool-detail__raw">
          <summary>Raw JSON</summary>
          <pre>{JSON.stringify(tool.raw_definition, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
