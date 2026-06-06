// ToolTree — left sidebar. Groups all registered tools by level (L0, L1, L2+),
// filterable by substring. Clicking a row selects the tool. Below the catalog,
// the captured sidebar icons (perceived draw.io shapes) are listed by category.

import { useMemo, useState } from 'react';
import type { CapturedIcon, ToolSummary } from '../types';

interface Props {
  tools: ToolSummary[];
  icons: CapturedIcon[];
  selected: string | null;
  onSelect: (name: string) => void;
  onReload: () => void;
  onDedupeIcons: () => void;
}

export function ToolTree({
  tools,
  icons,
  selected,
  onSelect,
  onReload,
  onDedupeIcons,
}: Props) {
  const [filter, setFilter] = useState('');
  const [openIcon, setOpenIcon] = useState<string | null>(null);

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

  // Captured icons grouped by category, honoring the same filter.
  const iconGroups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const matched = q
      ? icons.filter(
          (ic) =>
            ic.name.toLowerCase().includes(q) ||
            ic.category.toLowerCase().includes(q),
        )
      : icons;
    const byCat = new Map<string, CapturedIcon[]>();
    for (const ic of matched) {
      if (!byCat.has(ic.category)) byCat.set(ic.category, []);
      byCat.get(ic.category)!.push(ic);
    }
    return Array.from(byCat.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([category, items]) => ({
        category,
        items: items.sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [icons, filter]);

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

      <details className="tool-tree__icons" open>
        <summary>
          <span className="tool-tree__icons-title">
            Captured icons{' '}
            <span className="tool-tree__icons-count">{icons.length}</span>
          </span>
          <button
            type="button"
            className="link tool-tree__icons-dedupe"
            title="Collapse same-shape duplicates to one canonical icon per shape"
            onClick={(e) => {
              e.preventDefault(); // don't toggle the <details>
              onDedupeIcons();
            }}
          >
            dedupe
          </button>
        </summary>
        {iconGroups.length === 0 ? (
          <p className="tool-tree__icons-empty">
            {icons.length === 0 ? 'No icons captured yet.' : 'No icons match the filter.'}
          </p>
        ) : (
          <div className="tool-tree__icons-list">
            {iconGroups.map(({ category, items }) => (
              <section key={category} className="tool-tree__icon-group">
                <header>
                  {category}
                  <span className="tool-tree__icon-cnt">{items.length}</span>
                </header>
                <ul>
                  {items.map((ic) => {
                    const open = openIcon === ic.name;
                    return (
                      <li
                        key={ic.name}
                        className={
                          'tool-tree__icon' + (open ? ' tool-tree__icon--open' : '')
                        }
                      >
                        <button
                          type="button"
                          className="tool-tree__icon-row"
                          aria-expanded={open}
                          onClick={() => setOpenIcon(open ? null : ic.name)}
                        >
                          <span className="tool-tree__icon-caret">
                            {open ? '▾' : '▸'}
                          </span>
                          <code className="tool-tree__icon-name">{ic.name}</code>
                        </button>
                        {open && (
                          <dl className="tool-tree__icon-detail">
                            <dt>category</dt>
                            <dd>{ic.category}</dd>
                            <dt>position</dt>
                            <dd>
                              x={ic.x}, y={ic.y}
                            </dd>
                            <dt>size</dt>
                            <dd>
                              {ic.w} × {ic.h}
                            </dd>
                            <dt>center</dt>
                            <dd>
                              ({ic.x + Math.floor(ic.w / 2)},{' '}
                              {ic.y + Math.floor(ic.h / 2)})
                            </dd>
                            <dt>place_shape</dt>
                            <dd>
                              <code>tool_name="{ic.name}"</code>
                            </dd>
                          </dl>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </details>
    </aside>
  );
}
