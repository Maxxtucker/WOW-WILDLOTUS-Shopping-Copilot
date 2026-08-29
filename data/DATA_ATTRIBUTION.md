# Data Attribution and Use

This competition package is derived from **Amazon Reviews 2023**, published by McAuley Lab at UCSD.

- Project page: https://amazon-reviews-2023.github.io/
- Selected category: `Clothing_Shoes_and_Jewelry`
- Product join key: `parent_asin`
- Competition modality: text and structured product metadata only

The competition package does not contain images, videos, account credentials, private organizer labels, or the private holdout sessions.

Participants must follow the source dataset's applicable terms and use the data only for the competition, research, and other permitted purposes. The competition organizer does not claim ownership of the underlying Amazon review or product content.

## Catalog slot aliases (offline preprocess)

These sources are used only by `scripts/build_aliases_color.py` and
`scripts/build_aliases_material.py` to build committed lookup JSON. They are
not loaded by the Agent at scoring time, and they do not define user NLU.

- [NacerKr/colors-normalized](https://huggingface.co/datasets/NacerKr/colors-normalized) (MIT): messy color names mapped to a 20-color palette, then to the evaluator 11-color list.
- [kobo-labs-open-source/textile-fiber-database](https://github.com/kobo-labs-open-source/textile-fiber-database) (MIT): fiber and FTC/EU labelling names mapped to the evaluator material list, plus a small leather/typo table.


