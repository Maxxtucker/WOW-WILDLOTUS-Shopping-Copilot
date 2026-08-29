import { useState } from "react";

export default function ProductCard() {
  const {
    title = "",
    price = null,
    store = "",
    rating = null,
    blurb = "",
    tags = [],
    accent = "#4A7C59",
    image_url = null,
  } = props;

  const [imageFailed, setImageFailed] = useState(false);

  const priceText =
    price === null || price === undefined
      ? "Price n/a"
      : `$${Number(price).toFixed(price % 1 ? 2 : 0)}`;

  const ratingText =
    rating === null || rating === undefined
      ? null
      : Number(rating).toFixed(1);

  const initial = (store || title || "?").trim().charAt(0).toUpperCase();
  const showImage = Boolean(image_url) && !imageFailed;

  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        marginTop: 10,
        maxWidth: 520,
        padding: 14,
        borderRadius: 14,
        background: "#2A2A2A",
        border: "1px solid #3F3F3F",
        color: "#F3F3F3",
        boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
      }}
    >
      <div
        style={{
          flexShrink: 0,
          width: 88,
          height: 88,
          borderRadius: 12,
          overflow: "hidden",
          background: showImage
            ? "#1A1A1A"
            : `linear-gradient(145deg, ${accent} 0%, #1F1F1F 100%)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "1px solid #404040",
        }}
        aria-hidden="true"
      >
        {showImage ? (
          <img
            src={image_url}
            alt=""
            onError={() => setImageFailed(true)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              display: "block",
            }}
          />
        ) : (
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 999,
              background: "rgba(255,255,255,0.14)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
              fontWeight: 700,
              color: "#FFFFFF",
            }}
          >
            {initial}
          </div>
        )}
      </div>

      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontWeight: 600,
            fontSize: 15,
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
            alignItems: "baseline",
            gap: 14,
            fontSize: 14,
          }}
        >
          <span style={{ fontWeight: 700, color: "#FFFFFF" }}>{priceText}</span>
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
