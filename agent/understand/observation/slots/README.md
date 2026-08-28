# observation/slots — typed constraint grounding

## Purpose

Turn one LLM or regex constraint into a `ConstraintSlot`. The model reads ordinary shopper language. Code checks that cited text is in the message, and that classified labels are official keys. Category may be a top-level field and/or `attribute=category` rows.

Each slot has `is_hard`. Hardness is user language (must vs prefer), not evaluator `intent_card` fingerprints. Same `(attribute, value)` later overwrites earlier hardness. Different values of the same attribute may be hard and soft at once.

When `typed_constraints` is non-empty, retrieve uses hard slots to prune and soft slots only as preferred scoring. Empty slots fall back to `active_constraints` strings (not leftover hints). Understand defaults to NLU; regex is the fallback after failed extracts or `understand_mode="regex"`.

Do not copy evaluator `intent_card`, customer templates, or `public_set.jsonl` labels into these handlers.

## Design

### Cite vs classify

Two kinds of fields. Mixing them is the usual bug.

| Role | Fields | After the model returns |
|---|---|---|
| **Cite** (must appear in the message) | `surface`; optional `surfaces[]`; budget/size `amount`; dimension `length` / `width` / `height` as the **original** numbers | Drop the slot (or the invented number) if the span/digit is missing |
| **Classify** (official key, not a shopper word) | color/material `canonical` list; size `kind`; size `system`; apparel letter `canonical`; dimension `unit` | Accept only closed-list keys. Do not span-check `blue`, `shoe`, `us`, `mm`, or converted millimetres |

`navy` → `blue` is classify. The cited word is still `navy`. Same split for `extra small` → `xs` (model `canonical` only) and `21 cm` → `unit=mm`, `length=210` (cite `21 cm`, do not cite `210`).

### OR alternatives

One utterance may still emit `canonical: ["blue", "orange", "pink"]`. Writeback splits that into one row per value so a later "must be blue" can flip only blue to hard. Retrieve ORs hard values of the same attribute; it ANDs across attributes. Soft rows never join the exact intersection.

### Ten attributes

`pipeline.py` span-grounds `surface`, then `attributes/__init__.py` dispatches.

| Attribute | Handler | Grounding |
|---|---|---|
| `category` | `attributes/category.py` | Top-level span or a category slot. Hard and soft category names may coexist. |
| `color` | `attributes/color.py` | Each `canonical` member ∈ closed color list. Surface may be a synonym; grey/gray are one bucket. Missing canonical and surface not already a list member → drop. |
| `material` | `attributes/material.py` | Same pattern against `MATERIALS`. |
| `size` | `attributes/size.py` | See below. Never one shared XS–XXL class for shoes and boxes. Letter `canonical` is a 1-tuple. |
| `budget` | `attributes/budget.py` | Digit in the message; `op` is `lte` / `gte` / `eq`. |
| `style` `brand` `feature` `use_case` `other` | matching modules via `free.py` | Copied span. `canonical` optional list, not span-checked. |

### Size

Catalog `details.Size` mixes garment letters, US/UK/EU footwear, clothing numeric charts (`US 4-6`), and object dimensions (`3" x 3"`). SQL must branch on `kind`.

| `kind` | Meaning | Structured fields |
|---|---|---|
| `shoe` | Footwear | `system` ∈ {us, uk, eu} when that label sits near the size digits (either side, short window). `amount` is the number. Letter `canonical` is null. |
| `apparel` | Clothes and pants | Letter: model `canonical` ∈ {xs, s, m, l, xl, xxl, xxxl, one_size}, or surface that **already is** that key (`XL`). Numeric clothing (`US 4`, waist 32): `amount` plus optional `system`. Not a shoe size. |
| `dimension` | Object L/W/H | `unit` ∈ {in, mm}. cm → mm (×10). Copy original numbers; convert after cite-check. |
| null | Product type unclear | Keep `surface`. Do not guess shoe vs dress from `US 10` alone. |

`kind` comes from the model (`shoes` folds to `shoe`). Code infers `dimension` only when the **size surface** is a measurement (`3 x 3`, `21 cm`), not from product words like `hoodie` / `boots`.

`system` is evidence near the number (`US 10`, `size 10 US`). Invented `system: "us"` with no nearby US/UK/EU is dropped. Two scales in one phrase (`US 11 / UK 10`) → `system` null, keep the full surface.

### Aliases

Allowed: fold a **model key** onto the official name so later SQL hits (`EUR` → `eu`, `shoes` → `shoe`, model `canonical: "extra small"` → `xs`).

Not allowed: synonym tables that classify open shopper language (`clothing` → apparel, `extra small` on surface → `xs` without model `canonical`). That is the model's job. Color already follows this: `navy` without `canonical: ["blue"]` is dropped.

## Files

| Path | Role |
|---|---|
| `pipeline.py` | Parse, surface check, dispatch, repair merge. |
| `parse.py` | Raw JSON / tagged string → `ParsedItem`. |
| `text.py` | Shared span, digits, comparison ops. |
| `closed.py` | Closed-list accept for color/material. |
| `types.py` | `ConstraintSlot`, `ParsedItem`, `GroundingFailures`, `OR_ATTRIBUTES`. |
| `merge.py` | Split multi-canonical rows; upsert by `(attribute, value)`. |
| `attributes/` | One `ground()` per attribute. |

## Collaboration

```text
llm_nlu / regex payload
    parse_constraint_item
    ground_surface          # cite
    attributes.HANDLERS[name].ground
        color / material    # classify canonical list
        size                # kind + system / letters / mm|in
        budget              # amount + op
        free strings
    merge_or_attribute_slots    # one row per (attribute, value)
    ObservationExtract.slots → SessionState.typed_constraints
    retrieve/from_slots.py  → hard groups prune; soft pairs only score
```

Repair (max three rounds) replaces only ungrounded fields; already-cited slots stay. Later turns upsert the same `(attribute, value)`; a later hard overwrites an earlier soft for that value. Different values of one attribute stay as separate rows.

## Core variables

On `ConstraintSlot`: `attribute`, `surface`, `canonical`, `is_hard`, plus size/budget fields. Writeback stores one row per `(attribute, value)`.

On session: `typed_constraints` (list of slots, including category). `active_constraints` is the cited-string view. Retrieve maps **hard** slots to the exact pool and **soft** slots to preferred scoring.

## Core code

- Dispatch: `ground_constraint_item` in `pipeline.py`
- Per-attribute rules: `attributes/<name>.py`
- Upsert: `merge_or_attribute_slots` / `split_value_rows` in `merge.py`
- Retrieve mapping: `slot_search_values` / `constraint_groups` in `retrieve/from_slots.py`
- Model contract: system prompt in `../llm_nlu.py` (must stay aligned with this README)
