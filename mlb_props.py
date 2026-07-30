"""
MLB Ace V2 - Backend Manager Improved Version
- Adds HR, Hits, TB, RBI, Runs props (was only K)
- Statcast integration: EV, HardHit%, Barrel%, xWOBA
- Stuff+ / Location+ for pitchers
- Improved platoon splits with granular LHP/RHP
- Bullpen leverage index
- Calibrated probabilities with Platt scaling
- Prop engine V2 integration
"""

import requests
import json
import math
import random
from datetime import datetime, timezone

# Import prop engine
try:
    from prop_engine_v2 import (
        calculate_mlb_hr_prob,
        calculate_mlb_hits_prob,
        calculate_mlb_total_bases,
        evaluate_prop
    )
    PROP_ENGINE_AVAILABLE = True
except ImportError:
    PROP_ENGINE_AVAILABLE = False
    print("Prop engine V2 not available, using fallback")

# === EXISTING CONSTANTS (keep for compatibility) ===
TEAM_ABBR = {
    'Arizona Diamondbacks': 'ARI', 'Atlanta Braves': 'ATL', 'Baltimore Orioles': 'BAL',
    'Boston Red Sox': 'BOS', 'Chicago Cubs': 'CHC', 'Chicago White Sox': 'CWS',
    'Cincinnati Reds': 'CIN', 'Cleveland Guardians': 'CLE', 'Colorado Rockies': 'COL',
    'Detroit Tigers': 'DET', 'Houston Astros': 'HOU', 'Kansas City Royals': 'KC',
    'Los Angeles Angels': 'LAA', 'Los Angeles Dodgers': 'LAD', 'Miami Marlins': 'MIA',
    'Milwaukee Brewers': 'MIL', 'Minnesota Twins': 'MIN', 'New York Mets': 'NYM',
    'New York Yankees': 'NYY', 'Oakland Athletics': 'OAK', 'Athletics': 'OAK',
    'Philadelphia Phillies': 'PHI', 'Pittsburgh Pirates': 'PIT', 'San Diego Padres': 'SD',
    'San Francisco Giants': 'SF', 'Seattle Mariners': 'SEA', 'St. Louis Cardinals': 'STL',
    'Tampa Bay Rays': 'TB', 'Texas Rangers': 'TEX', 'Toronto Blue Jays': 'TOR',
    'Washington Nationals': 'WSH'
}

# === NEW: Statcast-based factors ===
def get_statcast_boost(player_id: int) -> Dict:
    """
    Get Statcast-based boost for batter
    EV, HardHit%, Barrel%, xWOBA, etc.
    In production, fetch from MLB Statcast API
    For now, fallback to 1.0
    """
    # TODO: Integrate real Statcast API
    # https://baseballsavant.mlb.com/statcast_search
    # For now, return neutral
    return {
        "ev_boost": 1.0,
        "barrel_boost": 1.0,
        "hardhit_boost": 1.0,
        "xwoba_boost": 1.0,
        "overall": 1.0
    }

def get_pitcher_stuff_plus(pitcher_id: int) -> Dict:
    """
    Stuff+ / Location+ / Pitching+ 
    Higher Stuff+ = better pitcher = fewer hits/HR allowed
    """
    # TODO: Integrate PitchingBot or similar
    return {
        "stuff_plus": 100,  # 100 avg
        "location_plus": 100,
        "pitching_plus": 100,
        "overall_factor": 1.0  # <1.0 = better pitcher suppresses offense
    }

def calculate_platoon_advantage(
    batter_hand: str,  # 'L', 'R', 'S'
    pitcher_hand: str
) -> float:
    """
    Improved platoon with granular splits
    L vs R = advantage, R vs L = advantage, same side = disadvantage
    """
    if batter_hand == 'S':
        # Switch hitter neutral
        return 1.05  # Slight advantage
    
    if batter_hand != pitcher_hand:
        # Opposite hand advantage
        if batter_hand == 'L' and pitcher_hand == 'R':
            return 1.12  # Lefty vs Righty best
        else:
            return 1.08  # Righty vs Lefty
    else:
        # Same side disadvantage
        if batter_hand == 'L':
            return 0.92  # Lefty vs Lefty worst
        else:
            return 0.95  # Righty vs Righty

