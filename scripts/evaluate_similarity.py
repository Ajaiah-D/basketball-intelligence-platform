"""Score the Similar players model against the real warehouse and write
docs/similarity-evaluation.md.

Three checks (dashboard/lib/similarity_eval.py explains them):

1. Self-match: does a player's season-one profile find his own season two
   among everyone's? Run for several pairs of seasons, for the first
   version (the baseline), the model before shot data and the current
   model, with and without the stable stats (height, role size) that make
   the test easy.
2. Known pairs: players who play the same way should be near each other,
   and players who only share box-score output should not.
3. A sanity panel: each named player's closest matches before shot data
   and now, to read by eye.

It also scores the other weightings tried for the shot diet and play types
(WEIGHTINGS), on self-match and known pairs together, so the choice is on
record.

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
# one with part of it, the rest with all of it. 2017-18 to 2018-19 and
# 2024-25 to 2025-26 have play types on both sides; 2023-24 has too few
# players with complete play types, so its pairs go without them.
PAIRS = [
    ("2005-06", "2006-07"),
    ("2014-15", "2015-16"),
    ("2017-18", "2018-19"),
    ("2022-23", "2023-24"),
    ("2023-24", "2024-25"),
    ("2024-25", "2025-26"),
]

BEFORE = E.block_model("Before shot data", E.BEFORE_SHOT_DATA)
CURRENT = E.block_model("Current model")
MODELS = [
    E.LEGACY,
    BEFORE,
    CURRENT,
    E.block_model("Current, play types not shrunk", prior=0.0),
    E.block_model("Current, no height", E.without(features=["height_inches"])),
    E.block_model(
        "Current, no height or role", E.without(features=["height_inches"], blocks=["Role"])
    ),
]

PANEL_SEASONS = ["2025-26", "2026-27"]

# Judgement calls, so they sit beside self-match, never in its place.
KNOWN_PAIRS = [
    E.Pair("Nikola Jokić", "Alperen Sengun", True, "post-up hub bigs who pass and screen"),
    E.Pair("Domantas Sabonis", "Nikola Jokić", True, "hub bigs: handoffs, screens, elbow passing"),
    E.Pair("Rudy Gobert", "Jarrett Allen", True, "rim-running centers who don't shoot"),
    E.Pair("Brook Lopez", "Myles Turner", True, "stretch centers who protect the rim"),
    E.Pair("Victor Wembanyama", "Chet Holmgren", True, "long shot-blockers who shoot threes"),
    E.Pair("Bam Adebayo", "Evan Mobley", True, "switchable bigs who pass on the roll"),
    E.Pair("Mitchell Robinson", "Steven Adams", True, "offensive rebounders and screeners"),
    E.Pair("Giannis Antetokounmpo", "Zion Williamson", True, "downhill rim attackers, few threes"),
    E.Pair("Luka Dončić", "James Harden", True, "step-back, pick-and-roll lead creators"),
    E.Pair("Derrick White", "Jrue Holiday", True, "3-and-D combo guards"),
    E.Pair("Herbert Jones", "Dyson Daniels", True, "disruptive wing defenders"),
    E.Pair(
        "Nikola Jokić", "Jalen Johnson", False, "same output, not the post, screens or matchups"
    ),
    E.Pair("Jayson Tatum", "Cade Cunningham", False, "high-volume shooting wing vs lead guard"),
    E.Pair("Rudy Gobert", "Brook Lopez", False, "both protect the rim, score in opposite places"),
]
PAIR_MODELS = [E.LEGACY, BEFORE, CURRENT]


def _scoring_blocks(diet: float, play: float, keep_3pa_rate: bool = False) -> tuple[S.Block, ...]:
    """S.BLOCKS with the Shot diet and Play type weights set (and, if asked,
    the box-score 3PA rate kept in Shot diet)."""
    out = []
    for b in S.BLOCKS:
        if b.name == "Shot diet":
            extra = {"three_point_attempt_rate": 1.0} if keep_3pa_rate else {}
            out.append(S.Block(b.name, diet, {**b.features, **extra}))
        elif b.name == "Play type":
            out.append(S.Block(b.name, play, b.features))
        else:
            out.append(b)
    return tuple(out)


def _one_scoring_block() -> tuple[S.Block, ...]:
    """Shot diet and play types as one Scoring block of weight 3."""
    diet, play = S.BLOCKS[0], S.BLOCKS[1]
    return (S.Block("Scoring", 3.0, {**diet.features, **play.features}), *S.BLOCKS[2:])


# The weightings tried for the new data. Each keeps the other blocks as they
# are; the one marked current is the model.
WEIGHTINGS = [
    BEFORE,
    E.block_model("One Scoring block, weight 3, not shrunk", _one_scoring_block(), prior=0.0),
    E.block_model("Shot diet 1.5 + Play type 1.5, not shrunk", prior=0.0),
    E.block_model("Shot diet 1.5 + Play type 1.5, prior 50", prior=50.0),
    E.block_model("Shot diet 1.5 + Play type 1.5, prior 100 (current)"),
    E.block_model("Shot diet 1.5 + Play type 1.5, prior 200", prior=200.0),
    E.block_model(
        "Same, 3PA rate kept in Shot diet, prior 100", _scoring_blocks(1.5, 1.5, keep_3pa_rate=True)
    ),
    E.block_model("Shot diet 2 + Play type 2, not shrunk", _scoring_blocks(2.0, 2.0), prior=0.0),
    E.block_model("Shot diet 2 + Play type 2, prior 100", _scoring_blocks(2.0, 2.0)),
]
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


def model_top(p: pd.DataFrame, model: E.Model, player_id: int, n: int) -> list[str]:
    """`model`'s top `n` for one player, closest first (ties to the lower
    player_id, as the page does)."""
    emb = model.embed(p, None)
    me = int((emb.player_ids == player_id).argmax())
    scores = E.closeness(emb.matrix[[me]], emb.matrix, model.metric)[0]
    others = sorted(
        (i for i in range(len(scores)) if i != me), key=lambda i: (-scores[i], emb.player_ids[i])
    )
    return [str(p["player_name"].iloc[i]) for i in others[:n]]


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


def pairs_held(model: E.Model, pools: dict[str, pd.DataFrame]) -> tuple[int, int]:
    """How many of the known pairs `model` holds over PANEL_SEASONS, and of
    how many (a pair with a player under the floor doesn't count)."""
    held = total = 0
    for season in PANEL_SEASONS:
        p = pools[season]
        ids = dict(zip(p["player_name"], p["player_id"], strict=True))
        for pair in KNOWN_PAIRS:
            if pair.player in ids and pair.other in ids:
                rank = E.rank_of(p, model, int(ids[pair.player]), int(ids[pair.other]))
                held += E.pair_holds(pair, rank)
                total += 1
    return held, total


def weightings_table() -> list[str]:
    seasons = {*PANEL_SEASONS, *(s for pair in PAIRS for s in pair)}
    pools = {s: pool(s) for s in seasons}
    lines = [
        "| Weighting | " + " | ".join(f"{a} to {b}" for a, b in PAIRS) + " | Known pairs held |",
        "|---|" + "---|" * (len(PAIRS) + 1),
    ]
    for model in WEIGHTINGS:
        cells = []
        for first, second in PAIRS:
            s = E.summarize(E.self_match(pools[first], pools[second], model), len(pools[second]))
            cells.append(f"{s.top1:.0%} / {s.top5:.0%}")
        held, total = pairs_held(model, pools)
        lines.append(f"| {model.name} | {' | '.join(cells)} | {held} of {total} |")
    return lines


def known_pairs_tables() -> list[str]:
    lines: list[str] = []
    held = {m.name: [0, 0] for m in PAIR_MODELS}
    for season in PANEL_SEASONS:
        p = pool(season)
        ids = dict(zip(p["player_name"], p["player_id"], strict=True))
        lines += [
            f"### {season}",
            "",
            "| On his page | Other | Want | Why | "
            + " | ".join(m.name for m in PAIR_MODELS)
            + " |",
            "|---|---|---|---|" + "---|" * len(PAIR_MODELS),
        ]
        for pair in KNOWN_PAIRS:
            want = f"top {E.MATCH_TOP}" if pair.should_match else f"not top {E.AVOID_TOP}"
            if pair.player not in ids or pair.other not in ids:
                cells = ["under the floor"] * len(PAIR_MODELS)
            else:
                cells = []
                for m in PAIR_MODELS:
                    rank = E.rank_of(p, m, int(ids[pair.player]), int(ids[pair.other]))
                    ok = E.pair_holds(pair, rank)
                    held[m.name][0] += ok
                    held[m.name][1] += 1
                    cells.append(f"{rank} {'(yes)' if ok else '(no)'}")
            lines.append(
                f"| {pair.player} | {pair.other} | {want} | {pair.why} | {' | '.join(cells)} |"
            )
        lines.append("")
    lines += [f"- **{name}**: {h} of {n} pairs hold" for name, (h, n) in held.items()]
    return lines


def panel_tables() -> list[str]:
    lines: list[str] = []
    for season in PANEL_SEASONS:
        p = pool(season)
        lines += [
            f"### {season} ({len(p)} players, {minutes_floor(advanced.similarity_pool(season))}+"
            " minutes)",
            "",
            "| Player | Before shot data | Current model |",
            "|---|---|---|",
        ]
        for name in PANEL:
            hit = p[p["player_name"] == name]
            if hit.empty:
                lines.append(f"| {name} | under the floor | under the floor |")
                continue
            pid = int(hit["player_id"].iloc[0])
            new = S.rank_similar(p, pid, 0, PANEL_N).ranked["player_name"].tolist()
            old = model_top(p, BEFORE, pid, PANEL_N)
            lines.append(f"| {name} | {', '.join(old)} | {', '.join(new)} |")
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
        f"Play-type shares are shrunk toward the pool's average by {S.PLAY_TYPE_PRIOR:g}",
        "possessions of it (ten per play type, the NBA's own floor for listing one).",
        "Shot zones exist from 1996-97 and play types from 2015-16; a season without",
        "them goes without those features. 2023-24's play types are missing for too",
        "many players (the NBA's answer lacks rows), so that season goes without them.",
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
        "## Known pairs",
        "",
        "Rank of the other player on his page (1 = closest). A pair that should match",
        f"holds in the top {E.MATCH_TOP}; one that shouldn't holds outside the top",
        f"{E.AVOID_TOP}. The pairs are judgement calls and count beside self-match.",
        "",
        *known_pairs_tables(),
        "",
        "## Weightings tried",
        "",
        "Self-match (found himself first / in the top 5) and known pairs for each",
        "weighting tried for the shot diet and play types. Pick on both: self-match",
        "rewards stable stats, the pairs are judgement calls.",
        "",
        *weightings_table(),
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
