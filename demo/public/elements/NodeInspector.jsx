import React from "react";

const CARD = {
  padding: "12px 14px",
  borderRadius: 14,
  background: "rgba(255,255,255,0.03)",
  border: "1px solid rgba(255,255,255,0.07)",
};

const LABEL = {
  fontSize: 10,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "rgba(255,255,255,0.38)",
  fontWeight: 600,
  marginBottom: 8,
};

function prettyKey(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function sendAction(name, payload) {
  if (typeof callAction !== "function") {
    return;
  }
  callAction({ name, payload });
}

function Chip({ children, tone = "muted" }) {
  const palettes = {
    success: { bg: "rgba(32,201,151,0.14)", border: "rgba(32,201,151,0.32)", text: "#d6fff3" },
    danger: { bg: "rgba(255,107,107,0.12)", border: "rgba(255,107,107,0.28)", text: "#ffd8d8" },
    accent: { bg: "rgba(255,43,122,0.14)", border: "rgba(255,43,122,0.28)", text: "#ffe1ec" },
    muted: { bg: "rgba(255,255,255,0.05)", border: "rgba(255,255,255,0.1)", text: "rgba(255,255,255,0.7)" },
  };
  const toneStyle = palettes[tone] || palettes.muted;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontSize: 12,
        padding: "3px 9px",
        borderRadius: 999,
        background: toneStyle.bg,
        border: `1px solid ${toneStyle.border}`,
        color: toneStyle.text,
        lineHeight: 1.3,
      }}
    >
      {children}
    </span>
  );
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "error") return "danger";
  if (status === "running") return "accent";
  return "muted";
}

function statusLabel(status) {
  if (status === "completed") return "Ran";
  if (status === "skipped") return "Skipped";
  if (status === "running") return "Running";
  if (status === "error") return "Error";
  return "Pending";
}

function isHitRow(value) {
  return value && typeof value === "object" && ("phrase" in value || "replacement" in value);
}

function isGroupRow(value) {
  return value && typeof value === "object" && "attribute" in value && "values" in value;
}

function HitPills({ hits }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {hits.map((hit, index) => {
        const kept = hit.kept !== false;
        const phrase = hit.phrase || hit.replacement || "hit";
        const next = hit.replacement && hit.replacement !== hit.phrase ? ` → ${hit.replacement}` : "";
        return (
          <Chip key={`${phrase}-${index}`} tone={kept ? "success" : "danger"}>
            {phrase}
            {next}
            {kept ? "" : " · dropped"}
          </Chip>
        );
      })}
    </div>
  );
}

function Field({ name, children }) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div
        style={{
          fontSize: 11,
          color: "rgba(255,255,255,0.4)",
          letterSpacing: "0.04em",
        }}
      >
        {prettyKey(name)}
      </div>
      <div style={{ fontSize: 13, color: "rgba(255,255,255,0.86)", lineHeight: 1.5 }}>
        {children}
      </div>
    </div>
  );
}

