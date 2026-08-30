import React from "react";

function toneForStatus(status) {
  if (status === "completed") {
    return { accent: "#20c997", glow: "rgba(32, 201, 151, 0.18)", text: "#d7fff2" };
  }
  if (status === "error") {
    return { accent: "#ff6b6b", glow: "rgba(255, 107, 107, 0.16)", text: "#ffe0e0" };
  }
  return { accent: "#5da8ff", glow: "rgba(93, 168, 255, 0.18)", text: "#deecff" };
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
        color: "#f5f7fb",
        background: `radial-gradient(circle at top left, ${tone.glow}, transparent 28%), linear-gradient(180deg, #151515 0%, #101010 100%)`,
        border: "1px solid rgba(255,255,255,0.08)",
        boxShadow: "0 20px 40px rgba(0,0,0,0.28)",
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
              background: "linear-gradient(90deg, #5da8ff 0%, #88baff 55%, #c9dcff 100%)",
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
