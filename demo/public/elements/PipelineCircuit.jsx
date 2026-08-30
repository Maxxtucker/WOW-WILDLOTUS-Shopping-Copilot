import React from "react";

const NODE_W = 10;
const NODE_H = 36;

const GRAPHS = {
  understand: {
    title: "Understand graph",
    viewBox: "0 0 720 800",
    pos: {
      casefold: { x: 360, y: 32 },
      color_map: { x: 170, y: 112 },
      material_map: { x: 550, y: 112 },
      color_verify: { x: 170, y: 192 },
      material_verify: { x: 550, y: 192 },
      merge_rewrite: { x: 360, y: 272 },
      category_l1: { x: 130, y: 360 },
      category_l2: { x: 360, y: 360 },
      category_l3: { x: 590, y: 360 },
      category_cap: { x: 360, y: 440 },
      attribute_llm: { x: 360, y: 520 },
      repair_1: { x: 130, y: 600 },
      repair_2: { x: 360, y: 600 },
      repair_3: { x: 590, y: 600 },
      disclosure: { x: 360, y: 680 },
      turn_delta: { x: 360, y: 760 },
    },
    edges: [
      ["casefold", "color_map"],
      ["casefold", "material_map"],
      ["color_map", "color_verify"],
      ["material_map", "material_verify"],
      ["color_verify", "merge_rewrite"],
      ["material_verify", "merge_rewrite"],
      ["merge_rewrite", "category_l1"],
      ["category_l1", "category_l2"],
      ["category_l2", "category_l3"],
      ["category_l3", "category_cap"],
      ["category_cap", "attribute_llm"],
      ["attribute_llm", "repair_1"],
      ["repair_1", "repair_2"],
      ["repair_2", "repair_3"],
      ["repair_3", "disclosure"],
      ["disclosure", "turn_delta"],
    ],
  },
  router: {
    title: "Intent router graph",
    viewBox: "0 0 720 700",
    pos: {
      override_l1: { x: 360, y: 36 },
      override_l2: { x: 360, y: 120 },
      replace_delta: { x: 140, y: 210 },
      drop_slots: { x: 280, y: 210 },
      probe_override: { x: 160, y: 300 },
      intention_override: { x: 160, y: 390 },
      probe_before: { x: 560, y: 210 },
      apply_delta: { x: 560, y: 300 },
      probe_after: { x: 560, y: 390 },
      route_llm: { x: 560, y: 470 },
      buying: { x: 450, y: 550 },
      browsing: { x: 670, y: 550 },
      failsafe: { x: 360, y: 640 },
    },
    edges: [
      ["override_l1", "override_l2"],
      ["override_l1", "replace_delta"],
      ["override_l2", "drop_slots"],
      ["override_l2", "probe_before"],
      ["replace_delta", "probe_override"],
      ["drop_slots", "probe_override"],
      ["probe_override", "intention_override"],
      ["intention_override", "failsafe"],
      ["probe_before", "apply_delta"],
      ["apply_delta", "probe_after"],
      ["probe_after", "route_llm"],
      ["route_llm", "buying"],
      ["route_llm", "browsing"],
      ["buying", "failsafe"],
      ["browsing", "failsafe"],
    ],
  },
  retrieve: {
    title: "Retrieve graph",
    viewBox: "0 0 720 680",
    pos: {
      slot_groups: { x: 130, y: 36 },
      rewrite_query: { x: 360, y: 36 },
      routing: { x: 590, y: 36 },
      lexical_in_pool: { x: 180, y: 150 },
      score_exact: { x: 180, y: 240 },
      hybrid_search: { x: 540, y: 190 },
      cap_hits: { x: 360, y: 350 },
      qwen_rerank: { x: 180, y: 470 },
      belief_hits: { x: 540, y: 470 },
      normalize: { x: 360, y: 590 },
    },
    edges: [
      ["slot_groups", "rewrite_query"],
      ["rewrite_query", "routing"],
      ["routing", "lexical_in_pool"],
      ["lexical_in_pool", "score_exact"],
      ["score_exact", "cap_hits"],
      ["routing", "hybrid_search"],
      ["hybrid_search", "cap_hits"],
      ["cap_hits", "qwen_rerank"],
      ["cap_hits", "belief_hits"],
      ["qwen_rerank", "normalize"],
      ["belief_hits", "normalize"],
    ],
  },
  decide: {
    title: "Decide graph",
    viewBox: "0 0 720 680",
    pos: {
      answer_signature: { x: 360, y: 36 },
      eligible_questions: { x: 360, y: 126 },
      planner: { x: 360, y: 216 },
      sequential_gate: { x: 360, y: 306 },
      gate_rank1: { x: 180, y: 420 },
      keep_planned: { x: 540, y: 420 },
      persist_turn: { x: 360, y: 530 },
      build_response: { x: 360, y: 620 },
    },
    edges: [
      ["answer_signature", "eligible_questions"],
      ["eligible_questions", "planner"],
      ["planner", "sequential_gate"],
      ["sequential_gate", "gate_rank1"],
      ["sequential_gate", "keep_planned"],
      ["gate_rank1", "persist_turn"],
      ["keep_planned", "persist_turn"],
      ["persist_turn", "build_response"],
    ],
  },
};

