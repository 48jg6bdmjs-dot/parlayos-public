import requests, json, os
from datetime import datetime, timezone

def fetch_live_mlb():
    # MLB Stats API - free, no key, safe to call from backend or frontend
    url = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&hydrate=team,linescore"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        games = []
        for d in data.get('dates', []):
            for g in d.get('games', []):
                # Only include live or recently final
                status = g.get('status', {}).get('detailedState','')
                abstract = g.get('status', {}).get('abstractGameState','')
                is_live = abstract == 'Live' or 'In Progress' in status
                is_final = abstract == 'Final'
                # Include live + final today for context
                if not (is_live or is_final):
                    continue
                teams = g.get('teams', {})
                away = teams.get('away', {})
                home = teams.get('home', {})
                linescore = g.get('linescore', {})
                games.append({
                    "lg": "MLB",
                    "a": away.get('team', {}).get('teamName','Away'),
                    "b": home.get('team', {}).get('teamName','Home'),
                    "aAbbr": away.get('team', {}).get('abbreviation','AWY'),
                    "bAbbr": home.get('team', {}).get('abbreviation','HME'),
                    "aScore": away.get('score',0),
                    "bScore": home.get('score',0),
                    "status": status,
                    "inning": linescore.get('currentInningOrdinal','') + ' ' + linescore.get('inningState','') if linescore.get('currentInningOrdinal') else status,
                    "final": is_final,
                    "date": d.get('date')
                })
        return games
    except Exception as e:
        print(f"Live fetch error: {e}")
        return []

if __name__ == "__main__":
    games = fetch_live_mlb()
    payload = {"games": games, "updated": datetime.now(timezone.utc).isoformat(), "count": len(games)}
    with open("live_scores.json","w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote live_scores.json with {len(games)} games")
    # Also write to public-repo if exists
    if os.path.exists("public-repo"):
        with open("public-repo/live_scores.json","w") as f:
            json.dump(payload, f, indent=2)