function ValueView({ value }) {
  if (value == null || value === "") {
    return <span style={{ color: "rgba(255,255,255,0.35)" }}>None</span>;
  }
  if (typeof value === "boolean") {
    return <Chip tone={value ? "success" : "muted"}>{value ? "Yes" : "No"}</Chip>;
  }
  if (typeof value === "number") {
    return <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>;
  }
  if (typeof value === "string") {
    if (value.length > 80) {
      return (
        <div
          style={{
            padding: "8px 10px",
            borderRadius: 10,
            background: "rgba(0,0,0,0.22)",
            border: "1px solid rgba(255,255,255,0.06)",
            color: "rgba(255,255,255,0.82)",
            lineHeight: 1.5,
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
      return <span style={{ color: "rgba(255,255,255,0.35)" }}>None</span>;
    }
    if (value.every(isHitRow)) {
      return <HitPills hits={value} />;
    }
    if (value.every(isGroupRow)) {
      return (
        <div style={{ display: "grid", gap: 8 }}>
          {value.map((row, index) => (
            <div key={`${row.attribute}-${index}`} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <Chip tone="accent">{row.attribute}</Chip>
              {(row.values || []).map((item) => (
                <Chip key={String(item)}>{String(item)}</Chip>
              ))}
            </div>
          ))}
        </div>
      );
    }
    if (value.every((item) => item == null || typeof item !== "object")) {
      return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {value.map((item, index) => (
            <Chip key={`${item}-${index}`}>{String(item)}</Chip>
          ))}
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
              background: "rgba(0,0,0,0.18)",
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
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <Chip tone="accent">{value.count} total</Chip>
          {sample.map((item) => (
            <Chip key={String(item)}>{String(item)}</Chip>
          ))}
        </div>
      );
    }
    const entries = Object.entries(value).filter(([, item]) => item !== undefined);
    if (entries.length === 0) {
      return <span style={{ color: "rgba(255,255,255,0.35)" }}>None</span>;
    }
    return (
      <div style={{ display: "grid", gap: 12 }}>
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

function Section({ title, children }) {
  return (
    <div style={CARD}>
      <div style={LABEL}>{title}</div>
      <div style={{ fontSize: 13.5, color: "rgba(255,255,255,0.84)", lineHeight: 1.6 }}>
        {children}
      </div>
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
    if (expandedTurn != null) {
      setViewTurn(expandedTurn);
    }
  }, [expandedTurn]);

  const row =
    turns.find((item) => item.turn === viewTurn) ||
    turns[turns.length - 1] ||
    null;
  const nodes = row && row.nodes && typeof row.nodes === "object" ? row.nodes : {};
  const node = selectedNode ? nodes[selectedNode] || {} : null;
  const meta = selectedNode ? catalog[selectedNode] || {} : {};
  const title = meta.label || node?.label || selectedNode || "Node inspector";
  const stage = meta.stage || node?.stage || activeGraph;

  if (!expanded) {
    return (
      <div
        data-inspector-collapsed="true"
        style={{
          padding: 8,
          color: "#f5f7fb",
          background: "linear-gradient(180deg, #151515 0%, #101010 100%)",
          borderRadius: 16,
          border: "1px solid rgba(255,255,255,0.08)",
          minHeight: 72,
          display: "flex",
          justifyContent: "center",
        }}
      >
        <button
          type="button"
          onClick={() => sendAction("toggle_inspector", { expanded: true })}
          style={{
            writingMode: "vertical-rl",
            transform: "rotate(180deg)",
            background: "rgba(255,43,122,0.14)",
            border: "1px solid rgba(255,43,122,0.32)",
            color: "#ffe1ec",
            borderRadius: 999,
            padding: "12px 8px",
            fontSize: 12,
            fontWeight: 700,
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
  const rawInput =
    Object.prototype.hasOwnProperty.call(detail, "input")
      ? detail.input
      : detail.text ?? detail.original ?? detail.message ?? detail.source ?? null;
  const rawOutput =
    Object.prototype.hasOwnProperty.call(detail, "output")
      ? detail.output
      : detail.rewritten ?? detail.labels ?? detail.hits ?? detail.result ?? null;
  const leftover = Object.fromEntries(
    Object.entries(detail).filter(([key]) => !["input", "output", "why", "text", "original", "rewritten", "labels", "hits", "result", "message", "source"].includes(key))
  );
  const structured = rawInput != null || rawOutput != null || Object.keys(leftover).length > 0;
  const inputValue = structured ? rawInput : null;
  const outputValue = structured
    ? rawOutput != null
      ? rawOutput
      : leftover
    : leftover;
  const hasInput =
    inputValue != null &&
    !(typeof inputValue === "object" && !Array.isArray(inputValue) && Object.keys(inputValue).length === 0);
  const hasOutput =
    outputValue != null &&
    !(typeof outputValue === "object" && !Array.isArray(outputValue) && Object.keys(outputValue).length === 0);
  const purpose = meta.purpose || meta.function || node?.function || "No purpose note for this node.";
  const why = meta.why || meta.meaning || "No rationale note for this node.";
  const thisTurn = meta.this_turn || detail.why || (
    hasInput || hasOutput
      ? [
          hasInput ? { label: "Input", value: inputValue } : null,
          hasOutput ? { label: "Result", value: outputValue } : null,
        ].filter(Boolean)
      : "No structured activity was recorded for this turn."
  );
  const howItWorks = meta.how_it_works || meta.implementation || "No implementation note for this node.";

  return (
    <div
      data-inspector-collapsed="false"
      style={{
        padding: 14,
        color: "#f5f7fb",
        background:
          "radial-gradient(circle at top left, rgba(255,43,122,0.12), transparent 34%), linear-gradient(180deg, #151515 0%, #101010 100%)",
        borderRadius: 18,
        border: "1px solid rgba(255,255,255,0.08)",
        minHeight: 80,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.42)",
            fontWeight: 600,
          }}
        >
          Node inspector
        </div>
        <button
          type="button"
          onClick={() => sendAction("toggle_inspector", { expanded: false })}
          style={{
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.12)",
            color: "rgba(255,255,255,0.62)",
            borderRadius: 999,
            padding: "4px 11px",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          Collapse
        </button>
      </div>

      {turns.length > 0 ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 14,
          }}
        >
          <span style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>Turn</span>
          <select
            value={row ? row.turn : ""}
            onChange={(event) => setViewTurn(Number(event.target.value))}
            style={{
              flex: 1,
              background: "#121212",
              color: "#f5f7fb",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 10,
              padding: "6px 10px",
              fontSize: 13,
            }}
          >
            {turns.map((item) => (
              <option key={item.turn} value={item.turn}>
                Turn {item.turn}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {!selectedNode ? (
        <div style={{ display: "grid", gap: 12 }}>
          <Section title={String(stage).replace(/_/g, " ")}>
            {blurbs[stage] ||
              "Click a circuit node to inspect its function, implementation, and this-turn I/O."}
          </Section>
          <div style={{ fontSize: 12.5, color: "rgba(255,255,255,0.42)", lineHeight: 1.55 }}>
            Unused branches stay on the graph and can still be opened.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          <div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: "-0.03em",
                marginBottom: 8,
              }}
            >
              {title}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <Chip tone="accent">{String(stage).replace(/_/g, " ")}</Chip>
              {row ? <Chip>Turn {row.turn}</Chip> : null}
              <Chip tone={statusTone(node?.status)}>{statusLabel(node?.status)}</Chip>
            </div>
          </div>

          <Section title="Purpose">
            {purpose}
          </Section>
          <Section title="Why it matters">
            {why}
          </Section>

          <Section title="This turn">
            {typeof thisTurn === "string" ? (
              thisTurn
            ) : Array.isArray(thisTurn) ? (
              <div style={{ display: "grid", gap: 12 }}>
                {thisTurn.map((item) => (
                  <Field key={item.label} name={item.label}>
                    <ValueView value={item.value} />
                  </Field>
                ))}
              </div>
            ) : (
              <ValueView value={thisTurn} />
            )}
          </Section>

          <Section title="How it works">
            {howItWorks}
          </Section>
        </div>
      )}
    </div>
  );
}
