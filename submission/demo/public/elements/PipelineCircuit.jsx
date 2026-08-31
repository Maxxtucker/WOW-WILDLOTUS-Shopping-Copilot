import React from "react";

const NODE_W = 190;
const NODE_H = 48;
const FIT_PADDING = 0.94;
const MIN_SCALE_RATIO = 0.8;
const MAX_SCALE = 4.5;

function formatElapsed(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function statusTone(status) {
  if (status === "completed") return "#25f4ee";
  if (status === "running") return "#fe2c55";
  if (status === "error") return "#ff6b8a";
  if (status === "skipped") return "rgba(247,243,255,0.32)";
  return "rgba(196,181,253,0.72)";
}

function nodeFill(status) {
  if (status === "completed") return "rgba(37,244,238,0.14)";
  if (status === "running") return "rgba(254,44,85,0.18)";
  if (status === "error") return "rgba(255,107,138,0.16)";
  if (status === "skipped") return "rgba(247,243,255,0.03)";
  return "rgba(196,181,253,0.07)";
}

function nodeStroke(status) {
  if (status === "completed") return "rgba(37,244,238,0.62)";
  if (status === "running") return "#fe2c55";
  if (status === "error") return "#ff6b8a";
  if (status === "skipped") return "rgba(247,243,255,0.1)";
  return "rgba(196,181,253,0.22)";
}

function liveStatus(status) {
  return status === "completed" || status === "running";
}

function edgeLit(nodes, from, to) {
  return liveStatus(nodes[from]?.status) && liveStatus(nodes[to]?.status);
}

function box(position) {
  return {
    left: position.x - NODE_W / 2,
    right: position.x + NODE_W / 2,
    top: position.y - NODE_H / 2,
    bottom: position.y + NODE_H / 2,
    cx: position.x,
    cy: position.y,
  };
}

function edgePath(fromPosition, toPosition) {
  const a = box(fromPosition);
  const b = box(toPosition);
  const sameRow = Math.abs(a.cy - b.cy) < 5;
  const sameColumn = Math.abs(a.cx - b.cx) < 5;
  if (sameRow) {
    const rightward = a.cx < b.cx;
    const startX = rightward ? a.right : a.left;
    const endX = rightward ? b.left : b.right;
    const bend = Math.min(22, Math.abs(endX - startX) / 3);
    const direction = rightward ? 1 : -1;
    return [
      `M ${startX} ${a.cy}`,
      `C ${startX + direction * bend} ${a.cy}`,
      `${endX - direction * bend} ${b.cy}`,
      `${endX} ${b.cy}`,
    ].join(" ");
  }
  if (sameColumn) {
    const downward = a.cy < b.cy;
    const startY = downward ? a.bottom : a.top;
    const endY = downward ? b.top : b.bottom;
    const rise = Math.abs(endY - startY);
    if (rise > 500) {
      const bow = 280;
      const mid1 = startY + (endY - startY) * 0.28;
      const mid2 = startY + (endY - startY) * 0.72;
      return `M ${a.cx} ${startY} C ${a.cx + bow} ${mid1} ${a.cx + bow} ${mid2} ${b.cx} ${endY}`;
    }
    return `M ${a.cx} ${startY} L ${b.cx} ${endY}`;
  }

  const downward = a.cy < b.cy;
  const start = { x: a.cx, y: downward ? a.bottom : a.top };
  const end = { x: b.cx, y: downward ? b.top : b.bottom };
  const rise = Math.abs(end.y - start.y);
  const run = Math.abs(end.x - start.x);
  const pull = Math.max(36, Math.min(120, rise * 0.55, run * 0.45));
  const sign = downward ? 1 : -1;
  return [
    `M ${start.x} ${start.y}`,
    `C ${start.x} ${start.y + sign * pull}`,
    `${end.x} ${end.y - sign * pull}`,
    `${end.x} ${end.y}`,
  ].join(" ");
}

function sendAction(name, payload) {
  if (typeof callAction === "function") callAction({ name, payload });
}

function inspectNode(id, turn) {
  sendAction("inspect_node", { node: id, turn: turn || 0 });
}

function parseViewBox(value) {
  const parts = String(value || "0 0 1200 800")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  return {
    minX: Number.isFinite(parts[0]) ? parts[0] : 0,
    minY: Number.isFinite(parts[1]) ? parts[1] : 0,
    width: parts[2] > 0 ? parts[2] : 1200,
    height: parts[3] > 0 ? parts[3] : 800,
  };
}

function fitTransform(viewport, world) {
  if (!viewport.width || !viewport.height) {
    return { x: 0, y: 0, k: 1 };
  }
  const scale =
    Math.min(viewport.width / world.width, viewport.height / world.height) *
    FIT_PADDING;
  return {
    x: (viewport.width - world.width * scale) / 2 - world.minX * scale,
    y: (viewport.height - world.height * scale) / 2 - world.minY * scale,
    k: scale,
  };
}

const VIEWPORT_STORE_KEY = "__convergePipelineViewport";

function viewportStore() {
  const root = typeof globalThis !== "undefined" ? globalThis : {};
  if (!root[VIEWPORT_STORE_KEY]) {
    root[VIEWPORT_STORE_KEY] = { lastGraphId: "", byGraph: {} };
  }
  return root[VIEWPORT_STORE_KEY];
}

function peekCanvasCache(graphId) {
  if (!graphId) return null;
  return viewportStore().byGraph[graphId] || null;
}

function writeCanvasCache(graphId, next, userAdjusted) {
  if (!graphId || !next) return;
  const store = viewportStore();
  store.lastGraphId = graphId;
  store.byGraph[graphId] = {
    x: next.x,
    y: next.y,
    k: next.k,
    userAdjusted: !!userAdjusted,
  };
}

function consumeCanvasCache(graphId) {
  const store = viewportStore();
  if (!graphId) return null;
  if (store.lastGraphId && store.lastGraphId !== graphId) {
    delete store.byGraph[store.lastGraphId];
    store.lastGraphId = graphId;
    return null;
  }
  store.lastGraphId = graphId;
  return store.byGraph[graphId] || null;
}

function cachedTransform(graphId) {
  const cached = peekCanvasCache(graphId);
  if (cached && cached.userAdjusted) {
    return { x: cached.x, y: cached.y, k: cached.k };
  }
  return { x: 0, y: 0, k: 1 };
}

function stageLabel(graph, stageId) {
  const title = String(graph?.title || "").split("·")[0].trim();
  if (title) return title;
  return String(stageId || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function NodeGlyph({ id, position, node, selected, turn, onInspect }) {
  const running = node.status === "running";
  const tone = statusTone(node.status);
  return (
    <g
      onClick={() => {
        if (typeof onInspect === "function") onInspect(id);
        inspectNode(id, turn);
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      style={{ cursor: "pointer" }}
    >
      <rect
        x={position.x - NODE_W / 2}
        y={position.y - NODE_H / 2}
        width={NODE_W}
        height={NODE_H}
        rx="13"
        fill={nodeFill(node.status)}
        stroke={selected ? "#25f4ee" : nodeStroke(node.status)}
        strokeWidth={selected || running ? 2.2 : 1.2}
        style={
          running
            ? { filter: "drop-shadow(0 0 10px rgba(37,244,238,0.7))" }
            : {}
        }
      />
      <foreignObject
        x={position.x - NODE_W / 2 + 9}
        y={position.y - NODE_H / 2 + 4}
        width={NODE_W - 18}
        height={NODE_H - 8}
        style={{ pointerEvents: "none" }}
      >
        <div
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            textAlign: "center",
            color:
              node.status === "skipped"
                ? "rgba(255,255,255,0.38)"
                : "#f5f7fb",
            fontSize: 12,
            lineHeight: 1.15,
            fontWeight: 650,
          }}
        >
          <span>{node.label || id}</span>
          {node.summary ? (
            <span
              style={{
                marginTop: 3,
                color:
                  node.status === "skipped"
                    ? "rgba(255,255,255,0.25)"
                    : tone,
                fontSize: 9.5,
                fontWeight: 600,
                maxWidth: "100%",
                overflow: "hidden",
                whiteSpace: "nowrap",
                textOverflow: "ellipsis",
              }}
            >
              {node.summary}
            </span>
          ) : null}
        </div>
      </foreignObject>
    </g>
  );
}

function GraphCanvas({
  graph,
  graphId,
  positions,
  edges,
  nodes,
  selectedNode,
  turn,
  onInspect,
}) {
  const viewportRef = React.useRef(null);
  const worldGroupRef = React.useRef(null);
  const initial = cachedTransform(graphId);
  const transformRef = React.useRef(initial);
  const fitScaleRef = React.useRef(1);
  const dragRef = React.useRef(null);
  const sizeRef = React.useRef({ width: 0, height: 0 });
  const userAdjustedRef = React.useRef(!!peekCanvasCache(graphId)?.userAdjusted);
  const [transform, setTransformState] = React.useState(initial);
  const [panning, setPanning] = React.useState(false);
  const world = React.useMemo(
    () => parseViewBox(graph.viewBox),
    [graph.viewBox]
  );

  const applyTransform = React.useCallback(
    (next) => {
      transformRef.current = next;
      setTransformState(next);
      if (worldGroupRef.current) {
        worldGroupRef.current.setAttribute(
          "transform",
          `translate(${next.x} ${next.y}) scale(${next.k})`
        );
      }
      writeCanvasCache(graphId, next, userAdjustedRef.current);
    },
    [graphId]
  );

  const fitToView = React.useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const fitted = fitTransform(
      { width: rect.width, height: rect.height },
      world
    );
    fitScaleRef.current = fitted.k;
    sizeRef.current = { width: rect.width, height: rect.height };
    userAdjustedRef.current = false;
    applyTransform(fitted);
  }, [applyTransform, world]);

  React.useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const rect = viewport.getBoundingClientRect();
    const fitted = fitTransform(
      { width: rect.width, height: rect.height },
      world
    );
    fitScaleRef.current = fitted.k;
    sizeRef.current = { width: rect.width, height: rect.height };
    const cached = consumeCanvasCache(graphId);
    if (cached && cached.userAdjusted) {
      userAdjustedRef.current = true;
      applyTransform({ x: cached.x, y: cached.y, k: cached.k });
    } else {
      userAdjustedRef.current = false;
      applyTransform(fitted);
    }

    if (typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = entry.contentRect.width;
      const height = entry.contentRect.height;
      const previous = sizeRef.current;
      if (
        Math.abs(width - previous.width) < 2 &&
        Math.abs(height - previous.height) < 2
      ) {
        return;
      }
      sizeRef.current = { width, height };
      const nextFit = fitTransform({ width, height }, world);
      fitScaleRef.current = nextFit.k;
      if (userAdjustedRef.current || peekCanvasCache(graphId)?.userAdjusted) {
        return;
      }
      applyTransform(nextFit);
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [applyTransform, graph.viewBox, graphId, world]);

  React.useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const onWheel = (event) => {
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      const current = transformRef.current;
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      const minimum = fitScaleRef.current * MIN_SCALE_RATIO;
      const nextScale = Math.min(
        MAX_SCALE,
        Math.max(minimum, current.k * factor)
      );
      if (nextScale === current.k) return;
      userAdjustedRef.current = true;
      applyTransform({
        x: pointerX - ((pointerX - current.x) * nextScale) / current.k,
        y: pointerY - ((pointerY - current.y) * nextScale) / current.k,
        k: nextScale,
      });
    };
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [applyTransform]);

  const endDrag = React.useCallback((event) => {
    if (dragRef.current && event?.pointerId != null) {
      viewportRef.current?.releasePointerCapture?.(event.pointerId);
    }
    dragRef.current = null;
    setPanning(false);
  }, []);

  const onPointerDown = (event) => {
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    viewportRef.current?.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
    };
    setPanning(true);
  };

  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const current = transformRef.current;
    userAdjustedRef.current = true;
    applyTransform({
      x: current.x + (event.clientX - drag.lastX),
      y: current.y + (event.clientY - drag.lastY),
      k: current.k,
    });
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
  };

  return (
    <div
      ref={viewportRef}
      data-graph-canvas="true"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={fitToView}
      onContextMenu={(event) => event.preventDefault()}
      style={{
        height: "min(70vh, 820px)",
        width: "100%",
        overflow: "hidden",
        touchAction: "none",
        cursor: panning ? "grabbing" : "grab",
        userSelect: "none",
      }}
    >
      <svg
        width="100%"
        height="100%"
        style={{ display: "block" }}
      >
        <g
          ref={worldGroupRef}
          transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}
        >
          {edges.map(([from, to]) => {
            const fromPosition = positions[from];
            const toPosition = positions[to];
            if (!fromPosition || !toPosition) return null;
            const lit = edgeLit(nodes, from, to);
            return (
              <path
                key={`${from}-${to}`}
                d={edgePath(fromPosition, toPosition)}
                fill="none"
                stroke={
                  lit ? "rgba(254,44,85,0.85)" : "rgba(196,181,253,0.22)"
                }
                strokeWidth={lit ? 2.4 : 1.2}
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}
          {Object.entries(positions).map(([id, position]) => (
            <NodeGlyph
              key={id}
              id={id}
              position={position}
              node={nodes[id] || { id, label: id, status: "pending" }}
              selected={selectedNode === id}
              turn={turn}
              onInspect={onInspect}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

export default function PipelineCircuit() {
  const root = typeof props !== "undefined" ? props : {};
  const {
    title = "Agent pipeline",
    status = "running",
    current = "",
    activeGraph = "understand",
    viewGraph = "",
    selectedNode = "",
    turn = 0,
    progressPercent = 0,
    error = "",
    startedAt = 0,
    nodes = {},
    stages = {},
    graphs: rawGraphs = {},
    graphOrder: rawGraphOrder = [],
  } = root ?? {};

  const graphs =
    rawGraphs && typeof rawGraphs === "object" && !Array.isArray(rawGraphs)
      ? rawGraphs
      : {};
  const requestedOrder = Array.isArray(rawGraphOrder) ? rawGraphOrder : [];
  const graphOrder = [
    ...requestedOrder.filter(
      (stageId, index) =>
        graphs[stageId] && requestedOrder.indexOf(stageId) === index
    ),
    ...Object.keys(graphs).filter((stageId) => !requestedOrder.includes(stageId)),
  ];
  const fallbackGraph = graphOrder[0] || "";
  const liveGraph = graphs[activeGraph] ? activeGraph : fallbackGraph;
  const pinnedGraph = graphs[viewGraph] ? viewGraph : "";
  const shownGraph = pinnedGraph || liveGraph;
  const graph = graphs[shownGraph] || null;
  const positions =
    graph?.positions &&
    typeof graph.positions === "object" &&
    !Array.isArray(graph.positions)
      ? graph.positions
      : {};
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const [pickedNode, setPickedNode] = React.useState(selectedNode || "");
  React.useEffect(() => {
    if (selectedNode) setPickedNode(selectedNode);
  }, [selectedNode]);

  const [nowMs, setNowMs] = React.useState(Date.now());
  React.useEffect(() => {
    if (status !== "running") {
      setNowMs(Date.now());
      return undefined;
    }
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  const elapsedSeconds = startedAt
    ? Math.max(0, (nowMs - Math.round(startedAt * 1000)) / 1000)
    : 0;
  const currentLabel = nodes[current]?.label || current || "…";
  const statusLabel =
    status === "completed"
      ? "Turn complete"
      : status === "error"
        ? "Turn failed"
        : current
          ? `Running · ${currentLabel}`
          : "Running";
  const doneCount = Object.values(nodes).filter((node) =>
    ["completed", "skipped", "error"].includes(node.status)
  ).length;
  const total = Object.keys(nodes).length || 1;

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 1480,
        borderRadius: 22,
        padding: 18,
        color: "#f7f3ff",
        background:
          "radial-gradient(ellipse 80% 60% at 0% 0%, rgba(254,44,85,0.24), transparent 52%), radial-gradient(ellipse 70% 50% at 100% 0%, rgba(37,244,238,0.14), transparent 48%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)",
        border: "1px solid rgba(196,181,253,0.22)",
        boxShadow: "0 18px 44px rgba(254,44,85,0.12), 0 0 0 1px rgba(37,244,238,0.06)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          alignItems: "flex-start",
          marginBottom: 14,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 11,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.45)",
              marginBottom: 7,
            }}
          >
            Production path · turn {turn || "—"}
          </div>
          <div style={{ fontSize: 22, fontWeight: 750, letterSpacing: "-0.03em" }}>
            {title}
          </div>
          <div
            style={{
              marginTop: 6,
              fontSize: 13,
              color: "rgba(255,255,255,0.68)",
            }}
          >
            {statusLabel}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: statusTone(status),
            }}
          >
            {doneCount}/{total} nodes
          </div>
          <div
            style={{
              marginTop: 5,
              fontSize: 12,
              color: "rgba(255,255,255,0.45)",
            }}
          >
            {formatElapsed(elapsedSeconds)}
          </div>
        </div>
      </div>

      <div
        style={{
          height: 9,
          overflow: "hidden",
          borderRadius: 999,
          background: "rgba(255,255,255,0.07)",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            width: `${Math.max(status === "running" ? 2 : 0, progressPercent)}%`,
            height: "100%",
            transition: "width 300ms ease",
            background:
              status === "error"
                ? "linear-gradient(90deg,#ff6b8a,#ff9ab0)"
                : "linear-gradient(90deg,#fe2c55,#c4b5fd,#25f4ee)",
          }}
        />
      </div>

      <div
        style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 15 }}
      >
        {graphOrder.map((stageId) => {
          const stage = stages[stageId] || {};
          const stageStatus = stage.status || "pending";
          const selected = shownGraph === stageId;
          const canOpen = stageStatus !== "pending" || stageId === liveGraph;
          return (
            <button
              key={stageId}
              type="button"
              disabled={!canOpen}
              onClick={() =>
                canOpen &&
                sendAction("view_graph", {
                  graph: stageId === liveGraph ? "" : stageId,
                  turn: turn || 0,
                })
              }
              style={{
                flex: "1 1 140px",
                minWidth: 130,
                padding: "10px 12px",
                borderRadius: 12,
                textAlign: "left",
                cursor: canOpen ? "pointer" : "default",
                opacity: canOpen ? 1 : 0.48,
                background: nodeFill(stageStatus),
                border: selected
                  ? `1px solid ${statusTone(stageStatus)}`
                  : `1px solid ${nodeStroke(stageStatus)}`,
                color: "#f5f7fb",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 7,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 800,
                    textTransform: "uppercase",
                  }}
                >
                  {stageLabel(graphs[stageId], stageId)}
                </span>
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 999,
                    background: statusTone(stageStatus),
                    flex: "0 0 auto",
                    marginTop: 3,
                  }}
                />
              </div>
              {stage.summary ? (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 9.5,
                    lineHeight: 1.25,
                    whiteSpace: "pre-line",
                    color: "rgba(255,255,255,0.46)",
                  }}
                >
                  {stage.summary}
                </div>
              ) : null}
            </button>
          );
        })}
      </div>

      {error ? (
        <div
          style={{
            marginBottom: 13,
            padding: "10px 12px",
            borderRadius: 12,
            background: "linear-gradient(135deg, rgba(254,44,85,0.16), rgba(255,107,138,0.12))",
            border: "1px solid rgba(254,44,85,0.32)",
            color: "#ffd8e0",
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 10,
          marginBottom: 8,
          color: "rgba(255,255,255,0.46)",
          fontSize: 10.5,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        <span>{graph?.title || "Workflow graph unavailable"}</span>
        <span>
          {pinnedGraph && pinnedGraph !== liveGraph
            ? "preview · live stage elsewhere"
            : "live stage"}
        </span>
      </div>

      <div
        style={{
          borderRadius: 16,
          overflow: "hidden",
          background:
            "radial-gradient(ellipse 80% 70% at 50% 0%, rgba(254,44,85,0.08), transparent 55%), rgba(7,4,14,0.35)",
          border: "1px solid rgba(196,181,253,0.14)",
        }}
      >
        {graph ? (
          <GraphCanvas
            key={shownGraph}
            graph={graph}
            graphId={shownGraph}
            positions={positions}
            edges={edges}
            nodes={nodes}
            selectedNode={pickedNode || selectedNode}
            turn={turn}
            onInspect={setPickedNode}
          />
        ) : (
          <div
            style={{
              padding: "28px 18px",
              textAlign: "center",
              color: "rgba(255,255,255,0.42)",
              fontSize: 12,
            }}
          >
            No workflow graph was provided for this turn.
          </div>
        )}
      </div>

      <div
        style={{
          marginTop: 18,
          fontSize: 11.5,
          lineHeight: 1.45,
          color: "rgba(255,255,255,0.43)",
        }}
      >
        Green = executed, pink = running, dim = skipped/pending. Scroll to zoom,
        drag empty canvas to pan, double-click to fit. Click any node —
        including a skipped branch — to inspect its design and this turn's real
        input/output.
      </div>
    </div>
  );
}
