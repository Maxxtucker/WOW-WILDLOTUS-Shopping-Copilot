function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function num(value, digits) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(digits);
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
      <span style={{ color: "rgba(255,255,255,0.55)" }}>{label}</span>
      <strong style={{ color: "#f5f7fb" }}>{value}</strong>
    </div>
  );
}

export default function EvalScoreCard() {
  const root = typeof props !== "undefined" ? props : {};
  const kind = root.kind || "session";
  const hit = Boolean(root.hit);
  const accent = kind === "group" ? "#25f4ee" : hit ? "#25f4ee" : "#fe2c55";

  if (kind === "session") {
    return (
      <div
        style={{
          width: "100%",
          maxWidth: 420,
          borderRadius: 18,
          padding: 16,
          color: "#f7f3ff",
          background: `radial-gradient(ellipse 80% 60% at 0% 0%, ${accent}33, transparent 52%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)`,
          border: "1px solid rgba(196,181,253,0.22)",
        }}
      >
        <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255,255,255,0.42)", fontWeight: 700 }}>
          Session score
        </div>
        <div style={{ fontSize: 17, fontWeight: 650, margin: "6px 0 12px" }}>
          {root.sample_id || "sample"} · {hit ? "HIT" : "MISS"}
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          <Row label="Scenario" value={root.scenario_type || "—"} />
          <Row label="First hit turn" value={root.first_hit_turn ?? "—"} />
          <Row label="Best rank" value={root.best_rank ?? "—"} />
          <Row label="Reciprocal rank" value={num(root.reciprocal_rank, 3)} />
        </div>
      </div>
    );
  }

  const scenarios = root.scenario_metrics || {};
  return (
    <div
      style={{
        width: "100%",
        maxWidth: 480,
        borderRadius: 18,
        padding: 16,
          color: "#f7f3ff",
          background:
            "radial-gradient(ellipse 80% 60% at 0% 0%, rgba(37,244,238,0.18), transparent 50%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)",
          border: "1px solid rgba(196,181,253,0.22)",
      }}
    >
      <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255,255,255,0.42)", fontWeight: 700 }}>
        Group score
      </div>
      <div style={{ fontSize: 17, fontWeight: 650, margin: "6px 0 12px" }}>
        Technical {num(root.recommended_technical_score, 3)}
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        <Row label="Sessions" value={root.sample_count ?? 0} />
        <Row label="Hit@10" value={pct(root.hit_rate_at_10)} />
        <Row label="MRR" value={num(root.mrr, 3)} />
        <Row label="MTTC" value={root.mttc == null ? "—" : num(root.mttc, 2)} />
        <Row label="Efficiency" value={pct(root.efficiency)} />
      </div>
      {Object.keys(scenarios).length ? (
        <div style={{ marginTop: 12, display: "grid", gap: 6 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "rgba(255,255,255,0.42)" }}>
            By scenario
          </div>
          {Object.entries(scenarios).map(([name, row]) => (
            <Row
              key={name}
              label={name}
              value={`${row.sample_count} · hit ${pct(row.hit_rate_at_10)} · MRR ${num(row.mrr, 3)}`}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
