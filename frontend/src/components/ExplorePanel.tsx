// ExplorePanel — screenshot + CV bounding-box overlay, interactive labeling.
//
// Workflow:
//   1. Set countdown, click "Capture & Detect" → backend screenshots +
//      runs CV to find icon-sized regions → SVG boxes appear on screenshot.
//   2. Drag on the image to add a new box; click a box / list row to select.
//   3. Edit labels inline in the list, or click "AI" to let the VLM label
//      that icon; "AI Label All" labels the whole working set at once.
//   4. Click "Save to ui_graph.json" → persists to disk + reloads live catalog.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ExploreIcon } from '../types';

// Colors for selected vs normal box
const CLR_NORMAL = { fill: 'rgba(0,255,100,0.08)', stroke: '#00c864' };
const CLR_SELECTED = { fill: 'rgba(0,200,255,0.18)', stroke: '#00c8ff' };
const CLR_DRAW = { fill: 'rgba(255,107,0,0.12)', stroke: '#ff6b00' };

// Minimum box side length (in logical px) to register a drag as a new icon
const MIN_BOX_PX = 8;

type LoadingState =
  | null
  | 'detecting'
  | 'label-all'
  | { kind: 'label-one'; index: number }
  | 'saving';

interface DrawState {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

function stopEv(e: React.SyntheticEvent) {
  e.stopPropagation();
}

export function ExplorePanel() {
  const [icons, setIcons] = useState<ExploreIcon[]>([]);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [logicalW, setLogicalW] = useState(0);
  const [logicalH, setLogicalH] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [loading, setLoading] = useState<LoadingState>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(5);
  const [drawing, setDrawing] = useState<DrawState | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Scroll selected list row into view when selection changes
  useEffect(() => {
    if (selectedIdx === null) return;
    rowRefs.current[selectedIdx]?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  // --- SVG coordinate helper -------------------------------------------
  function svgCoords(e: React.MouseEvent): { x: number; y: number } | null {
    if (!svgRef.current) return null;
    const pt = svgRef.current.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const inv = svgRef.current.getScreenCTM()?.inverse();
    if (!inv) return null;
    const p = pt.matrixTransform(inv);
    return { x: p.x, y: p.y };
  }

  // --- Detect -----------------------------------------------------------
  const handleDetect = useCallback(async () => {
    setError(null);
    setStatus(null);
    setLoading('detecting');
    try {
      const res = await api.exploreDetect({ countdown });
      setScreenshot(res.screenshot);
      setLogicalW(res.logical_width);
      setLogicalH(res.logical_height);
      setIcons(res.icons);
      setSelectedIdx(null);
      setStatus(`Detected ${res.icons.length} icon(s).`);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }, [countdown]);

  // --- AI label all ----------------------------------------------------
  const handleLabelAll = useCallback(async () => {
    if (!screenshot) { setError('Detect first.'); return; }
    setError(null);
    setStatus(null);
    setLoading('label-all');
    try {
      const res = await api.exploreLabel({ icons, indices: null });
      setIcons(res.icons);
      setStatus('AI labeling complete.');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }, [screenshot, icons]);

  // --- AI label one ----------------------------------------------------
  const handleLabelOne = useCallback(async (idx: number) => {
    if (!screenshot) { setError('Detect first.'); return; }
    setError(null);
    setLoading({ kind: 'label-one', index: idx });
    try {
      const res = await api.exploreLabel({ icons, indices: [idx] });
      setIcons(res.icons);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }, [screenshot, icons]);

  // --- Save ------------------------------------------------------------
  const handleSave = useCallback(async () => {
    if (icons.length === 0) { setError('Nothing to save.'); return; }
    setError(null);
    setStatus(null);
    setLoading('saving');
    try {
      const res = await api.exploreSave({ icons });
      setStatus(`Saved ${res.saved} icon(s) → ${res.path}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }, [icons]);

  // --- Manual label edit -----------------------------------------------
  function updateLabel(idx: number, label: string) {
    setIcons(prev => prev.map((ic, i) => i === idx ? { ...ic, label } : ic));
  }

  // --- Delete icon -----------------------------------------------------
  function deleteIcon(idx: number) {
    setIcons(prev => prev.filter((_, i) => i !== idx));
    setSelectedIdx(prev =>
      prev === null ? null : prev === idx ? null : prev > idx ? prev - 1 : prev
    );
  }

  // --- SVG drag: add new box -------------------------------------------
  function onSvgMouseDown(e: React.MouseEvent<SVGSVGElement>) {
    if (e.button !== 0) return;
    const c = svgCoords(e);
    if (!c) return;
    setDrawing({ startX: c.x, startY: c.y, curX: c.x, curY: c.y });
    setSelectedIdx(null);
  }

  function onSvgMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!drawing) return;
    const c = svgCoords(e);
    if (!c) return;
    setDrawing(d => d ? { ...d, curX: c.x, curY: c.y } : null);
  }

  function onSvgMouseUp(e: React.MouseEvent<SVGSVGElement>) {
    if (!drawing) return;
    const c = svgCoords(e);
    const cur = c ?? { x: drawing.curX, y: drawing.curY };
    const rx1 = Math.min(drawing.startX, cur.x);
    const ry1 = Math.min(drawing.startY, cur.y);
    const rw  = Math.abs(cur.x - drawing.startX);
    const rh  = Math.abs(cur.y - drawing.startY);
    if (rw >= MIN_BOX_PX && rh >= MIN_BOX_PX) {
      const newIcon: ExploreIcon = {
        x: Math.round(rx1 + rw / 2),
        y: Math.round(ry1 + rh / 2),
        w: Math.round(rw),
        h: Math.round(rh),
        label: null,
      };
      setIcons(prev => {
        const next = [...prev, newIcon];
        setSelectedIdx(next.length - 1);
        return next;
      });
    }
    setDrawing(null);
  }

  // Draw-preview rect dimensions
  const dpX1 = drawing ? Math.min(drawing.startX, drawing.curX) : 0;
  const dpY1 = drawing ? Math.min(drawing.startY, drawing.curY) : 0;
  const dpW  = drawing ? Math.abs(drawing.curX - drawing.startX) : 0;
  const dpH  = drawing ? Math.abs(drawing.curY - drawing.startY) : 0;

  const isBusy = loading !== null;

  return (
    <div className="explore-panel">
      {/* ── Toolbar ─────────────────────────────────────────────────── */}
      <div className="explore-toolbar">
        <label className="explore-countdown-label">
          Countdown&nbsp;
          <input
            type="number"
            min={0}
            max={30}
            value={countdown}
            onChange={e => setCountdown(Number(e.target.value))}
            className="explore-countdown-input"
            disabled={isBusy}
          />
          s
        </label>

        <button
          className="explore-btn explore-btn--primary"
          onClick={handleDetect}
          disabled={isBusy}
        >
          {loading === 'detecting' ? '⏳ Detecting…' : '📸 Capture & Detect'}
        </button>

        <button
          className="explore-btn"
          onClick={handleLabelAll}
          disabled={isBusy || !screenshot || icons.length === 0}
        >
          {loading === 'label-all' ? '⏳ Labeling…' : '🤖 AI Label All'}
        </button>

        <button
          className="explore-btn explore-btn--save"
          onClick={handleSave}
          disabled={isBusy || icons.length === 0}
        >
          {loading === 'saving' ? '⏳ Saving…' : '💾 Save to ui_graph.json'}
        </button>

        <span className="explore-count">
          {icons.length > 0 && `${icons.length} icon${icons.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      {error  && <div className="explore-error">{error}</div>}
      {status && !error && <div className="explore-status">{status}</div>}

      {/* ── Main split ──────────────────────────────────────────────── */}
      <div className="explore-main">
        {/* Left: screenshot + SVG overlay */}
        <div className="explore-image-col">
          {!screenshot && (
            <div className="explore-placeholder">
              Click <strong>Capture &amp; Detect</strong> to start.
              <br />
              Switch to the target application before the countdown ends.
            </div>
          )}
          {screenshot && (
            <div className="explore-image-wrap">
              <img
                src={api.screenshotUrl(screenshot)}
                alt="Screenshot"
                className="explore-screenshot"
                draggable={false}
              />
              <svg
                ref={svgRef}
                className="explore-svg"
                viewBox={`0 0 ${logicalW} ${logicalH}`}
                preserveAspectRatio="none"
                onMouseDown={onSvgMouseDown}
                onMouseMove={onSvgMouseMove}
                onMouseUp={onSvgMouseUp}
                onMouseLeave={onSvgMouseUp}
                style={{ cursor: drawing ? 'crosshair' : 'crosshair' }}
              >
                {/* Existing icon boxes */}
                {icons.map((ic, i) => {
                  const sel = selectedIdx === i;
                  const clr = sel ? CLR_SELECTED : CLR_NORMAL;
                  const bx = ic.x - ic.w / 2;
                  const by = ic.y - ic.h / 2;
                  const labelBusy =
                    loading !== null &&
                    typeof loading === 'object' &&
                    loading.kind === 'label-one' &&
                    loading.index === i;
                  return (
                    <g key={i}>
                      <rect
                        x={bx}
                        y={by}
                        width={ic.w}
                        height={ic.h}
                        fill={clr.fill}
                        stroke={clr.stroke}
                        strokeWidth={sel ? 2 : 1.5}
                        onMouseDown={(e) => { stopEv(e); setSelectedIdx(i); }}
                        style={{ cursor: 'pointer' }}
                      />
                      <text
                        x={ic.x}
                        y={by - 3}
                        textAnchor="middle"
                        fill={labelBusy ? '#ffaa00' : clr.stroke}
                        fontSize={10}
                        style={{ pointerEvents: 'none', userSelect: 'none' }}
                      >
                        {labelBusy ? '…' : (ic.label || `#${i + 1}`)}
                      </text>
                    </g>
                  );
                })}

                {/* Draw preview */}
                {drawing && dpW >= MIN_BOX_PX && dpH >= MIN_BOX_PX && (
                  <rect
                    x={dpX1}
                    y={dpY1}
                    width={dpW}
                    height={dpH}
                    fill={CLR_DRAW.fill}
                    stroke={CLR_DRAW.stroke}
                    strokeWidth={1.5}
                    strokeDasharray="6 3"
                    style={{ pointerEvents: 'none' }}
                  />
                )}
              </svg>
            </div>
          )}
          {screenshot && (
            <p className="explore-drag-hint">
              Drag on the image to add a bounding box.
            </p>
          )}
        </div>

        {/* Right: icon list */}
        <div className="explore-list-col" ref={listRef}>
          {icons.length === 0 && screenshot && (
            <p className="explore-empty-list">No icons detected. Drag on the image to add boxes.</p>
          )}
          {icons.map((ic, i) => {
            const sel = selectedIdx === i;
            const labelBusy =
              loading !== null &&
              typeof loading === 'object' &&
              loading.kind === 'label-one' &&
              loading.index === i;
            return (
              <div
                key={i}
                ref={el => { rowRefs.current[i] = el; }}
                className={`explore-row ${sel ? 'explore-row--selected' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                <span className="explore-row-idx">{i + 1}</span>

                <input
                  className="explore-row-label"
                  value={ic.label ?? ''}
                  placeholder="(no label)"
                  onChange={e => updateLabel(i, e.target.value)}
                  onClick={stopEv}
                />

                <span className="explore-row-coords">
                  {ic.x},{ic.y} {ic.w}×{ic.h}
                </span>

                <button
                  className="explore-row-btn"
                  title="AI label this icon"
                  disabled={isBusy || !screenshot}
                  onClick={e => { stopEv(e); handleLabelOne(i); }}
                >
                  {labelBusy ? '⏳' : '🤖'}
                </button>

                <button
                  className="explore-row-btn explore-row-btn--del"
                  title="Remove this icon"
                  disabled={isBusy}
                  onClick={e => { stopEv(e); deleteIcon(i); }}
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
