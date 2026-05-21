// ToolTree — left sidebar. Groups all registered tools by level (L0, L1, L2+),
// filterable by substring. Clicking a row selects the tool.

import { useMemo, useState } from 'react';
import type { ToolSummary } from '../types';

interface Props {
  tools: ToolSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
  onReload: () => void;
}

export function ToolTree({ tools, selected, onSelect, onReload }: Props) {
  const [filter, setFilter] = useState('');

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const matched = q
      ? tools.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            t.description.toLowerCase().includes(q),
        )
      : tools;
    const byLevel = new Map<number, ToolSummary[]>();
    for (const t of matched) {
      if (!byLevel.has(t.level)) byLevel.set(t.level, []);
      byLevel.get(t.level)!.push(t);
    }
    return Array.from(byLevel.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([lvl, list]) => ({
        level: lvl,
        tools: list.sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [tools, filter]);

  return (
    <aside className="tool-tree">
      <div className="tool-tree__header">
        <h2>Tool catalog</h2>
        <button
          className="link"
          onClick={onReload}
          title="Rescan state/tools/ on disk (pick up added/removed/edited JSON)"
        >
          ↻
        </button>
      </div>
      <input
        className="tool-tree__filter"
        placeholder="filter…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="tool-tree__counts">
        {tools.length} tools · {groups.length} levels
      </div>
      <div className="tool-tree__list">
        {groups.map(({ level, tools: list }) => (
          <section key={level} className="tool-tree__group">
            <header>L{level}</header>
            <ul>
              {list.map((t) => (
                <li
                  key={t.name}
                  className={
                    'tool-tree__item' +
                    (t.name === selected ? ' tool-tree__item--selected' : '')
                  }
                  onClick={() => onSelect(t.name)}
                  title={t.description}
                >
                  <span className="tool-tree__name">{t.name}</span>
                  {t.params.length > 0 && (
                    <span className="tool-tree__params">
                      ({t.params.join(', ')})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}
