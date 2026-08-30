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
        color: "#f5f7fb",
        background: "linear-gradient(180deg, #171717 0%, #101010 100%)",
        border: "1px solid rgba(255,255,255,0.09)",
        boxShadow: "0 18px 36px rgba(0,0,0,0.24)",
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
            color: "#ffd7e7",
            background: "rgba(255,43,122,0.14)",
            border: "1px solid rgba(255,43,122,0.24)",
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
            accentColor: "#ff2b7a",
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
