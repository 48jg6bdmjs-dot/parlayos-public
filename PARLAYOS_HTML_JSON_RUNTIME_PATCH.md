# ParlayOS HTML JSON runtime patch

A focused local patch was made to the user-supplied `parlayos.html` so it reads the four real CHD JSON files from the same HTTP origin:

- `parlayos_mlb_chd.json`
- `parlayos_nfl_chd.json`
- `parlayos_nba_chd.json`
- `parlayos_chd_data.json`

The loader normalizes the current game payloads into the existing HTML contract (`id`, `a`, `b`, team abbreviations, ML, totals, K props, MLB pitcher/lineup/weather fields) and exposes the canonical sport payloads through `window.PARLAYOS_DATA`, `window.PARLAYOS_NFL_DATA`, `window.PARLAYOS_NBA_DATA`, `window.PARLAYOS_CHD_DATA`, `window.PARLAYOS_GAMES`, `window.gamesNFL`, and `window.gamesNBA`.

No model math, weights, calibration, thresholds, odds transforms, or generated JSON values were changed.

The exact patched HTML is supplied as a local test artifact with this PR because the repository's current `parlayos.html` blob is empty and the GitHub text-content interface should not be used to truncate or reconstruct a multi-megabyte generated artifact.
