// SceneGraphView — compact read-only summary of the current scene graph.
// Mirrors the text-based summary the executor prompt uses.

import type { SceneGraph } from '../types';

interface Props {
  graph: SceneGraph | null;
  onReset: () => void;
  onRefresh: () => void;
}

export function SceneGraphView({ graph, onReset, onRefresh }: Props) {
  const objects = graph?.objects ?? [];
  const edges = graph?.edges ?? [];
  const meta = graph?.metadata;
  return (
    <div className="panel scene">
      <header className="panel__header">
        <h2>Scene graph</h2>
        <div className="panel__actions">
          <button className="link" onClick={onRefresh} title="Refresh">
            ↻
          </button>
          <button className="danger" onClick={onReset} title="Reset (wipe)">
            Reset
          </button>
        </div>
      </header>
      {objects.length === 0 ? (
        <p className="scene__empty">
          <em>Canvas is empty.</em>
        </p>
      ) : (
        <ul className="scene__objects">
          {objects.map((o) => (
            <li key={o.id} className={o.selected ? 'scene__obj--selected' : ''}>
              <code>{o.id}</code> {o.type}
              {o.label && <> "{o.label}"</>}{' '}
              {o.bbox ? (
                <span className="scene__bbox">
                  [{o.bbox[0]},{o.bbox[1]},{o.bbox[2]}×{o.bbox[3]}]
                </span>
              ) : (
                <span className="scene__bbox">bbox=?</span>
              )}
              {o.selected && <span className="scene__selected"> SELECTED</span>}
            </li>
          ))}
        </ul>
      )}
      {edges.length > 0 && (
        <>
          <h3>Edges</h3>
          <ul className="scene__edges">
            {edges.map((e) => (
              <li key={e.id}>
                <code>{e.id}</code>{' '}
                <code>{e.source}</code>.{e.source_anchor} →{' '}
                <code>{e.target}</code>.{e.target_anchor}
                {e.label && <> "{e.label}"</>}
              </li>
            ))}
          </ul>
        </>
      )}
      {meta?.last_op && (
        <p className="scene__meta">
          op #{meta.op_count}, last: <code>{meta.last_op}</code>
        </p>
      )}
    </div>
  );
}
