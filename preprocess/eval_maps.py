"""Purpose: closed 20→11 color map and fiber→evaluator material map for alias builders."""

from __future__ import annotations

# HuggingFace colors-normalized base_color labels.
BASE_COLORS = (
    "black",
    "blue",
    "cyan",
    "green",
    "teal",
    "turquoise",
    "indigo",
    "gray",
    "purple",
    "brown",
    "tan",
    "violet",
    "beige",
    "gold",
    "magenta",
    "orange",
    "pink",
    "red",
    "white",
    "yellow",
)

# Evaluator COLOR_RE (grey folds to gray before this map).
EVAL_COLORS = (
    "black",
    "white",
    "blue",
    "red",
    "pink",
    "green",
    "brown",
    "gray",
    "purple",
    "yellow",
    "orange",
)

BASE_TO_EVAL: dict[str, str] = {
    "black": "black",
    "white": "white",
    "blue": "blue",
    "red": "red",
    "pink": "pink",
    "green": "green",
    "brown": "brown",
    "gray": "gray",
    "purple": "purple",
    "yellow": "yellow",
    "orange": "orange",
    "indigo": "blue",
    "cyan": "blue",
    "turquoise": "blue",
    "teal": "green",
    "violet": "purple",
    "magenta": "pink",
    "tan": "brown",
    "beige": "white",
    "gold": "yellow",
}

EVAL_MATERIALS = (
    "cotton",
    "polyester",
    "nylon",
    "leather",
    "wool",
    "spandex",
    "silk",
    "rayon",
    "fabric",
)

# Textile-fiber-database ids / FTC names / common labels → evaluator material.
# Unlisted fibers fall through to fabric in the alias builder.
FIBER_TO_EVAL: dict[str, str] = {
    "cotton": "cotton",
    "pima-cotton": "cotton",
    "organic-cotton": "cotton",
    "polyester": "polyester",
    "recycled-polyester": "polyester",
    "rpet": "polyester",
    "nylon": "nylon",
    "nylon-6": "nylon",
    "nylon-66": "nylon",
    "polyamide": "nylon",
    "wool": "wool",
    "merino": "wool",
    "merino-wool": "wool",
    "cashmere": "wool",
    "mohair": "wool",
    "alpaca": "wool",
    "camel": "wool",
    "camel-hair": "wool",
    "angora": "wool",
    "silk": "silk",
    "spandex": "spandex",
    "elastane": "spandex",
    "lycra": "spandex",
    "rayon": "rayon",
    "viscose": "rayon",
    "modal": "rayon",
    "lyocell": "rayon",
    "tencel": "rayon",
    "cupro": "rayon",
    "cuprammonium-rayon": "rayon",
    "bamboo": "rayon",
    "leather": "leather",
}

# Non-fiber and misspelling aliases merged into material_aliases.json.
LEATHER_ALIASES: dict[str, str] = {
    "leather": "leather",
    "cowhide": "leather",
    "suede": "leather",
    "nubuck": "leather",
    "faux leather": "leather",
    "vegan leather": "leather",
    "pu leather": "leather",
    "patent leather": "leather",
    "bonded leather": "leather",
    "microfiber leather": "leather",
}

MATERIAL_TYPOS: dict[str, str] = {
    "spandx": "spandex",
    "spandex": "spandex",
    "elastan": "spandex",
    "lycra": "spandex",
    "polyster": "polyester",
    "polyesther": "polyester",
    "polyeseter": "polyester",
    "coton": "cotton",
    "nlyon": "nylon",
    "viscose": "rayon",
    "tencel": "rayon",
}

SPECIFIC_MATERIALS = frozenset(EVAL_MATERIALS) - {"fabric"}
