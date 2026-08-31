import { useEffect, useState } from "react";

const DEFAULT_POSITION = 34.375;

function sendPreference(position) {
  if (typeof callAction !== "function") {
    return;
  }
  callAction({
    name: "set_recommendation_preference",
    payload: { position },
  });
}

export default function RecommendationPreference() {
  const root = typeof props !== "undefined" ? props : {};
  const externalPosition = Number(root.position ?? DEFAULT_POSITION);
  const locked = Boolean(root.locked);
  const [position, setPosition] = useState(externalPosition);

  useEffect(() => {
    setPosition(externalPosition);
  }, [externalPosition]);

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 680,
        borderRadius: 20,
        padding: "18px 20px 16px",
        color: "#f7f3ff",
        background:
          "radial-gradient(ellipse 80% 60% at 0% 0%, rgba(254,44,85,0.2), transparent 52%), radial-gradient(ellipse 70% 50% at 100% 0%, rgba(37,244,238,0.12), transparent 48%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)",
        border: "1px solid rgba(196,181,253,0.22)",
        boxShadow: "0 18px 36px rgba(254,44,85,0.12)",
        opacity: locked ? 0.62 : 1,
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 20 }}>
        Recommendation preference
      </div>
      <div style={{ position: "relative", paddingTop: 24 }}>
        <div
          style={{
            position: "absolute",
            top: 0,
            left: `${DEFAULT_POSITION}%`,
            transform: "translateX(-50%)",
            padding: "2px 7px",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: "#ffe4ec",
            background: "linear-gradient(135deg, rgba(254,44,85,0.22), rgba(37,244,238,0.12))",
            border: "1px solid rgba(37,244,238,0.28)",
          }}
        >
          Default
        </div>
        <input
          type="range"
          min="0"
          max="100"
          step="0.125"
          value={position}
          disabled={locked}
          aria-label="Recommendation preference"
          onChange={(event) => {
            const next = Number(event.target.value);
            setPosition(next);
            if (!locked) {
              sendPreference(next);
            }
          }}
          style={{
            width: "100%",
            accentColor: "#fe2c55",
            cursor: locked ? "not-allowed" : "pointer",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 20,
          marginTop: 8,
          fontSize: 12,
          color: "rgba(255,255,255,0.66)",
        }}
      >
        <span>Recommend more products</span>
        <span style={{ textAlign: "right" }}>More precise recommendations</span>
      </div>
      {locked ? (
        <div
          style={{
            marginTop: 12,
            fontSize: 11,
            color: "rgba(255,255,255,0.48)",
          }}
        >
          Locked for this conversation
        </div>
      ) : null}
    </div>
  );
}
