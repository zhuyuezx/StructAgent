import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { ComposerForm } from './components/ComposerForm';
import { ExecutePanel } from './components/ExecutePanel';
import { ExplorePanel } from './components/ExplorePanel';
import { PlanPanel } from './components/PlanPanel';
import { SceneGraphView } from './components/SceneGraphView';
import { ToolDetail } from './components/ToolDetail';
import { ToolTree } from './components/ToolTree';
import type {
  CapturedIcon,
  SceneGraph,
  TargetStatusResult,
  ToolDetail as Detail,
  ToolSummary,
} from './types';

type Tab = 'inspect' | 'execute' | 'compose' | 'plan' | 'explore';

export default function App() {
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [icons, setIcons] = useState<CapturedIcon[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [composerSeed, setComposerSeed] = useState<Detail | null>(null);
  const [sceneGraph, setSceneGraph] = useState<SceneGraph | null>(null);
  const [tab, setTab] = useState<Tab>('inspect');
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [domains, setDomains] = useState<string[]>([]);
  const [activeDomain, setActiveDomain] = useState<string>('drawio');
  const [targetStatus, setTargetStatus] = useState<TargetStatusResult | null>(null);

  // Soft reload: just re-fetch the catalog from server memory.
  const reloadTools = useCallback(async () => {
    try {
      const list = await api.listTools();
      setTools(list);
      setGlobalError(null);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  // Hard reload: rescan state/tools/ on disk to pick up files added or
  // removed without going through the API.
  const rescanTools = useCallback(async () => {
    try {
      const res = await api.reloadTools();
      setTools(res.tools);
      const parts: string[] = [];
      if (res.added.length) parts.push(`+${res.added.join(', ')}`);
      if (res.removed.length) parts.push(`-${res.removed.join(', ')}`);
      setGlobalError(
        parts.length
          ? `Rescanned: ${parts.join(' · ')} (${res.total} total)`
          : null,
      );
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  const reloadSceneGraph = useCallback(async () => {
    try {
      const sg = await api.getSceneGraph();
      setSceneGraph(sg);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  const reloadIcons = useCallback(async () => {
    try {
      const ui = await api.getUiGraph();
      setIcons(ui.icons);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  // Collapse same-shape duplicate icons to one canonical icon per shape.
  const dedupeIcons = useCallback(async () => {
    try {
      const ui = await api.dedupeIcons();
      setIcons(ui.icons);
      setGlobalError(null);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  const reloadDomains = useCallback(async () => {
    try {
      const res = await api.getDomains();
      setDomains(res.available);
      setActiveDomain(res.active);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  const reloadTarget = useCallback(async () => {
    try {
      const res = await api.targetStatus();
      setTargetStatus(res);
    } catch (e) {
      setGlobalError(String(e));
    }
  }, []);

  useEffect(() => {
    reloadTools();
    reloadSceneGraph();
    reloadIcons();
    reloadDomains();
    reloadTarget();
  }, [reloadTools, reloadSceneGraph, reloadIcons, reloadDomains, reloadTarget]);

  // Switch the active interface: backend swaps the live ui_graph + resets the
  // canvas; we then re-pull everything tied to the interface.
  const handleDomainChange = useCallback(
    async (name: string) => {
      if (name === activeDomain) return;
      try {
        const res = await api.setDomain({ domain: name });
        setActiveDomain(res.active);
        setSelected(null);
        await Promise.all([reloadTools(), reloadIcons(), reloadSceneGraph()]);
        setGlobalError(null);
      } catch (e) {
        setGlobalError(String(e));
      }
    },
    [activeDomain, reloadTools, reloadIcons, reloadSceneGraph],
  );

  // Fetch detail when selection changes.
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getTool(selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => setGlobalError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [selected, tools]);

  async function handleDelete(name: string) {
    try {
      await api.deleteTool(name);
      if (selected === name) setSelected(null);
      await reloadTools();
    } catch (e) {
      setGlobalError(String(e));
    }
  }

  function handleCloneToComposer(t: Detail) {
    setComposerSeed(t);
    setTab('compose');
  }

  async function handleResetSceneGraph() {
    if (!confirm('Reset the scene graph? (does not touch draw.io)')) return;
    try {
      const sg = await api.resetSceneGraph();
      setSceneGraph(sg);
    } catch (e) {
      setGlobalError(String(e));
    }
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>StructAgent Studio</h1>
        <nav>
          <button
            className={tab === 'inspect' ? 'active' : ''}
            onClick={() => setTab('inspect')}
          >
            Inspect
          </button>
          <button
            className={tab === 'execute' ? 'active' : ''}
            onClick={() => setTab('execute')}
          >
            Execute
          </button>
          <button
            className={tab === 'compose' ? 'active' : ''}
            onClick={() => setTab('compose')}
          >
            Compose
          </button>
          <button
            className={tab === 'plan' ? 'active' : ''}
            onClick={() => setTab('plan')}
          >
            Plan
          </button>
          <button
            className={tab === 'explore' ? 'active' : ''}
            onClick={() => setTab('explore')}
          >
            Explore
          </button>
        </nav>
        {globalError && <div className="app__error">{globalError}</div>}
        <label className="app__domain">
          <span>Interface</span>
          <select
            value={activeDomain}
            onChange={(e) => handleDomainChange(e.target.value)}
          >
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <button
          className={`app__target ${targetStatus?.connected ? 'ok' : 'warn'}`}
          onClick={async () => {
            try {
              const res = await api.targetRefresh();
              setTargetStatus(res);
              setGlobalError(null);
            } catch (e) {
              setGlobalError(String(e));
            }
          }}
          title={targetStatus?.url || targetStatus?.error || 'Target status'}
        >
          {targetStatus?.backend ?? 'target'}: {targetStatus?.connected ? 'ready' : 'missing'}
        </button>
      </header>

      <main className={`app__main ${tab === 'explore' ? 'app__main--full' : ''}`}>
        {tab !== 'explore' && (
          <ToolTree
            tools={tools}
            icons={icons}
            selected={selected}
            onSelect={setSelected}
            onReload={rescanTools}
            onDedupeIcons={dedupeIcons}
          />
        )}

        <section className="app__content">
          {tab === 'inspect' && (
            <ToolDetail
              tool={detail}
              onDelete={handleDelete}
              onCloneToComposer={handleCloneToComposer}
            />
          )}
          {tab === 'execute' && (
            <ExecutePanel tool={detail} onSceneGraphUpdated={reloadSceneGraph} />
          )}
          {tab === 'compose' && (
            <ComposerForm
              tools={tools}
              prefill={composerSeed}
              onSaved={() => {
                setComposerSeed(null);
                reloadTools();
              }}
            />
          )}
          {tab === 'plan' && (
            <PlanPanel
              tools={tools}
              onSceneGraphUpdated={reloadSceneGraph}
              onToolSaved={reloadTools}
            />
          )}
          {tab === 'explore' && (
            <ExplorePanel key={activeDomain} domain={activeDomain} />
          )}
        </section>

        {tab !== 'explore' && (
          <aside className="app__sidebar-right">
            <SceneGraphView
              graph={sceneGraph}
              onReset={handleResetSceneGraph}
              onRefresh={reloadSceneGraph}
            />
          </aside>
        )}
      </main>
    </div>
  );
}
