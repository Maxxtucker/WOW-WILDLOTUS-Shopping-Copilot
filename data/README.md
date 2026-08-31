# Competition Data

## `public_set.jsonl`

Contains 200 labeled development sessions: 80 Buying, 80 Browsing, 30 Intent Override, and 10 Boundary sessions.

Each session contains a safe aggregate `user_profile` and public labels for local development. Direct user identifiers, timestamps, free-text reviews, raw purchase history, hidden intent cards, and simulator-policy internals are not shipped in this participant file.

## `catalog.jsonl`

Download `catalog.jsonl.gz` from the GitHub Release and decompress it as `catalog.jsonl` in this directory. Expected row count: 50,000.

From the repository root (SHA-256 verified; skips the download when the file already exists):

```bash
python scripts/download_catalog.py
```

`python scripts/bootstrap.py` runs that step as part of first-time setup. See [`scripts/README.md`](../scripts/README.md).

## `catalog_images.jsonl` (optional, UI only)

Side-car map of `parent_asin` → `main_image_url` joined from Amazon Reviews 2023 item metadata (Clothing_Shoes_and_Jewelry). Does not change the frozen contest catalog.

Build:

```bash
python scripts/build_catalog_images.py
```

Source: https://amazon-reviews-2023.github.io/ (item metadata `images`, not review images).

Never place API keys, private evaluation data, or participant outputs in this directory.
