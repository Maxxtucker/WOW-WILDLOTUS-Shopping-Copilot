import React from "react";

const CARD = {
  padding: "12px 14px",
  borderRadius: 14,
  background: "linear-gradient(180deg, rgba(254,44,85,0.08), rgba(37,244,238,0.04))",
  border: "1px solid rgba(196,181,253,0.16)",
};

const LABEL = {
  fontSize: 10,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "rgba(255,255,255,0.38)",
  fontWeight: 700,
  marginBottom: 8,
};

function prettyKey(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function sendAction(name, payload) {
  if (typeof callAction === "function") callAction({ name, payload });
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "error") return "danger";
  if (status === "running") return "accent";
  return "muted";
}

function statusLabel(status) {
  if (status === "completed") return "Executed";
  if (status === "skipped") return "Skipped";
  if (status === "running") return "Running";
  if (status === "error") return "Error";
  return "Pending";
}

function Chip({ children, tone = "muted" }) {
  const palettes = {
    success: { bg: "rgba(37,244,238,0.16)", border: "rgba(37,244,238,0.38)", text: "#d9fbff" },
    danger: { bg: "rgba(255,107,138,0.14)", border: "rgba(255,107,138,0.32)", text: "#ffd8e0" },
    accent: { bg: "rgba(254,44,85,0.16)", border: "rgba(37,244,238,0.32)", text: "#ffe4ec" },
    muted: { bg: "rgba(196,181,253,0.08)", border: "rgba(196,181,253,0.18)", text: "rgba(247,243,255,0.78)" },
  };
  const palette = palettes[tone] || palettes.muted;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontSize: 11.5,
        padding: "3px 8px",
        borderRadius: 999,
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.text,
        lineHeight: 1.3,
      }}
    >
      {children}
    </span>
  );
}

function Field({ name, children }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <div style={{ fontSize: 10.5, color: "rgba(255,255,255,0.4)", letterSpacing: "0.04em" }}>
        {prettyKey(name)}
      </div>
      <div style={{ fontSize: 13, color: "rgba(255,255,255,0.86)", lineHeight: 1.5 }}>
        {children}
      </div>
    </div>
  );
}

function isHitRow(value) {
  return value && typeof value === "object" && ("phrase" in value || "replacement" in value);
}

function isGroupRow(value) {
  return value && typeof value === "object" && "attribute" in value && "values" in value;
}

