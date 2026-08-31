import { useState } from "react";

export default function ProductCard() {
  const {
    title = "",
    price = null,
    store = "",
    rating = null,
    blurb = "",
    tags = [],
    accent = "#fe2c55",
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
        borderRadius: 16,
        background:
          "radial-gradient(ellipse 80% 70% at 0% 0%, rgba(254,44,85,0.16), transparent 50%), linear-gradient(165deg, #1c122c 0%, #0c0816 100%)",
        border: "1px solid rgba(196,181,253,0.22)",
        color: "#f7f3ff",
        boxShadow: "0 14px 32px rgba(254,44,85,0.1)",
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
            ? "#0c0816"
            : `linear-gradient(145deg, ${accent} 0%, #0c0816 100%)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "1px solid rgba(196,181,253,0.2)",
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
                  color: "#f7f3ff",
                  background: "linear-gradient(135deg, rgba(254,44,85,0.2), rgba(37,244,238,0.12))",
                  border: "1px solid rgba(37,244,238,0.22)",
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