const STAGE_RAIL = [
  ["understand", "Understand", "understand"],
  ["router", "Intent router", "router"],
  ["retrieve", "Retrieve", "retrieve"],
  ["decide", "Decide", "decide"],
];

function formatElapsed(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function statusTone(status) {
  if (status === "completed") return "#20c997";
  if (status === "error") return "#ff6b6b";
  if (status === "skipped") return "rgba(255,255,255,0.28)";
  return "#ff2b7a";
}

function nodeFill(status) {
  if (status === "completed") return "rgba(32, 201, 151, 0.16)";
  if (status === "running") return "rgba(255, 43, 122, 0.16)";
  if (status === "error") return "rgba(255, 107, 107, 0.16)";
  if (status === "skipped") return "rgba(255, 255, 255, 0.03)";
  return "rgba(255, 255, 255, 0.04)";
}

function nodeStroke(status) {
  if (status === "completed") return "rgba(32, 201, 151, 0.55)";
  if (status === "running") return "#ff2b7a";
  if (status === "error") return "#ff6b6b";
  return "rgba(255,255,255,0.12)";
}

function edgeLit(nodes, from, to) {
  const src = nodes[from]?.status;
  const dst = nodes[to]?.status;
  const live = (status) => status === "completed" || status === "running";
  return live(src) && live(dst);
}

function nodeBox(pos) {
  return {
    left: pos.x - NODE_W / 2,
    right: pos.x + NODE_W / 2,
    top: pos.y - NODE_H / 2,
    bottom: pos.y + NODE_H / 2,
    cx: pos.x,
    cy: pos.y,
  };
}

function roundedOrtho(start, end, radius = 12) {
  const midY = (start.y + end.y) / 2;
  const v1 = Math.abs(midY - start.y);
  const horiz = Math.abs(end.x - start.x);
  const v2 = Math.abs(end.y - midY);
  const r = Math.max(0, Math.min(radius, v1 / 2, horiz / 2, v2 / 2));
  if (r < 1) {
    return `M ${start.x} ${start.y} L ${start.x} ${midY} L ${end.x} ${midY} L ${end.x} ${end.y}`;
  }
  const vSign = midY >= start.y ? 1 : -1;
  const hSign = end.x >= start.x ? 1 : -1;
  const v2Sign = end.y >= midY ? 1 : -1;
  return [
    `M ${start.x} ${start.y}`,
    `L ${start.x} ${midY - vSign * r}`,
    `Q ${start.x} ${midY} ${start.x + hSign * r} ${midY}`,
    `L ${end.x - hSign * r} ${midY}`,
    `Q ${end.x} ${midY} ${end.x} ${midY + v2Sign * r}`,
    `L ${end.x} ${end.y}`,
  ].join(" ");
}

function edgePath(fromPos, toPos) {
  const a = nodeBox(fromPos);
  const b = nodeBox(toPos);
  const sameRow = Math.abs(a.cy - b.cy) < 4;
  const sameCol = Math.abs(a.cx - b.cx) < 4;
  if (sameRow) {
    const rightward = a.cx < b.cx;
    const x1 = rightward ? a.right : a.left;
    const x2 = rightward ? b.left : b.right;
    return `M ${x1} ${a.cy} L ${x2} ${b.cy}`;
  }
  if (sameCol) {
    const downward = a.cy < b.cy;
    const y1 = downward ? a.bottom : a.top;
    const y2 = downward ? b.top : b.bottom;
    return `M ${a.cx} ${y1} L ${b.cx} ${y2}`;
  }
  const start = { x: a.cx, y: a.cy < b.cy ? a.bottom : a.top };
  const end = { x: b.cx, y: a.cy < b.cy ? b.top : b.bottom };
  return roundedOrtho(start, end);
}

function sendAction(name, payload) {
  if (typeof callAction !== "function") {
    return;
  }
  callAction({ name, payload });
}

function inspectNode(id, turn) {
  sendAction("inspect_node", { node: id, turn: turn || 0 });
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
  } = root ?? {};

  const liveGraph = GRAPHS[activeGraph] ? activeGraph : "understand";
  const pinned = GRAPHS[viewGraph] ? viewGraph : "";
  const shownGraph = pinned || liveGraph;
  const graph = GRAPHS[shownGraph] || GRAPHS.understand;

  const [nowMs, setNowMs] = React.useState(Date.now());
  React.useEffect(() => {
    if (status !== "running") {
      setNowMs(Date.now());
      return undefined;
    }
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  const startMs = Math.round((startedAt || 0) * 1000);
  const elapsedSeconds =
    startMs > 0 ? Math.max(0, (nowMs - startMs) / 1000) : 0;
  const tone = statusTone(status);
  const currentLabel = nodes[current]?.label || current || "…";
  const statusLabel =
    status === "completed"
      ? "Turn complete"
      : status === "error"
        ? "Failed"
        : current
          ? `Running ${currentLabel}`
          : "Running";

  const doneCount = Object.values(nodes).filter((node) =>
    ["completed", "skipped", "error"].includes(node.status)
  ).length;
  const total = Object.keys(nodes).length || 24;

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 760,
        borderRadius: 22,
        padding: 18,
        color: "#f5f7fb",
        background:
          "radial-gradient(circle at top left, rgba(255,43,122,0.18), transparent 28%), linear-gradient(180deg, #151515 0%, #101010 100%)",
        border: "1px solid rgba(255,255,255,0.08)",
        boxShadow: "0 20px 40px rgba(0,0,0,0.28)",
      }}
    >
      <style>
        {`
          @keyframes pipelineShimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
          @keyframes pipelinePulse {
            0% { filter: drop-shadow(0 0 0 rgba(255,43,122,0)); }
            50% { filter: drop-shadow(0 0 8px rgba(255,43,122,0.55)); }
            100% { filter: drop-shadow(0 0 0 rgba(255,43,122,0)); }
          }
        `}
      </style>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.48)",
              marginBottom: 8,
            }}
          >
            Live circuit
          </div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 700,
              letterSpacing: "-0.03em",
              marginBottom: 6,
            }}
          >
            {title}
          </div>
          <div style={{ fontSize: 14, color: "rgba(255,255,255,0.72)" }}>
            {statusLabel}
          </div>
        </div>
        <div
          style={{
            minWidth: 88,
            padding: "8px 12px",
            borderRadius: 999,
            textAlign: "center",
            background: `${tone}1f`,
            border: `1px solid ${tone}3d`,
            color: tone,
            fontWeight: 700,
            fontSize: 13,
          }}
        >
          {doneCount}/{total}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.7)" }}>
          Four stages. Click a node to inspect it. Only the taken path lights up.
        </div>
        <div
          style={{
            fontSize: 13,
            color: "rgba(255,255,255,0.64)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {formatElapsed(elapsedSeconds)}
        </div>
      </div>

      <div
        style={{
          position: "relative",
          height: 12,
          borderRadius: 999,
          overflow: "hidden",
          background: "rgba(255,255,255,0.08)",
          marginBottom: 16,
        }}
      >
        <div
          style={{
            width: `${Math.max(4, progressPercent)}%`,
            height: "100%",
            borderRadius: 999,
            background:
              status === "error"
                ? "linear-gradient(90deg, #ff6b6b 0%, #ff8d8d 100%)"
                : "linear-gradient(90deg, #ff2b7a 0%, #ff6aa8 55%, #ffd166 100%)",
            transition: "width 400ms ease",
          }}
        />
        {status === "running" ? (
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(110deg, transparent 20%, rgba(255,255,255,0.22) 35%, transparent 50%)",
              backgroundSize: "200% 100%",
              animation: "pipelineShimmer 1.6s linear infinite",
            }}
          />
        ) : null}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 16,
        }}
      >
        {STAGE_RAIL.map(([id, label, graphId]) => {
          const stage = stages[id] || {};
          const stageStatus = stage.status || "pending";
          const color = statusTone(stageStatus);
          const selected = shownGraph === graphId;
          const canOpen =
            stageStatus === "completed" ||
            stageStatus === "running" ||
            stageStatus === "error" ||
            graphId === liveGraph;
          return (
            <button
              key={id}
              type="button"
              disabled={!canOpen}
              onClick={() => {
                if (!canOpen) return;
                sendAction("view_graph", {
                  graph: graphId === liveGraph ? "" : graphId,
                  turn: turn || 0,
                });
              }}
              style={{
                flex: "1 1 120px",
                minWidth: 120,
                padding: "12px 14px",
                borderRadius: 12,
                textAlign: "left",
                cursor: canOpen ? "pointer" : "default",
                background: nodeFill(stageStatus),
                border: selected
                  ? `1px solid ${color}`
                  : `1px solid ${nodeStroke(stageStatus)}`,
                boxShadow: selected ? `0 0 0 1px ${color}66` : "none",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                }}
              >
                {label}
              </div>
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 999,
                  flex: "0 0 auto",
                  background: color,
                  boxShadow: stageStatus === "running" ? `0 0 8px ${color}` : "none",
                }}
              />
            </button>
          );
        })}
      </div>

      {error ? (
        <div
          style={{
            marginBottom: 14,
            padding: "10px 12px",
            borderRadius: 14,
            background: "rgba(255,107,107,0.12)",
            border: "1px solid rgba(255,107,107,0.24)",
            color: "#ffd8d8",
            fontSize: 13,
            lineHeight: 1.5,
          }}
        >
          {error}
        </div>
      ) : null}

      <div
        style={{
          fontSize: 12,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.45)",
          marginBottom: 8,
        }}
      >
        {graph.title}
        {pinned && pinned !== liveGraph ? " · preview" : ""}
      </div>
      <svg
        viewBox={graph.viewBox}
        width="100%"
        style={{ display: "block", overflow: "visible" }}
      >
        {graph.edges.map(([from, to]) => {
          const a = graph.pos[from];
          const b = graph.pos[to];
          if (!a || !b) return null;
          const lit = edgeLit(nodes, from, to);
          return (
            <path
              key={`${from}-${to}`}
              d={edgePath(a, b)}
              fill="none"
              stroke={lit ? "rgba(255,43,122,0.55)" : "rgba(255,255,255,0.16)"}
              strokeWidth={lit ? 2 : 1.2}
              strokeLinejoin="round"
            />
          );
        })}
        {Object.entries(graph.pos).map(([id, pos]) => {
          const node = nodes[id] || { label: id, status: "pending" };
          const running = node.status === "running";
          const selected = selectedNode === id;
          return (
            <g
              key={id}
              onClick={() => inspectNode(id, turn)}
              style={{
                cursor: "pointer",
                animation: running
                  ? "pipelinePulse 1.2s ease-in-out infinite"
                  : undefined,
              }}
            >
              <rect
                x={pos.x - NODE_W / 2}
                y={pos.y - NODE_H / 2}
                width={NODE_W}
                height={NODE_H}
                rx={NODE_H / 2}
                fill={nodeFill(node.status)}
                stroke={selected ? "#ff2b7a" : nodeStroke(node.status)}
                strokeWidth={selected || running ? 2 : 1}
              />
              <text
                x={pos.x}
                y={pos.y}
                textAnchor="middle"
                dominantBaseline="central"
                fill={
                  node.status === "pending"
                    ? "rgba(255,255,255,0.55)"
                    : "#f5f7fb"
                }
                fontSize="11"
                fontWeight="600"
                style={{ pointerEvents: "none" }}
              >
                {node.label || id}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
