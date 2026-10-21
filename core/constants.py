"""Numbers shared across the pipeline, the models and the dashboard, defined once."""

# The most play-by-play games one ingest run will fetch (one API call each, at
# least 1.5s apart). A busy NBA week has about 100 games, so 120 lets a run
# catch up a whole week with room for some retries, and the first run of a
# season backfills over a few weeks instead of one multi-hour fetch.
PBP_MAX_NEW_GAMES_PER_RUN = 120