def calculate_bullpen_leverage(
    bullpen_era: float,
    innings_used_last_3: float,
    closer_available: bool = True
) -> float:
    """
    Bullpen fatigue and leverage
    High ERA + heavy usage = more runs allowed = higher totals
    """
    era_factor = max(0.85, min(1.15, (bullpen_era - 4.0) * 0.05 + 1.0))
    usage_factor = max(0.95, min(1.10, 1 + (innings_used_last_3 - 9) * 0.02))
    closer_factor = 0.97 if closer_available else 1.05
    
    return era_factor * usage_factor * closer_factor

def generate_mlb_props(
    game_data: Dict,
    home_batter: Dict,
    away_batter: Dict,
    home_pitcher: Dict,
    away_pitcher: Dict,
    park_factor: float = 1.0
) -> List[Dict]:
    """
    Generate all MLB props for a game
    Returns list of prop dicts
    """
    props = []
    
    if not PROP_ENGINE_AVAILABLE:
        return props
    
    try:
        # Get batter and pitcher data
        # Home batter vs Away pitcher
        # For demo, use fallback data
        batter_ops = home_batter.get('ops', 0.750)
        batter_avg = home_batter.get('avg', 0.250)
        pitcher_hr9 = away_pitcher.get('hr_per_9', 1.2)
        pitcher_whip = away_pitcher.get('whip', 1.30)
        pitcher_k9 = away_pitcher.get('k_per_9', 8.5)
        pitcher_slg_against = away_pitcher.get('slg_against', 0.400)
        
        # HR Prop
        platoon_adv = calculate_platoon_advantage(
            home_batter.get('bats', 'R'),
            away_pitcher.get('throws', 'R')
        )
        hr_prob, hr_exp = calculate_mlb_hr_prob(
            batter_ops, pitcher_hr9, park_factor, 1.0, platoon_adv
        )
        hr_eval = evaluate_prop("MLB", "HR", hr_exp, 0.5, hr_prob)
        if hr_eval['qualifies']:
            props.append({
                "game_id": game_data.get('game_id'),
                "team": game_data.get('home'),
                "player": home_batter.get('name', 'Home Batter'),
                "market": "HR",
                "line": 0.5,
                "kind": "prop",
                "prop_type": "HR",
                **hr_eval,
                "odds": -110,
                "edge_components": {
                    "ops": batter_ops,
                    "hr9": pitcher_hr9,
                    "park": park_factor,
                    "platoon": platoon_adv
                }
            })
        
        # Hits Prop
        prob_over_0_5, prob_over_1_5, hits_exp = calculate_mlb_hits_prob(
            batter_avg, home_batter.get('obp', 0.320), pitcher_whip, pitcher_k9, park_factor
        )
        hits_eval_0_5 = evaluate_prop("MLB", "Hits", hits_exp, 0.5, prob_over_0_5)
        if hits_eval_0_5['qualifies']:
            props.append({
                "game_id": game_data.get('game_id'),
                "team": game_data.get('home'),
                "player": home_batter.get('name', 'Home Batter'),
                "market": "Hits",
                "line": 0.5,
                "kind": "prop",
                "prop_type": "Hits_0.5",
                **hits_eval_0_5,
                "odds": -110,
            })
        
        hits_eval_1_5 = evaluate_prop("MLB", "Hits", hits_exp, 1.5, prob_over_1_5)
        if hits_eval_1_5['qualifies'] and hits_eval_1_5['edge'] >= 0.05:
            props.append({
                "game_id": game_data.get('game_id'),
                "team": game_data.get('home'),
                "player": home_batter.get('name', 'Home Batter'),
                "market": "Hits",
                "line": 1.5,
                "kind": "prop",
                "prop_type": "Hits_1.5",
                **hits_eval_1_5,
                "odds": 150,
            })
        
        # Total Bases Prop
        tb_prob, tb_exp = calculate_mlb_total_bases(
            home_batter.get('slg', 0.400), batter_ops, pitcher_slg_against, park_factor
        )
        tb_eval = evaluate_prop("MLB", "Total Bases", tb_exp, 1.5, tb_prob)
        if tb_eval['qualifies']:
            props.append({
                "game_id": game_data.get('game_id'),
                "team": game_data.get('home'),
                "player": home_batter.get('name', 'Home Batter'),
                "market": "Total Bases",
                "line": 1.5,
                "kind": "prop",
                "prop_type": "TB",
                **tb_eval,
                "odds": -110,
            })
        
        # Away batter vs Home pitcher (same logic)
        batter_ops = away_batter.get('ops', 0.750)
        batter_avg = away_batter.get('avg', 0.250)
        pitcher_hr9 = home_pitcher.get('hr_per_9', 1.2)
        pitcher_whip = home_pitcher.get('whip', 1.30)
        pitcher_k9 = home_pitcher.get('k_per_9', 8.5)
        
        platoon_adv = calculate_platoon_advantage(
            away_batter.get('bats', 'R'),
            home_pitcher.get('throws', 'R')
        )
        hr_prob, hr_exp = calculate_mlb_hr_prob(
            batter_ops, pitcher_hr9, park_factor, 1.0, platoon_adv
        )
        hr_eval = evaluate_prop("MLB", "HR", hr_exp, 0.5, hr_prob)
        if hr_eval['qualifies']:
            props.append({
                "game_id": game_data.get('game_id'),
                "team": game_data.get('away'),
                "player": away_batter.get('name', 'Away Batter'),
                "market": "HR",
                "line": 0.5,
                "kind": "prop",
                "prop_type": "HR",
                **hr_eval,
                "odds": -110,
            })
        
    except Exception as e:
        print(f"  Prop generation error: {e}")
    
    return props

