import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { ComposerForm } from './components/ComposerForm';
import { ExecutePanel } from './components/ExecutePanel';
import { SceneGraphView } from './components/SceneGraphView';
import { ToolDetail } from './components/ToolDetail';
import { ToolTree } from './components/ToolTree';
import type {
  SceneGraph,
  ToolDetail as Detail,
  ToolSummary,
} from './types';

type Tab = 'inspect' | 'execute' | 'compose';

export default function App() {
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [composerSeed, setComposerSeed] = useState<Detail | null>(null);
  const [sceneGraph, setSceneGraph] = useState<SceneGraph | null>(null);
  const [tab, setTab] = useState<Tab>('inspect');
  const [globalError, setGlobalError] = useState<string | null>(null);

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

  useEffect(() => {
    reloadTools();
    reloadSceneGraph();
  }, [reloadTools, reloadSceneGraph]);

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
        </nav>
        {globalError && <div className="app__error">{globalError}</div>}
      </header>

      <main className="app__main">
        <ToolTree
          tools={tools}
          selected={selected}
          onSelect={setSelected}
          onReload={rescanTools}
        />

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
        </section>

        <aside className="app__sidebar-right">
          <SceneGraphView
            graph={sceneGraph}
            onReset={handleResetSceneGraph}
            onRefresh={reloadSceneGraph}
          />
        </aside>
      </main>
    </div>
  );
}
