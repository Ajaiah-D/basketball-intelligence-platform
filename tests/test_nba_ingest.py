"""ingestion/nba_ingest.py's run() around the season rollover, with every
nba_api call stubbed out."""

import pandas as pd

from ingestion import nba_ingest


def test_a_season_with_no_games_yet_skips_play_by_play(monkeypatch):
    """From October 1 current_season() is the new season, but it has no
    games until opening night three weeks later. Play-by-play used to raise
    "No play-by-play data could be fetched" on the empty game list, failing
    the weekly refresh every October before tip-off."""
    empty_logs = pd.DataFrame(columns=["GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION"])
    written = []

    def no_call(*args, **kwargs):
        raise AssertionError("play-by-play must not be fetched for an empty season")

    monkeypatch.setattr(nba_ingest, "fetch_player_game_logs", lambda s: empty_logs)
    monkeypatch.setattr(nba_ingest, "fetch_team_game_logs", lambda s: empty_logs)
    monkeypatch.setattr(nba_ingest, "fetch_player_advanced", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_team_advanced", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_schedule", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_players", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_teams", lambda: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_play_by_play", no_call)
    monkeypatch.setattr(nba_ingest, "write_parquet",
                        lambda df, name, season=None: written.append((name, season)))

    nba_ingest.run(["2026-27"], 20, force=True)

    assert ("play_by_play", "2026-27") not in written
    assert ("team_game_logs", "2026-27") in written
