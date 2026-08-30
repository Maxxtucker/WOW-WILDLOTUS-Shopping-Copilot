import React from "react";

const NODE_W = 190;
const NODE_H = 48;

const GRAPHS = {
  understand: {
    title: "Understand · observe, ground, stage delta",
    viewBox: "0 0 1000 1050",
    pos: {
      casefold: { x: 500, y: 45 },
      color_map: { x: 270, y: 135 },
      material_map: { x: 730, y: 135 },
      color_verify: { x: 270, y: 225 },
      material_verify: { x: 730, y: 225 },
      merge_rewrite: { x: 500, y: 315 },
      category_l1: { x: 500, y: 405 },
      category_l2: { x: 500, y: 495 },
      category_l3: { x: 500, y: 585 },
      category_cap: { x: 500, y: 675 },
      attribute_llm: { x: 500, y: 765 },
      repair_1: { x: 250, y: 855 },
      repair_2: { x: 500, y: 855 },
      repair_3: { x: 750, y: 855 },
      disclosure: { x: 500, y: 945 },
      turn_delta: { x: 500, y: 1030 },
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
      ["attribute_llm", "disclosure"],
      ["repair_1", "disclosure"],
      ["repair_2", "disclosure"],
      ["repair_3", "disclosure"],
      ["disclosure", "turn_delta"],
    ],
  },
  router: {
    title: "Intent Router · override, commit, exact pools, route",
    viewBox: "0 0 1000 850",
    pos: {
      override_l1: { x: 500, y: 45 },
      override_l2: { x: 500, y: 135 },
      replace_delta: { x: 190, y: 240 },
      drop_slots: { x: 410, y: 240 },
      probe_override: { x: 300, y: 340 },
      intention_override: { x: 300, y: 440 },
      probe_before: { x: 760, y: 240 },
      apply_delta: { x: 760, y: 340 },
      probe_after: { x: 760, y: 440 },
      route_llm: { x: 760, y: 540 },
      buying: { x: 620, y: 645 },
      browsing: { x: 880, y: 645 },
      failsafe: { x: 500, y: 770 },
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
    title: "Retrieve + Rank · exact/hybrid recall, safety fusion, rerank",
    viewBox: "0 0 1000 1160",
    pos: {
      select_pool: { x: 500, y: 45 },
      slot_groups: { x: 180, y: 145 },
      rewrite_query: { x: 500, y: 145 },
      routing: { x: 820, y: 145 },
      lexical_in_pool: { x: 250, y: 260 },
      score_exact: { x: 250, y: 365 },
      hybrid_search: { x: 750, y: 365 },
      cap_hits: { x: 500, y: 475 },
      raw_evidence: { x: 500, y: 575 },
      base_only: { x: 180, y: 700 },
      relaxed_route: { x: 500, y: 700 },
      raw_text_route: { x: 820, y: 700 },
      weighted_rrf: { x: 660, y: 825 },
      qwen_rerank: { x: 310, y: 950 },
      belief_hits: { x: 690, y: 950 },
      normalize: { x: 500, y: 1080 },
    },
    edges: [
      ["select_pool", "slot_groups"],
      ["slot_groups", "rewrite_query"],
      ["rewrite_query", "routing"],
      ["routing", "lexical_in_pool"],
      ["lexical_in_pool", "score_exact"],
      ["routing", "hybrid_search"],
      ["score_exact", "hybrid_search"],
      ["score_exact", "cap_hits"],
      ["hybrid_search", "cap_hits"],
      ["cap_hits", "raw_evidence"],
      ["raw_evidence", "base_only"],
      ["raw_evidence", "relaxed_route"],
      ["raw_evidence", "raw_text_route"],
      ["relaxed_route", "weighted_rrf"],
      ["raw_text_route", "weighted_rrf"],
      ["base_only", "qwen_rerank"],
      ["base_only", "belief_hits"],
      ["weighted_rrf", "qwen_rerank"],
      ["weighted_rrf", "belief_hits"],
      ["qwen_rerank", "normalize"],
      ["belief_hits", "normalize"],
    ],
  },
  decide: {
    title: "Decide · question value, dynamic slate, writeback",
    viewBox: "0 0 1000 1080",
    pos: {
      answer_signature: { x: 500, y: 45 },
      eligible_questions: { x: 500, y: 135 },
      viability_filter: { x: 500, y: 225 },
      planning_head: { x: 500, y: 315 },
      action_space: { x: 500, y: 405 },
      planner: { x: 500, y: 500 },
      fallback_question: { x: 500, y: 595 },
      sequential_gate: { x: 500, y: 690 },
      gate_rank1: { x: 280, y: 795 },
      keep_planned: { x: 720, y: 795 },
      persist_turn: { x: 500, y: 905 },
      build_response: { x: 500, y: 1010 },
    },
    edges: [
      ["answer_signature", "eligible_questions"],
      ["eligible_questions", "viability_filter"],
      ["viability_filter", "planning_head"],
      ["planning_head", "action_space"],
      ["action_space", "planner"],
      ["planner", "fallback_question"],
      ["fallback_question", "sequential_gate"],
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
  ["retrieve", "Retrieve + rank", "retrieve"],
  ["decide", "Decide", "decide"],
];

function formatElapsed(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function statusTone(status) {
  if (status === "completed") return "#20c997";
  if (status === "running") return "#ff2b7a";
  if (status === "error") return "#ff6b6b";
  if (status === "skipped") return "rgba(255,255,255,0.28)";
  return "rgba(255,255,255,0.5)";
}

function nodeFill(status) {
  if (status === "completed") return "rgba(32,201,151,0.13)";
  if (status === "running") return "rgba(255,43,122,0.16)";
  if (status === "error") return "rgba(255,107,107,0.16)";
  if (status === "skipped") return "rgba(255,255,255,0.025)";
  return "rgba(255,255,255,0.045)";
}

function nodeStroke(status) {
  if (status === "completed") return "rgba(32,201,151,0.58)";
  if (status === "running") return "#ff2b7a";
  if (status === "error") return "#ff6b6b";
  if (status === "skipped") return "rgba(255,255,255,0.08)";
  return "rgba(255,255,255,0.13)";
}

function liveStatus(status) {
  return status === "completed" || status === "running";
}

function edgeLit(nodes, from, to) {
  return liveStatus(nodes[from]?.status) && liveStatus(nodes[to]?.status);
}

function box(pos) {
  return {
    left: pos.x - NODE_W / 2,
    right: pos.x + NODE_W / 2,
    top: pos.y - NODE_H / 2,
    bottom: pos.y + NODE_H / 2,
    cx: pos.x,
    cy: pos.y,
  };
}

function edgePath(fromPos, toPos) {
  const a = box(fromPos);
  const b = box(toPos);
  const sameRow = Math.abs(a.cy - b.cy) < 5;
  const sameCol = Math.abs(a.cx - b.cx) < 5;
  if (sameRow) {
    const rightward = a.cx < b.cx;
    return `M ${rightward ? a.right : a.left} ${a.cy} L ${rightward ? b.left : b.right} ${b.cy}`;
  }
  if (sameCol) {
    const downward = a.cy < b.cy;
    return `M ${a.cx} ${downward ? a.bottom : a.top} L ${b.cx} ${downward ? b.top : b.bottom}`;
  }
  const downward = a.cy < b.cy;
  const start = { x: a.cx, y: downward ? a.bottom : a.top };
  const end = { x: b.cx, y: downward ? b.top : b.bottom };
  const midY = (start.y + end.y) / 2;
  return `M ${start.x} ${start.y} L ${start.x} ${midY} L ${end.x} ${midY} L ${end.x} ${end.y}`;
}

function sendAction(name, payload) {
  if (typeof callAction === "function") callAction({ name, payload });
}

function inspectNode(id, turn) {
  sendAction("inspect_node", { node: id, turn: turn || 0 });
}

function NodeGlyph({ id, pos, node, selected, turn }) {
  const running = node.status === "running";
  const tone = statusTone(node.status);
  return (
    <g
      onClick={() => inspectNode(id, turn)}
      style={{ cursor: "pointer" }}
    >
      <rect
        x={pos.x - NODE_W / 2}
        y={pos.y - NODE_H / 2}
        width={NODE_W}
        height={NODE_H}
        rx="13"
        fill={nodeFill(node.status)}
        stroke={selected ? "#ff2b7a" : nodeStroke(node.status)}
        strokeWidth={selected || running ? 2.2 : 1.2}
        style={running ? { filter: "drop-shadow(0 0 9px rgba(255,43,122,0.6))" } : {}}
      />
      <foreignObject
        x={pos.x - NODE_W / 2 + 9}
        y={pos.y - NODE_H / 2 + 4}
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
            color: node.status === "skipped" ? "rgba(255,255,255,0.38)" : "#f5f7fb",
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
                color: node.status === "skipped" ? "rgba(255,255,255,0.25)" : tone,
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
        maxWidth: 820,
        borderRadius: 22,
        padding: 18,
        color: "#f5f7fb",
        background:
          "radial-gradient(circle at top left, rgba(255,43,122,0.16), transparent 28%), linear-gradient(180deg, #151515 0%, #0f0f0f 100%)",
        border: "1px solid rgba(255,255,255,0.08)",
        boxShadow: "0 20px 40px rgba(0,0,0,0.28)",
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
          <div style={{ marginTop: 6, fontSize: 13, color: "rgba(255,255,255,0.68)" }}>
            {statusLabel}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: statusTone(status) }}>
            {doneCount}/{total} nodes
          </div>
          <div style={{ marginTop: 5, fontSize: 12, color: "rgba(255,255,255,0.45)" }}>
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
                ? "linear-gradient(90deg,#ff6b6b,#ff9b9b)"
                : "linear-gradient(90deg,#ff2b7a,#ff72ab,#ffd166)",
          }}
        />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 15 }}>
        {STAGE_RAIL.map(([id, label, graphId]) => {
          const stage = stages[id] || {};
          const stageStatus = stage.status || "pending";
          const selected = shownGraph === graphId;
          const canOpen =
            stageStatus !== "pending" || graphId === liveGraph;
          return (
            <button
              key={id}
              type="button"
              disabled={!canOpen}
              onClick={() =>
                canOpen &&
                sendAction("view_graph", {
                  graph: graphId === liveGraph ? "" : graphId,
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
              <div style={{ display: "flex", justifyContent: "space-between", gap: 7 }}>
                <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase" }}>
                  {label}
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
            background: "rgba(255,107,107,0.11)",
            border: "1px solid rgba(255,107,107,0.24)",
            color: "#ffd8d8",
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
        <span>{graph.title}</span>
        <span>{pinned && pinned !== liveGraph ? "preview · live stage elsewhere" : "live stage"}</span>
      </div>

      <div
        style={{
          borderRadius: 16,
          overflow: "hidden",
          background: "rgba(255,255,255,0.018)",
          border: "1px solid rgba(255,255,255,0.055)",
        }}
      >
        <svg viewBox={graph.viewBox} width="100%" style={{ display: "block" }}>
          {graph.edges.map(([from, to]) => {
            const fromPos = graph.pos[from];
            const toPos = graph.pos[to];
            if (!fromPos || !toPos) return null;
            const lit = edgeLit(nodes, from, to);
            return (
              <path
                key={`${from}-${to}`}
                d={edgePath(fromPos, toPos)}
                fill="none"
                stroke={lit ? "rgba(255,43,122,0.72)" : "rgba(255,255,255,0.12)"}
                strokeWidth={lit ? 2.4 : 1.2}
                strokeLinejoin="round"
              />
            );
          })}
          {Object.entries(graph.pos).map(([id, pos]) => (
            <NodeGlyph
              key={id}
              id={id}
              pos={pos}
              node={nodes[id] || { id, label: id, status: "pending" }}
              selected={selectedNode === id}
              turn={turn}
            />
          ))}
        </svg>
      </div>

      <div
        style={{
          marginTop: 10,
          fontSize: 11.5,
          lineHeight: 1.45,
          color: "rgba(255,255,255,0.43)",
        }}
      >
        Green = executed, pink = running, dim = skipped/pending. Click any node — including a skipped branch — to inspect its contract and this turn's real input/output.
      </div>
    </div>
  );
}