function ValueView({ value }) {
  if (value == null || value === "") {
    return <span style={{ color: "rgba(255,255,255,0.33)" }}>None</span>;
  }
  if (typeof value === "boolean") {
    return <Chip tone={value ? "success" : "muted"}>{value ? "Yes" : "No"}</Chip>;
  }
  if (typeof value === "number") {
    return <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>;
  }
  if (typeof value === "string") {
    if (value.length > 92) {
      return (
        <div
          style={{
            padding: "8px 10px",
            borderRadius: 10,
            background: "rgba(0,0,0,0.22)",
            border: "1px solid rgba(255,255,255,0.06)",
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
          }}
        >
          {value}
        </div>
      );
    }
    return <Chip>{value}</Chip>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span style={{ color: "rgba(255,255,255,0.33)" }}>Empty list</span>;
    }
    if (value.every(isHitRow)) {
      return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {value.map((hit, index) => {
            const kept = hit.kept !== false;
            const phrase = hit.phrase || hit.replacement || "hit";
            const replacement = hit.replacement && hit.replacement !== hit.phrase
              ? ` → ${hit.replacement}`
              : "";
            return (
              <Chip key={`${phrase}-${index}`} tone={kept ? "success" : "danger"}>
                {phrase}{replacement}{kept ? "" : " · dropped"}
              </Chip>
            );
          })}
        </div>
      );
    }
    if (value.every(isGroupRow)) {
      return (
        <div style={{ display: "grid", gap: 8 }}>
          {value.map((row, index) => (
            <div key={`${row.attribute}-${index}`} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <Chip tone="accent">{row.attribute}</Chip>
              {(row.values || []).map((item, valueIndex) => (
                <Chip key={`${item}-${valueIndex}`}>{String(item)}</Chip>
              ))}
            </div>
          ))}
        </div>
      );
    }
    if (value.every((item) => item == null || typeof item !== "object")) {
      return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {value.map((item, index) => <Chip key={`${item}-${index}`}>{String(item)}</Chip>)}
        </div>
      );
    }
    return (
      <div style={{ display: "grid", gap: 8 }}>
        {value.map((item, index) => (
          <div
            key={index}
            style={{
              padding: "8px 10px",
              borderRadius: 10,
              background: "rgba(0,0,0,0.17)",
              border: "1px solid rgba(255,255,255,0.05)",
            }}
          >
            <ValueView value={item} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    if ("count" in value && "sample" in value) {
      const sample = Array.isArray(value.sample) ? value.sample : [];
      return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Chip tone="accent">{value.count} total</Chip>
          {sample.map((item, index) => <Chip key={`${item}-${index}`}>{String(item)}</Chip>)}
        </div>
      );
    }
    const entries = Object.entries(value).filter(([, item]) => item !== undefined);
    if (entries.length === 0) {
      return <span style={{ color: "rgba(255,255,255,0.33)" }}>Empty object</span>;
    }
    return (
      <div style={{ display: "grid", gap: 11 }}>
        {entries.map(([key, item]) => (
          <Field key={key} name={key}>
            <ValueView value={item} />
          </Field>
        ))}
      </div>
    );
  }
  return <span>{String(value)}</span>;
}

function Section({ title, children, accent = false }) {
  return (
    <div
      style={{
        ...CARD,
        border: accent ? "1px solid rgba(37,244,238,0.22)" : CARD.border,
        background: accent
          ? "linear-gradient(180deg, rgba(254,44,85,0.1), rgba(37,244,238,0.05))"
          : CARD.background,
      }}
    >
      <div style={LABEL}>{title}</div>
      <div style={{ fontSize: 13.2, color: "rgba(255,255,255,0.84)", lineHeight: 1.58 }}>
        {children}
      </div>
    </div>
  );
}

function isEmptyObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0;
}

function runtimeFields(detail) {
  const ignored = new Set([
    "input", "output", "why", "text", "original", "message", "rewritten",
    "labels", "hits", "result", "source",
  ]);
  return Object.fromEntries(
    Object.entries(detail || {}).filter(([key, value]) => !ignored.has(key) && value !== undefined)
  );
}

function liveInput(detail) {
  if (Object.prototype.hasOwnProperty.call(detail, "input")) return detail.input;
  if (detail.original != null) return { original: detail.original };
  if (detail.text != null) return { text: detail.text };
  if (detail.message != null) return { message: detail.message };
  return null;
}

function liveOutput(detail) {
  if (Object.prototype.hasOwnProperty.call(detail, "output")) return detail.output;
  const fallback = {};
  for (const key of ["rewritten", "labels", "hits", "result", "source"]) {
    if (detail[key] !== undefined) fallback[key] = detail[key];
  }
  return Object.keys(fallback).length ? fallback : null;
}

