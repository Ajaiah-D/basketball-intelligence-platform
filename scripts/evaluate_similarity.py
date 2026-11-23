"""Score the Similar players model against the real warehouse and write
docs/similarity-evaluation.md.

Two checks (dashboard/lib/similarity_eval.py explains them):

1. Self-match: does a player's season-one profile find his own season two
   among everyone's? Run for several pairs of seasons, for the first
   version (the baseline) and the current model, with and without the
   stable stats (height, role size) that make the test easy.
2. A sanity panel: each named player's closest matches under both models,
   to read by eye.

Run from the repo root:  python scripts/evaluate_similarity.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# The data layer caches through Streamlit, which warns when no app runs.
logging.getLogger("streamlit").setLevel(logging.ERROR)

from dashboard.lib import similarity as S  # noqa: E402
from dashboard.lib import similarity_eval as E  # noqa: E402
from dashboard.lib.advanced_metrics import minutes_floor  # noqa: E402
from dashboard.lib.data import advanced  # noqa: E402

REPORT = PROJECT_ROOT / "docs" / "similarity-evaluation.md"

# (season one, season two). One pair before tracking defense (2013-14),
# one with part of it, the rest with all of it.
PAIRS = [
    ("2005-06", "2006-07"),
    ("2014-15", "2015-16"),
    ("2022-23", "2023-24"),
    ("2023-24", "2024-25"),
    ("2024-25", "2025-26"),
]

MODELS = [
    E.LEGACY,
    E.block_model("Current model"),
    E.block_model("Current, no height", E.without(features=["height_inches"])),
    E.block_model(
        "Current, no height or role", E.without(features=["height_inches"], blocks=["Role"])
    ),
]

PANEL_SEASONS = ["2025-26", "2026-27"]
PANEL = [
    "Jayson Tatum",
    "Nikola Jokić",
    "Stephen Curry",
    "Giannis Antetokounmpo",
    "Rudy Gobert",
    "Jalen Brunson",
    "Herbert Jones",
    "Draymond Green",
    "Mikal Bridges",
    "Victor Wembanyama",
    "Shai Gilgeous-Alexander",
    "Derrick White",
]
PANEL_N = 8


def pool(season: str) -> pd.DataFrame:
    """The season's players over the page's minutes floor."""
    df = advanced.similarity_pool(season)
    return S.qualified(df, minutes_floor(df)).reset_index(drop=True)


def legacy_top(p: pd.DataFrame, player_id: int, n: int) -> list[str]:
    """The first version's top `n` for one player."""
    emb = E.LEGACY.embed(p, None)
    me = int((emb.player_ids == player_id).argmax())
    scores = E.closeness(emb.matrix[[me]], emb.matrix, "cosine")[0]
    order = [i for i in scores.argsort()[::-1] if i != me][:n]
    return [str(p["player_name"].iloc[i]) for i in order]


def self_match_table() -> list[str]:
    lines = [
        "| Seasons | Model | Players | Found himself 1st | In top 5 | Median rank |",
        "|---|---|---|---|---|---|",
    ]
    pools = {s: pool(s) for pair in PAIRS for s in pair}
    for first, second in PAIRS:
        for model in MODELS:
            ranks = E.self_match(pools[first], pools[second], model)
            s = E.summarize(ranks, len(pools[second]))
            lines.append(
                f"| {first} to {second} | {model.name} | {s.players} of {s.candidates} "
                f"| {s.top1:.0%} | {s.top5:.0%} | {s.median_rank:g} |"
            )
    return lines


def panel_tables() -> list[str]:
    lines: list[str] = []
    for season in PANEL_SEASONS:
        p = pool(season)
        lines += [
            f"### {season} ({len(p)} players, {minutes_floor(advanced.similarity_pool(season))}+"
            " minutes)",
            "",
            "| Player | First version | Current model |",
            "|---|---|---|",
        ]
        for name in PANEL:
            hit = p[p["player_name"] == name]
            if hit.empty:
                lines.append(f"| {name} | under the floor | under the floor |")
                continue
            pid = int(hit["player_id"].iloc[0])
            new = S.rank_similar(p, pid, 0, PANEL_N).ranked["player_name"].tolist()
            lines.append(
                f"| {name} | {', '.join(legacy_top(p, pid, PANEL_N))} | {', '.join(new)} |"
            )
        lines.append("")
    return lines


def main() -> None:
    weights = [
        f"- **{b.name}** (weight {b.weight:g}): "
        + ", ".join(f"{S.FEATURE_LABELS[f]} ({w:g})" for f, w in b.features.items())
        for b in S.BLOCKS
    ]
    report = [
        "# Similar players: evaluation",
        "",
        "Written by `scripts/evaluate_similarity.py` against the full local warehouse.",
        "The method is in `dashboard/lib/similarity.py`, the tests in",
        "`dashboard/lib/similarity_eval.py`.",
        "",
        "## The current model's blocks",
        "",
        *weights,
        "",
        "## Self-match",
        "",
        "Each player's season-one profile is compared with every season-two profile;",
        "the closer his own season two ranks, the better the model captures a stable",
        "style. Height and role size are stable by nature, so the rows without them",
        "show how much of the result is style.",
        "",
        *self_match_table(),
        "",
        "## Sanity panel",
        "",
        "Each player's closest matches, closest first. Read by eye: no number says",
        "these are right.",
        "",
        *panel_tables(),
    ]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
