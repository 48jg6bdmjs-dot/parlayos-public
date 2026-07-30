"""
live_scores.py - Fetches real-time MLB live scores from free MLB Stats API
No ODDS_API_KEY needed, free, updates every 5 min
Creates live_scores.json + injects into parlayos.html + index.html
"""

import requests
import json
import os
from datetime import datetime, timezone

def get_today_mlb_scores():
    """Fetch today's MLB games with linescore from free MLB Stats API"""
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?hydrate=team,linescore,flags,game(content(media(epg)))&date={today}&sportId=1"
    
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        games = []
        dates = data.get('dates', [])
        if not dates:
            print(f"No games for {today}")
            return []
        
        for date_block in dates:
            date_str = date_block.get('date', today)
            for game in date_block.get('games', []):
                try:
                    game_state = game.get('status', {}).get('abstractGameState', '')
                    detailed_state = game.get('status', {}).get('detailedState', '')
                    inning_state = game.get('linescore', {}).get('inningState', '')
                    current_inning = game.get('linescore', {}).get('currentInning', '')
                    
                    # Determine status
                    if game_state == 'Live':
                        status = f"{inning_state} {current_inning}".strip() if current_inning else "LIVE"
                        final = False
                    elif game_state == 'Final':
                        status = "Final"
                        final = True
                    elif game_state == 'Preview':
                        status = game.get('status', {}).get('detailedState', 'Scheduled')
                        final = False
                    else:
                        status = detailed_state or game_state or 'Scheduled'
                        final = game_state == 'Final'
                    
                    teams = game.get('teams', {})
                    away = teams.get('away', {})
                    home = teams.get('home', {})
                    
                    away_team = away.get('team', {}).get('name', 'Away')
                    home_team = home.get('team', {}).get('name', 'Home')
                    away_abbr = away.get('team', {}).get('abbreviation', away_team[:3].upper())
                    home_abbr = home.get('team', {}).get('abbreviation', home_team[:3].upper())
                    
                    away_score = away.get('score', 0)
                    home_score = home.get('score', 0)
                    
                    # Linescore for more detail
                    linescore = game.get('linescore', {})
                    away_runs = linescore.get('teams', {}).get('away', {}).get('runs', away_score) if linescore.get('teams') else away_score
                    home_runs = linescore.get('teams', {}).get('home', {}).get('runs', home_score) if linescore.get('teams') else home_score
                    
                    # Use linescore runs if available
                    if away_runs is not None:
                        away_score = away_runs
                    if home_runs is not None:
                        home_score = home_runs
                    
                    game_id = game.get('gamePk', '')
                    game_time = game.get('gameDate', '')
                    
                    # Format for frontend normalize()
                    formatted = {
                        "id": f"mlb_{game_id}",
                        "lg": "MLB",
                        "date": date_str,
                        "status": status,
                        "inning": f"{inning_state} {current_inning}".strip() if current_inning else status,
                        "final": final,
                        "a": away_team,
                        "b": home_team,
                        "aAbbr": away_abbr[:3].upper(),
                        "bAbbr": home_abbr[:3].upper(),
                        "aName": away_team,
                        "bName": home_team,
                        "aScore": away_score,
                        "bScore": home_score,
                        "teams": [
                            {"name": away_team, "abbr": away_abbr, "logo": away_abbr, "score": away_score},
                            {"name": home_team, "abbr": home_abbr, "logo": home_abbr, "score": home_score}
                        ],
                        "gamePk": game_id,
                        "gameDate": game_time,
                        "abstractGameState": game_state,
                        "detailedState": detailed_state
                    }
                    games.append(formatted)
                except Exception as e:
                    print(f"Error parsing game: {e}")
                    continue
        
        print(f"Fetched {len(games)} games for {today}")
        return games
        
    except Exception as e:
        print(f"Error fetching MLB scores: {e}")
        import traceback
        traceback.print_exc()
        return []

def export_live_scores(games, output_json="live_scores.json", html_path="parlayos.html"):
    """Export to live_scores.json and inject into parlayos.html"""
    
    payload = {
        "games": games,
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(games),
        "source": "MLB Stats API (free)"
    }
    
    # Write live_scores.json
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {output_json} - {len(games)} games")
    
    # Also write to data/ dir for fallback
    os.makedirs("data", exist_ok=True)
    with open("data/live_scores.json", 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    
    # Inject into parlayos.html as window.PARLAYOS_LIVE_SCORES for fallback
    if os.path.exists(html_path):
        try:
            with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                html = f.read()
            
            # Create injection
            injection = f"""
<script id="parlayos-live-scores-injected">
// LIVE SCORES INJECTED {payload['updated']} - {len(games)} games
window.PARLAYOS_LIVE_SCORES = {json.dumps(payload)};
window.LIVE_SCORES_DATA = {json.dumps(payload)};
</script>
"""
            # Remove old injection
            import re
            html = re.sub(r'<script id="parlayos-live-scores-injected">.*?</script>', '', html, flags=re.DOTALL)
            
            # Inject before </body> or at marker
            if '</body>' in html:
                html = html.replace('</body>', injection + '\n</body>')
            else:
                html += injection
            
            with open(html_path, 'w', encoding='utf-8') as out:
                out.write(html)
            print(f"Injected live scores into {html_path}")
            
            # Also update index.html if exists
            if os.path.exists("index.html"):
                with open("index.html", 'r', encoding='utf-8', errors='ignore') as f:
                    idx_html = f.read()
                idx_html = re.sub(r'<script id="parlayos-live-scores-injected">.*?</script>', '', idx_html, flags=re.DOTALL)
                if '</body>' in idx_html:
                    idx_html = idx_html.replace('</body>', injection + '\n</body>')
                else:
                    idx_html += injection
                with open("index.html", 'w', encoding='utf-8') as out:
                    out.write(idx_html)
                print(f"Injected live scores into index.html")
                
        except Exception as e:
            print(f"Error injecting into {html_path}: {e}")
            import traceback
            traceback.print_exc()
    
    return payload

def main():
    print(f"=== Live Scores Fetch - {datetime.now().isoformat()} ===")
    games = get_today_mlb_scores()
    
    if not games:
        print("No games, creating empty payload to clear stale data")
        games = []
    
    payload = export_live_scores(games, "live_scores.json", "parlayos.html")
    
    # Also ensure index.html exists and is updated
    if not os.path.exists("index.html") and os.path.exists("parlayos.html"):
        import shutil
        shutil.copy("parlayos.html", "index.html")
        print("Copied parlayos.html -> index.html")
    
    print(f"=== Done: {len(games)} games, updated {payload['updated']} ===")
    return payload

if __name__ == "__main__":
    main()