function ThisTurn({ node, detail }) {
  const status = node?.status || "pending";
  const input = liveInput(detail);
  const output = liveOutput(detail);
  const extra = runtimeFields(detail);
  const hasInput = input != null && !isEmptyObject(input);
  const hasOutput = output != null && !isEmptyObject(output);
  const hasExtra = Object.keys(extra).length > 0;
  const why = detail?.why;

  if (status === "pending") {
    return (
      <div style={{ display: "grid", gap: 9 }}>
        <Chip tone="muted">Pending</Chip>
        <span style={{ color: "rgba(255,255,255,0.45)" }}>
          This turn has not reached this node yet.
        </span>
      </div>
    );
  }
  if (status === "skipped" && !hasInput && !hasOutput && !hasExtra) {
    return (
      <div style={{ display: "grid", gap: 8 }}>
        <Chip tone="muted">Not executed this turn</Chip>
        <span>{why || "The production path did not require this branch."}</span>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 13 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <Chip tone={statusTone(status)}>{statusLabel(status)}</Chip>
        {node?.summary ? <Chip>{node.summary}</Chip> : null}
      </div>
      {why ? (
        <Field name={status === "skipped" ? "Skip reason" : "Runtime note"}>
          <ValueView value={why} />
        </Field>
      ) : null}
      {hasInput ? (
        <Field name="Actual input">
          <ValueView value={input} />
        </Field>
      ) : null}
      {hasOutput ? (
        <Field name="Actual output">
          <ValueView value={output} />
        </Field>
      ) : null}
      {hasExtra ? (
        <Field name="Runtime detail">
          <ValueView value={extra} />
        </Field>
      ) : null}
      {!why && !hasInput && !hasOutput && !hasExtra ? (
        <span style={{ color: "rgba(255,255,255,0.45)" }}>
          {status === "running"
            ? "The node is running; structured output has not arrived yet."
            : "The node ran, but this progress event did not publish structured I/O."}
        </span>
      ) : null}
    </div>
  );
}

export default function NodeInspector() {
  const root = typeof props !== "undefined" ? props : {};
  const turns = Array.isArray(root.turns) ? root.turns : [];
  const catalog = root.catalog && typeof root.catalog === "object" ? root.catalog : {};
  const blurbs = root.stage_blurbs && typeof root.stage_blurbs === "object" ? root.stage_blurbs : {};
  const selectedNode = root.selected_node || "";
  const activeGraph = root.active_graph || "understand";
  const expandedTurn = root.expanded_turn;
  const expanded = root.expanded !== false;

  const [viewTurn, setViewTurn] = React.useState(expandedTurn ?? null);
  React.useEffect(() => {
    if (expandedTurn != null) setViewTurn(expandedTurn);
  }, [expandedTurn]);

  const row = turns.find((item) => item.turn === viewTurn) || turns[turns.length - 1] || null;
  const nodes = row && row.nodes && typeof row.nodes === "object" ? row.nodes : {};
  const node = selectedNode ? nodes[selectedNode] || {} : null;
  const meta = selectedNode ? catalog[selectedNode] || {} : {};
  const stage = meta.stage || node?.stage || activeGraph;
  const title = meta.label || node?.label || selectedNode || "Node inspector";

  if (!expanded) {
    return (
      <div
        data-inspector-collapsed="true"
        style={{
          width: "100%",
          height: "100%",
          minHeight: "100%",
          boxSizing: "border-box",
          padding: 8,
          background:
            "radial-gradient(ellipse 80% 60% at 0% 0%, rgba(254,44,85,0.22), transparent 55%), linear-gradient(180deg,#1c122c,#0c0816)",
          borderRadius: 16,
          border: "1px solid rgba(196,181,253,0.2)",
          display: "flex",
          justifyContent: "center",
          alignItems: "flex-start",
        }}
      >
        <button
          type="button"
          onClick={() => sendAction("toggle_inspector", { expanded: true })}
          style={{
            writingMode: "vertical-rl",
            transform: "rotate(180deg)",
            background: "linear-gradient(180deg, rgba(254,44,85,0.22), rgba(37,244,238,0.12))",
            border: "1px solid rgba(37,244,238,0.35)",
            color: "#ffe4ec",
            borderRadius: 999,
            padding: "12px 8px",
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            cursor: "pointer",
          }}
        >
          Inspect
        </button>
      </div>
    );
  }

  const detail = node && node.detail && typeof node.detail === "object" ? node.detail : {};
  const task =
    meta.task ||
    meta.purpose ||
    node?.task ||
    "No task note is registered for this node.";
  const rationale =
    meta.rationale ||
    meta.why ||
    node?.rationale ||
    "No rationale note is registered for this node.";
  const implementation =
    meta.implementation ||
    meta.how_it_works ||
    node?.implementation ||
    "No implementation note is registered for this node.";

  return (
    <div
      data-inspector-collapsed="false"
      style={{
        width: "100%",
        height: "100%",
        minHeight: "100%",
        boxSizing: "border-box",
        overflow: "auto",
        padding: "10px 11px",
        color: "#f7f3ff",
        background:
          "radial-gradient(ellipse 80% 50% at 0% 0%, rgba(254,44,85,0.18), transparent 50%), radial-gradient(ellipse 70% 40% at 100% 0%, rgba(37,244,238,0.12), transparent 46%), linear-gradient(180deg,#1c122c,#0c0816)",
        borderRadius: 18,
        border: "1px solid rgba(196,181,253,0.2)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 13 }}>
        <div style={{ fontSize: 10.5, letterSpacing: "0.16em", textTransform: "uppercase", color: "rgba(255,255,255,0.42)", fontWeight: 700 }}>
          Node inspector · production trace
        </div>
        <button
          type="button"
          onClick={() => sendAction("toggle_inspector", { expanded: false })}
          style={{
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.12)",
            color: "rgba(255,255,255,0.62)",
            borderRadius: 999,
            padding: "4px 10px",
            fontSize: 10.5,
            cursor: "pointer",
          }}
        >
          Collapse
        </button>
      </div>

      {turns.length > 0 ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 13 }}>
          <span style={{ fontSize: 10.5, color: "rgba(255,255,255,0.4)" }}>Inspect turn</span>
          <select
            value={row ? row.turn : ""}
            onChange={(event) => setViewTurn(Number(event.target.value))}
            style={{
              flex: 1,
              background: "linear-gradient(180deg,#241634,#12081c)",
              color: "#f7f3ff",
              border: "1px solid rgba(196,181,253,0.28)",
              borderRadius: 9,
              padding: "6px 9px",
              fontSize: 12.5,
              colorScheme: "dark",
            }}
          >
            {turns.map((item) => (
              <option key={item.turn} value={item.turn}>Turn {item.turn}</option>
            ))}
          </select>
        </div>
      ) : null}

      {!selectedNode ? (
        <div style={{ display: "grid", gap: 11 }}>
          <div
            style={{
              ...CARD,
              border: "1px solid rgba(37,244,238,0.22)",
              background: "linear-gradient(180deg, rgba(254,44,85,0.1), rgba(37,244,238,0.05))",
            }}
          >
            <div style={LABEL}>{String(stage).replace(/_/g, " ")}</div>
            <div
              style={{
                fontSize: 13.2,
                color: "rgba(255,255,255,0.84)",
                lineHeight: 1.58,
              }}
            >
              {blurbs[stage] ||
                "Click a circuit node to inspect its design and current-turn I/O."}
            </div>
            {row?.original ? (
              <div
                style={{
                  marginTop: 12,
                  paddingTop: 11,
                  borderTop: "1px solid rgba(255,255,255,0.07)",
                }}
              >
                <Field name="Current turn utterance">
                  <ValueView value={row.original} />
                </Field>
              </div>
            ) : null}
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: "rgba(255,255,255,0.4)",
              lineHeight: 1.5,
            }}
          >
            The graph keeps unused branches visible. Clicking a skipped node
            shows the real reason it did not execute this turn.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 11 }}>
          <div>
            <div style={{ fontSize: 19, fontWeight: 750, letterSpacing: "-0.025em", marginBottom: 7 }}>
              {title}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <Chip tone="accent">{String(stage).replace(/_/g, " ")}</Chip>
              {row ? <Chip>Turn {row.turn}</Chip> : null}
              <Chip tone={statusTone(node?.status)}>{statusLabel(node?.status)}</Chip>
            </div>
          </div>

          <Section title="Node Task">{task}</Section>
          <Section title="Design Rationale">{rationale}</Section>
          <Section title="Implementation">{implementation}</Section>
          <Section title="This turn · real trace" accent>
            <ThisTurn node={node} detail={detail} />
          </Section>
        </div>
      )}
    </div>
  );
}