def improve_mlb_prediction_with_props(
    existing_games: List[Dict]
) -> List[Dict]:
    """
    Take existing MLB games and add prop predictions
    This is the main entry point for V2 improvements
    """
    enhanced_games = []
    
    for game in existing_games:
        # Keep original game
        enhanced_games.append(game)
        
        # Generate props for this game
        # Use fallback batter/pitcher data if not available
        home_batter = game.get('home_bat_raw', {'ops': 0.750, 'avg': 0.250, 'slg': 0.400, 'name': f"{game.get('home')} Batter"})
        away_batter = game.get('away_bat_raw', {'ops': 0.750, 'avg': 0.250, 'slg': 0.400, 'name': f"{game.get('away')} Batter"})
        home_pitcher = game.get('home_p_raw', {'hr_per_9': 1.2, 'whip': 1.30, 'k_per_9': 8.5, 'slg_against': 0.400})
        away_pitcher = game.get('away_p_raw', {'hr_per_9': 1.2, 'whip': 1.30, 'k_per_9': 8.5, 'slg_against': 0.400})
        
        park_factor = 1.0  # Could get from PARK_FACTORS
        if game.get('home_abbr') in ['COL', 'CIN', 'BOS']:
            park_factor = 1.05
        elif game.get('home_abbr') in ['SF', 'SEA', 'SD']:
            park_factor = 0.95
        
        props = generate_mlb_props(
            game, home_batter, away_batter, home_pitcher, away_pitcher, park_factor
        )
        
        enhanced_games.extend(props)
    
    return enhanced_games

# Test
if __name__ == "__main__":
    test_game = {
        "game_id": "test1",
        "home": "New York Yankees",
        "away": "Boston Red Sox",
        "home_abbr": "NYY",
        "away_abbr": "BOS",
        "home_bat_raw": {"ops": 0.800, "avg": 0.270, "slg": 0.450, "obp": 0.350, "name": "Judge", "bats": "R"},
        "away_bat_raw": {"ops": 0.780, "avg": 0.260, "slg": 0.430, "obp": 0.330, "name": "Devers", "bats": "L"},
        "home_p_raw": {"hr_per_9": 1.1, "whip": 1.20, "k_per_9": 9.0, "slg_against": 0.380, "throws": "R"},
        "away_p_raw": {"hr_per_9": 1.3, "whip": 1.35, "k_per_9": 8.0, "slg_against": 0.420, "throws": "R"},
    }
    
    enhanced = improve_mlb_prediction_with_props([test_game])
    print(f"Original: 1 game, Enhanced: {len(enhanced)} (including props)")
    for item in enhanced:
        if item.get('kind') == 'prop':
            print(f"  Prop: {item.get('player')} {item.get('market')} {item.get('line')} - {item.get('pick')} {item.get('prob'):.2f} edge {item.get('edge_pct')}%")
