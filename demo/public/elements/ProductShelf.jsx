import { useState } from "react";

function formatPrice(price) {
  if (price === null || price === undefined) return "Price n/a";
  return `$${Number(price).toFixed(price % 1 ? 2 : 0)}`;
}

function Thumb({ card, large }) {
  const {
    title = "",
    store = "",
    accent = "#ff2b7a",
    image_url = null,
  } = card || {};
  const [failed, setFailed] = useState(false);
  const initial = (store || title || "?").trim().charAt(0).toUpperCase();
  const showImage = Boolean(image_url) && !failed;
  const size = large ? 112 : 72;

  return (
    <div
      style={{
        flexShrink: 0,
        width: size,
        height: size,
        borderRadius: large ? 14 : 10,
        overflow: "hidden",
        background: showImage
          ? "#101010"
          : `linear-gradient(145deg, ${accent} 0%, #101010 100%)`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        border: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      {showImage ? (
        <img
          src={image_url}
          alt=""
          onError={() => setFailed(true)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            display: "block",
          }}
        />
      ) : (
        <span
          style={{
            fontSize: large ? 28 : 18,
            fontWeight: 700,
            color: "#FFFFFF",
          }}
        >
          {initial}
        </span>
      )}
    </div>
  );
}

function ShelfCard({ card }) {
  const { title = "", price = null, rating = null, on_slate = false } = card || {};
  const ratingText =
    rating === null || rating === undefined ? null : Number(rating).toFixed(1);
  return (
    <div
      style={{
        minWidth: 0,
        width: "100%",
        padding: 10,
        borderRadius: 12,
        background: on_slate
          ? "linear-gradient(180deg, rgba(255,43,122,0.16) 0%, #151515 100%)"
          : "linear-gradient(180deg, #151515 0%, #101010 100%)",
        border: on_slate
          ? "1px solid rgba(255,43,122,0.55)"
          : "1px solid rgba(255,255,255,0.08)",
        boxShadow: on_slate ? "0 0 0 1px rgba(255,43,122,0.2)" : "none",
        boxSizing: "border-box",
      }}
    >
      <Thumb card={card} large={false} />
      <div
        style={{
          marginTop: 8,
          fontSize: 12,
          fontWeight: 600,
          lineHeight: 1.3,
          color: "#f5f7fb",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          minHeight: 32,
        }}
      >
        {title}
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: "rgba(255,255,255,0.64)" }}>
        {formatPrice(price)}
        {ratingText ? ` · ★ ${ratingText}` : ""}
      </div>
    </div>
  );
}

function resolveCards(root) {
  const fromCards = Array.isArray(root.cards) ? root.cards : [];
  if (fromCards.length) {
    return fromCards.slice(0, 10);
  }
  const legacy = [root.hero, ...(Array.isArray(root.others) ? root.others : [])].filter(
    Boolean,
  );
  return legacy.slice(0, 10);
}

export default function ProductShelf() {
  const message = String(props.message || "").trim();
  const cards = resolveCards(typeof props !== "undefined" ? props : {});
  const clarifyPrompt = props.clarify_prompt || "";
  const clarifyActions = Array.isArray(props.clarify_actions)
    ? props.clarify_actions
    : [];
  const showExplore = Boolean(props.show_explore);
  const exploreLabel = props.explore_label || "More like this";
  const exploreText =
    props.explore_text || "More like this one would be nice";

  if (cards.length === 0 && !message) {
    return null;
  }

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 760,
        marginTop: 10,
        color: "#f5f7fb",
        boxSizing: "border-box",
      }}
    >
      {message ? (
        <div
          style={{
            marginBottom: cards.length ? 12 : 0,
            fontSize: 15,
            lineHeight: 1.5,
            color: "rgba(255,255,255,0.86)",
            whiteSpace: "pre-wrap",
          }}
        >
          {message}
        </div>
      ) : null}

      {cards.length > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
            gap: 10,
          }}
        >
          {cards.map((card) => (
            <ShelfCard key={card.parent_asin || card.title} card={card} />
          ))}
        </div>
      ) : null}

      {clarifyPrompt ? (
        <div
          style={{
            marginTop: 18,
            paddingTop: 14,
            borderTop: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.5,
              color: "rgba(255,255,255,0.82)",
              whiteSpace: "pre-wrap",
            }}
          >
            {clarifyPrompt}
          </div>
          {Array.isArray(clarifyActions) && clarifyActions.length > 0 ? (
            <div
              style={{
                marginTop: 12,
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              {clarifyActions.map((action) => (
                <button
                  key={action.label || action.text}
                  type="button"
                  onClick={() =>
                    callAction({
                      name: "quick_reply",
                      payload: { text: action.text },
                    })
                  }
                  style={{
                    borderRadius: 999,
                    border: "1px solid rgba(255,43,122,0.28)",
                    background: "rgba(255,43,122,0.12)",
                    color: "#ffe1ec",
                    padding: "8px 14px",
                    fontSize: 13,
                    fontWeight: 500,
                    cursor: "pointer",
                  }}
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {showExplore ? (
        <div style={{ marginTop: 16 }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.4)",
              fontWeight: 600,
              marginBottom: 8,
            }}
          >
            Explore
          </div>
          <button
            type="button"
            onClick={() =>
              callAction({
                name: "quick_reply",
                payload: { text: exploreText },
              })
            }
            style={{
              borderRadius: 999,
              border: "1px solid rgba(255,43,122,0.28)",
              background: "rgba(255,43,122,0.12)",
              color: "#ffe1ec",
              padding: "8px 14px",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            ♡ {exploreLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}
