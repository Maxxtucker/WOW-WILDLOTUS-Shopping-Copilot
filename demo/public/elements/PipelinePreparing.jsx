import React from "react";

function toneForStatus(status) {
  if (status === "completed") {
    return { accent: "#fe2c55", glow: "rgba(254, 44, 85, 0.28)", text: "#ffe4ec" };
  }
  if (status === "error") {
    return { accent: "#ff6b8a", glow: "rgba(255, 107, 138, 0.2)", text: "#ffe0e8" };
  }
  return { accent: "#25f4ee", glow: "rgba(37, 244, 238, 0.22)", text: "#d9fbff" };
}

export default function PipelinePreparing() {
  const root = typeof props !== "undefined" ? props : {};
  const {
    title = "Starting agent",
    status = "running",
    detail = "Loading catalog index and warming NLU…",
  } = root ?? {};
  const tone = toneForStatus(status);
  const label =
    status === "completed" ? "Ready" : status === "error" ? "Failed" : "Starting";

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 560,
        borderRadius: 22,
        padding: 18,
        color: "#f7f3ff",
        background: `radial-gradient(ellipse 80% 60% at 0% 0%, ${tone.glow}, transparent 52%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)`,
        border: "1px solid rgba(196,181,253,0.22)",
        boxShadow: "0 18px 40px rgba(254,44,85,0.12)",
      }}
    >
      <style>
        {`
          @keyframes pipelinePrepareShimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
        `}
      </style>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.48)",
              marginBottom: 6,
            }}
          >
            Agent
          </div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{title}</div>
        </div>
        <div
          style={{
            padding: "6px 12px",
            borderRadius: 999,
            border: `1px solid ${tone.accent}55`,
            color: tone.accent,
            fontWeight: 700,
            fontSize: 12,
          }}
        >
          {label}
        </div>
      </div>
      <div style={{ fontSize: 14, color: tone.text, lineHeight: 1.5 }}>{detail}</div>
      {status === "running" ? (
        <div
          style={{
            marginTop: 14,
            height: 10,
            borderRadius: 999,
            overflow: "hidden",
            background: "rgba(255,255,255,0.08)",
          }}
        >
          <div
            style={{
              width: "42%",
              height: "100%",
              borderRadius: 999,
              background: "linear-gradient(90deg, #fe2c55 0%, #c4b5fd 50%, #25f4ee 100%)",
            }}
          />
          <div
            style={{
              marginTop: -10,
              height: 10,
              background:
                "linear-gradient(110deg, transparent 20%, rgba(255,255,255,0.22) 35%, transparent 50%)",
              backgroundSize: "200% 100%",
              animation: "pipelinePrepareShimmer 1.6s linear infinite",
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
