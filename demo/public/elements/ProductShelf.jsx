import { useState } from "react";

function formatPrice(price) {
  if (price === null || price === undefined) return "Price n/a";
  return `$${Number(price).toFixed(price % 1 ? 2 : 0)}`;
}

function Thumb({ card, large }) {
  const {
    title = "",
    store = "",
    accent = "#4A7C59",
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
          ? "#1A1A1A"
          : `linear-gradient(145deg, ${accent} 0%, #1F1F1F 100%)`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        border: "1px solid #404040",
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

function HeroCard({ card }) {
  if (!card) return null;
  const {
    title = "",
    price = null,
    rating = null,
    blurb = "",
    tags = [],
  } = card;
  const ratingText =
    rating === null || rating === undefined ? null : Number(rating).toFixed(1);

  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        padding: 16,
        borderRadius: 16,
        background: "#2A2A2A",
        border: "1px solid #525252",
        boxShadow: "0 0 0 1px rgba(255,255,255,0.04)",
      }}
    >
      <Thumb card={card} large />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: "#FBBF24",
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          ⭐ Best match
        </div>
        <div
          style={{
            fontWeight: 600,
            fontSize: 16,
            lineHeight: 1.35,
            color: "#FAFAFA",
          }}
        >
          {title}
        </div>
        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 12,
            alignItems: "baseline",
            fontSize: 15,
          }}
        >
          <span style={{ fontWeight: 700, color: "#FFFFFF" }}>
            {formatPrice(price)}
          </span>
          {ratingText ? (
            <span style={{ color: "#D4D4D4" }}>★ {ratingText}</span>
          ) : null}
        </div>
        {blurb ? (
          <div
            style={{
              marginTop: 8,
              fontSize: 13,
              lineHeight: 1.45,
              color: "#C4C4C4",
            }}
          >
            {blurb}
          </div>
        ) : null}
        {Array.isArray(tags) && tags.length > 0 ? (
          <div
            style={{
              marginTop: 10,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            {tags.map((tag) => (
              <span
                key={tag}
                style={{
                  fontSize: 12,
                  color: "#E5E5E5",
                  background: "#3A3A3A",
                  border: "1px solid #525252",
                  borderRadius: 999,
                  padding: "3px 10px",
                }}
              >
                ✓ {tag}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MiniCard({ card }) {
  const { title = "", price = null, rating = null } = card || {};
  const ratingText =
    rating === null || rating === undefined ? null : Number(rating).toFixed(1);
  return (
    <div
      style={{
        flex: "0 0 auto",
        width: 148,
        padding: 10,
        borderRadius: 12,
        background: "#242424",
        border: "1px solid #3F3F3F",
      }}
    >
      <Thumb card={card} large={false} />
      <div
        style={{
          marginTop: 8,
          fontSize: 12,
          fontWeight: 600,
          lineHeight: 1.3,
          color: "#F3F3F3",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          minHeight: 32,
        }}
      >
        {title}
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: "#D4D4D4" }}>
        {formatPrice(price)}
        {ratingText ? ` · ★ ${ratingText}` : ""}
      </div>
    </div>
  );
}

export default function ProductShelf() {
  const hero = props.hero || null;
  const others = Array.isArray(props.others) ? props.others : [];
  const clarifyPrompt = props.clarify_prompt || "";
  const clarifyActions = Array.isArray(props.clarify_actions)
    ? props.clarify_actions
    : [];
  const showExplore = Boolean(props.show_explore);
  const exploreLabel = props.explore_label || "More like this";
  const exploreText =
    props.explore_text || "More like this one would be nice";

  if (!hero && others.length === 0) {
    return null;
  }

  return (
    <div style={{ marginTop: 10, maxWidth: 560, color: "#F3F3F3" }}>
      {hero ? <HeroCard card={hero} /> : null}

      {others.length > 0 ? (
        <div style={{ marginTop: 14 }}>
          <div
            style={{
              fontSize: 12,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: "#A3A3A3",
              fontWeight: 600,
              marginBottom: 8,
            }}
          >
            Other good matches →
          </div>
          <div
            style={{
              display: "flex",
              gap: 10,
              overflowX: "auto",
              paddingBottom: 6,
              WebkitOverflowScrolling: "touch",
            }}
          >
            {others.map((card) => (
              <MiniCard
                key={card.parent_asin || card.title}
                card={card}
              />
            ))}
          </div>
        </div>
      ) : null}

      {clarifyPrompt ? (
        <div
          style={{
            marginTop: 18,
            paddingTop: 14,
            borderTop: "1px solid #3F3F3F",
          }}
        >
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.5,
              color: "#E5E5E5",
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
                    border: "1px solid #525252",
                    background: "#333333",
                    color: "#F5F5F5",
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
        <div style={{ marginTop: clarifyPrompt ? 16 : 16 }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: "#737373",
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
              border: "1px solid #525252",
              background: "#333333",
              color: "#F5F5F5",
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
