# ParlayOS HTML JSON Runtime Test

The supplied `parlayos.html` is intended to load these real runtime JSON files from the same HTTP origin:

- `parlayos_mlb_chd.json`
- `parlayos_nfl_chd.json`
- `parlayos_nba_chd.json`
- `parlayos_chd_data.json`

The HTML loader normalizes each game into the dashboard's existing contract and exposes:

- `window.PARLAYOS_DATA` (MLB)
- `window.PARLAYOS_NFL_DATA` (NFL)
- `window.PARLAYOS_NBA_DATA` (NBA)
- `window.PARLAYOS_CHD_DATA` (all four payloads)
- `window.PARLAYOS_GAMES`
- `window.gamesNFL`
- `window.gamesNBA`

No model math, weights, calibration, odds transformations, thresholds, or generated JSON values are changed.

Local test:

```bash
python3 -m http.server 8000
```

Serve the HTML and the four real JSONs from the same directory, then open the HTML over HTTP.
