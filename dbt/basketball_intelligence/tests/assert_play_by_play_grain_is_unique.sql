-- One row per play-by-play event, keyed (game_id, action_number,
-- action_id) - the key the ingest deduplicates on (nba_ingest.PBP_KEY).
-- action_number alone is not unique within a game (531 repeats in the
-- local data when this was written), so a test on it would fail on good
-- data; a duplicate of the full key means an append ran twice or the
-- dedup broke, and every shot chart double-counts that event.
-- Grouping, not a unique test on a concatenation, so a null in any part
-- of the key still counts as a value.

select game_id, action_number, action_id, count(*) as dupes
from {{ ref('stg_play_by_play') }}
group by game_id, action_number, action_id
having count(*) > 1
