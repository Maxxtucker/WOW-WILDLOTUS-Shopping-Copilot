import { useState } from "react";

function sendAction(name, payload) {
  if (typeof callAction !== "function") {
    return;
  }
  callAction({ name, payload });
}

function Field({ label, children }) {
  return (
    <label style={{ display: "grid", gap: 6, fontSize: 12, color: "rgba(255,255,255,0.62)" }}>
      <span style={{ letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 600 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

const inputStyle = {
  borderRadius: 10,
  border: "1px solid rgba(196,181,253,0.28)",
  background: "linear-gradient(180deg, #241634, #12081c)",
  color: "#f7f3ff",
  padding: "8px 10px",
  fontSize: 13,
  colorScheme: "dark",
};

const btnStyle = {
  borderRadius: 999,
  border: "1px solid rgba(254,44,85,0.38)",
  background: "linear-gradient(135deg, rgba(254,44,85,0.22), rgba(37,244,238,0.1))",
  color: "#ffe4ec",
  padding: "8px 14px",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
};

const ghostBtn = {
  ...btnStyle,
  background: "linear-gradient(135deg, rgba(196,181,253,0.12), rgba(37,244,238,0.08))",
  borderColor: "rgba(196,181,253,0.22)",
  color: "#f7f3ff",
};

const BUYER_MODES = [
  { id: "1", label: "1 — Template" },
  { id: "2", label: "2 — Protected paraphrase" },
  { id: "3", label: "3 — Synonym rewrite" },
  { id: "4", label: "4 — Poor English" },
];

const LLM_MODES = [
  { id: "remote", label: "Remote" },
  { id: "local", label: "Local qwen3.5:4b" },
];

export default function EvalDock() {
  const root = typeof props !== "undefined" ? props : {};
  const evaluators = Array.isArray(root.evaluators) ? root.evaluators : [];
  const catalog = Array.isArray(root.catalog) ? root.catalog : [];
  const [evaluator, setEvaluator] = useState(root.selectedEvaluator || "");
  const [selection, setSelection] = useState(root.selection || "one");
  const [sampleId, setSampleId] = useState(root.sampleId || "");
  const [query, setQuery] = useState("");
  const [rangeStart, setRangeStart] = useState(root.rangeStart || "1");
  const [rangeEnd, setRangeEnd] = useState(root.rangeEnd || "10");
  const [randomN, setRandomN] = useState(String(root.randomN || "5"));
  const [mode, setMode] = useState(root.mode || "auto");
  const [buyerMode, setBuyerMode] = useState(String(root.buyerMode || "1"));
  const [llmMode, setLlmMode] = useState(String(root.llmMode || "remote"));
  const [expanded, setExpanded] = useState(true);
  const selectedBackend = String(evaluator || root.selectedEvaluator || "").trim();
  const canRun = selectedBackend === "local" || selectedBackend === "scenario";
  const showBuyerMode = selectedBackend === "scenario";
  const status = root.status || "idle";
  const canStep = Boolean(root.canStep);
  const busy = status === "running" || (status === "step" && !canStep);
  const selected = catalog.find((row) => row.sample_id === sampleId);
  const filtered = catalog.filter((row) => {
    const hay = `${row.sample_id} ${row.scenario_type} ${row.difficulty_bucket}`.toLowerCase();
    return hay.includes(query.trim().toLowerCase());
  });

  const payload = (overrides = {}) => ({
    evaluator: selectedBackend,
    selectedEvaluator: selectedBackend,
    selection,
    sampleId,
    rangeStart,
    rangeEnd,
    randomN,
    mode,
    buyerMode: Number(buyerMode) || 1,
    llmMode: llmMode === "local" ? "local" : "remote",
    ...overrides,
  });

  const persist = (overrides = {}) => {
    sendAction("eval_configure", payload(overrides));
  };

  const actions = (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {expanded ? (
        <button
          type="button"
          disabled={busy || !canRun}
          onClick={() =>
            sendAction(mode === "step" ? "eval_step_start" : "eval_run", payload())
          }
          style={{ ...btnStyle, opacity: busy || !canRun ? 0.45 : 1 }}
        >
          {mode === "step" ? "Start step-through" : "Run"}
        </button>
      ) : null}
      <button
        type="button"
        disabled={!canStep}
        onClick={() => sendAction("eval_step", {})}
        style={{ ...btnStyle, opacity: canStep ? 1 : 0.45 }}
      >
        Next turn
      </button>
      <button
        type="button"
        onClick={() => sendAction("eval_cancel", {})}
        style={ghostBtn}
      >
        Cancel
      </button>
    </div>
  );

  return (
    <div data-eval-dock="" style={{ height: 0, overflow: "visible", margin: 0, padding: 0 }}>
      <div
        style={{
          position: "fixed",
          zIndex: 60,
          left: "50%",
          transform: "translateX(-50%)",
          bottom: "var(--eval-dock-bottom, 96px)",
          width: "min(560px, calc(100vw - 32px))",
          color: "#f7f3ff",
          pointerEvents: "auto",
        }}
      >
        {expanded ? (
          <div
            style={{
              borderRadius: 22,
              padding: 18,
              background:
                "radial-gradient(ellipse 80% 60% at 0% 0%, rgba(254,44,85,0.22), transparent 52%), radial-gradient(ellipse 70% 50% at 100% 0%, rgba(37,244,238,0.12), transparent 48%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)",
              border: "1px solid rgba(196,181,253,0.22)",
              boxShadow: "0 20px 40px rgba(254,44,85,0.14)",
              display: "grid",
              gap: 14,
              maxHeight: "min(70vh, 640px)",
              overflow: "auto",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255,255,255,0.42)", fontWeight: 700 }}>
                  Evaluator
                </div>
                <div style={{ fontSize: 18, fontWeight: 650, marginTop: 4 }}>Public-set dock</div>
              </div>
              <button type="button" onClick={() => setExpanded(false)} style={ghostBtn}>
                Collapse
              </button>
            </div>

            <Field label="Backend">
              <select
                value={selectedBackend}
                onChange={(event) => {
                  const next = event.target.value;
                  setEvaluator(next);
                  persist({ evaluator: next, selectedEvaluator: next });
                }}
                style={inputStyle}
              >
                <option value="">Select an evaluator…</option>
                {evaluators.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.enabled}>
                    {item.label}
                    {item.path ? ` (${item.path})` : item.enabled ? "" : " — soon"}
                  </option>
                ))}
              </select>
            </Field>

            {showBuyerMode ? (
              <>
                <Field label="Buyer mode">
                  <select
                    value={buyerMode}
                    onChange={(event) => {
                      const next = event.target.value;
                      setBuyerMode(next);
                      persist({ buyerMode: Number(next) || 1 });
                    }}
                    style={inputStyle}
                  >
                    {BUYER_MODES.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="LLM mode">
                  <select
                    value={llmMode}
                    onChange={(event) => {
                      const next = event.target.value === "local" ? "local" : "remote";
                      setLlmMode(next);
                      persist({ llmMode: next });
                    }}
                    style={inputStyle}
                  >
                    {LLM_MODES.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            ) : null}

            {canRun ? (
              <div
                style={{
                  display: "grid",
                  gap: 12,
                  padding: 12,
                  borderRadius: 16,
                  border: "1px solid rgba(196,181,253,0.16)",
                  background: "rgba(7,4,14,0.35)",
                }}
              >
                <div style={{ fontSize: 12, color: "rgba(255,255,255,0.7)" }}>
                  {root.total || catalog.length} public_set sessions. Pick one, a range, all, or a random sample.
                </div>
                <Field label="Selection">
                  <select
                    value={selection}
                    onChange={(event) => setSelection(event.target.value)}
                    style={inputStyle}
                  >
                    <option value="one">One sample</option>
                    <option value="range">Range</option>
                    <option value="all">All</option>
                    <option value="random">Random sample</option>
                  </select>
                </Field>

                {selection === "one" ? (
                  <>
                    <Field label="Search">
                      <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="public_0001, buying, hard…"
                        style={inputStyle}
                      />
                    </Field>
                    <div
                      style={{
                        maxHeight: 160,
                        overflow: "auto",
                        display: "grid",
                        gap: 4,
                      }}
                    >
                      {filtered.map((row) => (
                        <button
                          key={row.sample_id}
                          type="button"
                          onClick={() => setSampleId(row.sample_id)}
                          style={{
                            ...btnStyle,
                            borderRadius: 10,
                            textAlign: "left",
                            background:
                              row.sample_id === sampleId
                                ? "linear-gradient(135deg, rgba(254,44,85,0.32), rgba(37,244,238,0.16))"
                                : "rgba(247,243,255,0.04)",
                            borderColor:
                              row.sample_id === sampleId
                                ? "#25f4ee"
                                : "rgba(196,181,253,0.16)",
                          }}
                        >
                          {row.index}. {row.sample_id} · {row.scenario_type} · {row.difficulty_bucket}
                        </button>
                      ))}
                    </div>
                    {selected ? (
                      <div style={{ fontSize: 13, lineHeight: 1.5, color: "#ffe4ec" }}>
                        <div>
                          <strong>{selected.sample_id}</strong>
                        </div>
                        <div>
                          {selected.scenario_type} · {selected.difficulty_bucket} · {selected.category_bucket}
                        </div>
                      </div>
                    ) : null}
                  </>
                ) : null}

                {selection === "range" ? (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <Field label="Start">
                      <input
                        value={rangeStart}
                        onChange={(event) => setRangeStart(event.target.value)}
                        placeholder="1 or public_0001"
                        style={inputStyle}
                      />
                    </Field>
                    <Field label="End">
                      <input
                        value={rangeEnd}
                        onChange={(event) => setRangeEnd(event.target.value)}
                        placeholder="10 or public_0010"
                        style={inputStyle}
                      />
                    </Field>
                  </div>
                ) : null}

                {selection === "random" ? (
                  <Field label="Sample size N">
                    <input
                      type="number"
                      min="1"
                      value={randomN}
                      onChange={(event) => setRandomN(event.target.value)}
                      style={inputStyle}
                    />
                  </Field>
                ) : null}

                {selection === "all" ? (
                  <div style={{ fontSize: 12, color: "#ffd27d" }}>
                    All {catalog.length} sessions × up to 10 live NLU turns can take a long time.
                  </div>
                ) : null}

                <Field label="Mode">
                  <select
                    value={mode}
                    onChange={(event) => setMode(event.target.value)}
                    style={inputStyle}
                  >
                    <option value="auto">Auto-run (default)</option>
                    <option value="step">Step through turns</option>
                  </select>
                </Field>
              </div>
            ) : null}

            {root.statusDetail ? (
              <div style={{ fontSize: 13, color: "rgba(255,255,255,0.75)" }}>{root.statusDetail}</div>
            ) : null}
            {root.warning ? (
              <div style={{ fontSize: 12, color: "#ffd27d" }}>{root.warning}</div>
            ) : null}
            {actions}
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              borderRadius: 999,
              padding: "8px 10px 8px 12px",
              background: "linear-gradient(90deg, #1c122c 0%, #0c0816 100%)",
              border: "1px solid rgba(37,244,238,0.28)",
              boxShadow: "0 12px 28px rgba(254,44,85,0.18)",
            }}
          >
            <button type="button" onClick={() => setExpanded(true)} style={btnStyle}>
              Eval
            </button>
            <span
              style={{
                flex: "1 1 140px",
                minWidth: 0,
                fontSize: 12,
                color: "rgba(255,255,255,0.72)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {root.statusDetail || "Pinned to composer"}
            </span>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
