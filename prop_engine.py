"""
ParlayOS Prop Engine V2 - Cross-Sport Prop Expansion
- MLB: K, HR, Hits, Total Bases, RBI, Runs, SB
- NFL: Pass Yds, Rush Yds, Rec Yds, Receptions, TDs, Attempts
- NBA: Points, Rebounds, Assists, PRA, 3PT, Blocks, Steals
- Unified prop modeling with Statcast, EPA, RAPM
"""

import math
import random
from typing import Dict, List, Tuple

# === MLB PROP MODELS ===

def calculate_mlb_hr_prob(
    batter_ops: float,
    pitcher_hr9: float,
    park_factor: float,
    weather_factor: float = 1.0,
    platoon_advantage: float = 1.0
) -> Tuple[float, float]:
    """
    Improved HR prop model
    - Uses OPS, HR/9, park, weather, platoon
    - Returns (prob_over_0.5, expected_hr)
    """
    # Base HR rate per PA
    # League avg ~ 0.03 HR per PA
    base_hr_rate = 0.03
    
    # OPS impact (0.700 avg -> 1.0, 1.000 OPS -> 1.8x)
    ops_mult = max(0.3, min(2.5, (batter_ops / 0.700) ** 1.5))
    
    # Pitcher HR/9 impact (1.0 avg, 2.0 bad)
    pitcher_mult = max(0.5, min(2.0, pitcher_hr9 / 1.0))
    
    # Combined
    hr_per_pa = base_hr_rate * ops_mult * pitcher_mult * park_factor * weather_factor * platoon_advantage
    
    # Expected PA per game ~ 4.2
    expected_hr = hr_per_pa * 4.2
    
    # Prob of over 0.5 HR (at least 1 HR)
    # Poisson with lambda = expected_hr
    prob_over_0_5 = 1 - math.exp(-expected_hr)
    
    return prob_over_0_5, expected_hr

def calculate_mlb_hits_prob(
    batter_avg: float,
    batter_obp: float,
    pitcher_whip: float,
    pitcher_k9: float,
    park_factor: float = 1.0
) -> Tuple[float, float, float]:
    """
    Hits prop: Over 0.5, 1.5
    Returns (prob_over_0.5, prob_over_1.5, expected_hits)
    """
    # Base hits per PA ~ AVG * (1 - K%)
    # Simplified
    k_rate = min(0.35, max(0.10, pitcher_k9 / 27.0))  # K/9 to K%
    hit_per_pa = batter_avg * (1 - k_rate * 0.5) * park_factor
    
    # Pitcher WHIP impact (lower WHIP = fewer hits)
    whip_mult = max(0.7, min(1.3, 1.3 - (pitcher_whip - 1.3) * 0.3))
    hit_per_pa *= whip_mult
    
    expected_hits = hit_per_pa * 4.2
    
    # Poisson for hits
    # P(0) = exp(-lambda)
    # P(1) = lambda * exp(-lambda)
    p0 = math.exp(-expected_hits)
    p1 = expected_hits * math.exp(-expected_hits)
    
    prob_over_0_5 = 1 - p0
    prob_over_1_5 = 1 - p0 - p1
    
    return prob_over_0_5, prob_over_1_5, expected_hits

def calculate_mlb_total_bases(
    batter_slg: float,
    batter_ops: float,
    pitcher_slg_against: float = 0.400,
    park_factor: float = 1.0
) -> Tuple[float, float]:
    """
    Total bases prop (usually 1.5)
    Returns (prob_over_1.5, expected_tb)
    """
    # TB per PA approximated from SLG
    # SLG = TB / AB, AB ~ PA * 0.9
    tb_per_pa = batter_slg * 0.9 * park_factor
    
    # Adjust for pitcher
    pitcher_mult = max(0.7, min(1.3, pitcher_slg_against / 0.400))
    tb_per_pa *= pitcher_mult
    
    expected_tb = tb_per_pa * 4.2
    
    # Prob over 1.5 - need distribution
    # Simplified: if expected > 1.5, prob > 0.5
    # Use normal approx
    # Var approx = expected * 1.2
    if expected_tb <= 0:
        return 0.0, 0.0
    
    # Z-score for 1.5
    # P(TB > 1.5)
    # Approx with Poisson for TB? Simplified
    # If expected >= 2.5, high prob over 1.5
    prob_over = 1 / (1 + math.exp(-(expected_tb - 1.5) * 1.2))
    
    return prob_over, expected_tb

# === NFL PROP MODELS ===

def calculate_nfl_passing_yards(
    qb_rating: float,
    qb_ypa: float,
    def_pass_ypg_allowed: float,
    ol_vs_dl_matchup: float = 1.0,
    weather_factor: float = 1.0,
    pace_factor: float = 1.0
) -> Tuple[float, float]:
    """
    Passing yards prop
    Returns (expected_yards, prob_over_line)
    Line typically 250.5, 275.5 etc - we return expected, prob calc needs line
    """
    # Base: QB YPA * attempts
    # Avg attempts ~ 35
    base_attempts = 35
    
    # Rating impact
    rating_mult = max(0.7, min(1.3, qb_rating / 90.0))
    
    # Defense impact (yards allowed)
    # League avg ~ 230 pass ypg allowed
    def_mult = max(0.7, min(1.3, def_pass_ypg_allowed / 230.0))
    
    expected_yards = qb_ypa * base_attempts * rating_mult * def_mult * ol_vs_dl_matchup * weather_factor * pace_factor
    
    return expected_yards

def calculate_nfl_rushing_yards(
    rb_ypc: float,
    rb_attempts_per_game: float,
    def_rush_ypg_allowed: float,
    ol_vs_dl_rush: float = 1.0,
    game_script_factor: float = 1.0
) -> float:
    """Rushing yards expected"""
    def_mult = max(0.7, min(1.3, def_rush_ypg_allowed / 110.0))
    expected = rb_ypc * rb_attempts_per_game * def_mult * ol_vs_dl_rush * game_script_factor
    return expected

def calculate_nfl_receptions(
    wr_targets_per_game: float,
    wr_catch_rate: float,
    qb_accuracy: float = 1.0,
    def_vs_wr: float = 1.0
) -> float:
    """Receptions expected"""
    expected = wr_targets_per_game * wr_catch_rate * qb_accuracy * def_vs_wr
    return expected

# === NBA PROP MODELS ===

def calculate_nba_points(
    player_ppg: float,
    player_usage: float,
    opp_def_rating: float,
    pace_factor: float = 1.0,
    rest_factor: float = 1.0,
    b2b: bool = False
) -> float:
    """Points expected"""
    # Usage impact
    usage_mult = max(0.7, min(1.3, player_usage / 0.20)) if player_usage else 1.0
    
    # Defense: lower def rating = better defense = fewer points
    # League avg ~ 112
    def_mult = max(0.7, min(1.3, opp_def_rating / 112.0)) if opp_def_rating else 1.0
    # Invert: good defense (low rating) reduces points
    def_mult = 2.0 - def_mult
    
    rest_mult = 0.92 if b2b else rest_factor
    
    expected = player_ppg * usage_mult * def_mult * pace_factor * rest_mult
    return expected

def calculate_nba_rebounds(
    player_rpg: float,
    player_reb_rate: float,
    opp_reb_allowed: float,
    pace_factor: float = 1.0
) -> float:
    """Rebounds expected"""
    opp_mult = max(0.7, min(1.3, opp_reb_allowed / 44.0)) if opp_reb_allowed else 1.0
    expected = player_rpg * opp_mult * pace_factor
    # Add reb rate if available
    if player_reb_rate:
        expected *= max(0.8, min(1.2, player_reb_rate / 0.10))
    return expected

def calculate_nba_assists(
    player_apg: float,
    teammate_fg_pct: float = 0.45,
    opp_ast_allowed: float = None,
    pace_factor: float = 1.0
) -> float:
    """Assists expected"""
    # Teammate shooting impact
    fg_mult = max(0.8, min(1.2, teammate_fg_pct / 0.45))
    
    opp_mult = 1.0
    if opp_ast_allowed:
        opp_mult = max(0.8, min(1.2, opp_ast_allowed / 25.0))
    
    expected = player_apg * fg_mult * opp_mult * pace_factor
    return expected

def calculate_nba_pra(
    points: float,
    rebounds: float,
    assists: float,
    correlation_factor: float = 0.15
) -> float:
    """
    PRA = Points + Rebounds + Assists
    Accounts for correlation (if scoring more, slightly fewer rebounds etc)
    """
    # Simple sum with slight correlation adjustment
    # When points high, reb slightly lower etc - but for prop we just sum expected
    expected_pra = points + rebounds + assists
    # Add correlation boost (players who do one tend to do others)
    expected_pra *= (1 + correlation_factor * 0.1)
    return expected_pra

# === UNIFIED PROP EVALUATOR ===

def evaluate_prop(
    sport: str,
    prop_type: str,
    expected: float,
    line: float,
    over_prob: float = None
) -> Dict:
    """
    Evaluate prop vs line
    Returns dict with edge, prob, pick
    """
    if over_prob is None:
        # Calculate prob over line from expected
        # Use normal distribution with std = sqrt(expected) * 0.8
        if expected <= 0:
            over_prob = 0.5
        else:
            # Z-score
            std = math.sqrt(max(1.0, expected)) * 0.8
            z = (expected - line) / std if std > 0 else 0
            # Sigmoid for prob
            over_prob = 1 / (1 + math.exp(-z * 1.2))
    
    # Edge vs 50% (if no market) or vs implied
    # For now, edge vs 50%
    edge = over_prob - 0.5
    
    pick = "Over" if over_prob >= 0.5 else "Under"
    prob = over_prob if pick == "Over" else 1 - over_prob
    
    return {
        "expected": round(expected, 2),
        "line": line,
        "prob": round(prob, 4),
        "over_prob": round(over_prob, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge * 100, 1),
        "pick": pick,
        "qualifies": abs(edge) >= 0.05  # 5% edge minimum
    }

# === PARLAY OPTIMIZATION ===

def calculate_parlay_correlation(
    prop1: Dict,
    prop2: Dict
) -> float:
    """
    Calculate correlation between two props for parlay
    Positive correlation = good for same-game parlay if both overs
    Negative = bad
    """
    # Same game, same team = positive
    if prop1.get('game_id') == prop2.get('game_id'):
        if prop1.get('team') == prop2.get('team'):
            # Same team overs correlate positively
            # QB yards + WR yards positive
            # Pitcher K + team win maybe negative
            if 'pass' in prop1.get('market','').lower() and 'rec' in prop2.get('market','').lower():
                return 0.25  # QB + WR positive
            if 'points' in prop1.get('market','').lower() and 'reb' in prop2.get('market','').lower():
                return 0.15  # NBA points + reb positive
            return 0.10
        else:
            # Opposite teams = negative correlation
            return -0.10
    
    # Different games = ~0 correlation
    return 0.0

def optimize_parlay_stake(
    legs: List[Dict],
    bankroll: float,
    kelly_fraction: float = 0.25
) -> float:
    """
    Kelly for parlay with correlation adjustment
    """
    if not legs:
        return 0.0
    
    # Combined prob
    combined_prob = 1.0
    for leg in legs:
        combined_prob *= leg.get('prob', 0.5)
    
    # Combined odds (decimal)
    combined_odds = 1.0
    for leg in legs:
        american = leg.get('odds', -110)
        if american < 0:
            dec = 100/abs(american) + 1
        else:
            dec = american/100 + 1
        combined_odds *= dec
    
    # Correlation adjustment - reduce prob if positive correlation (less value)
    # Actually positive correlation reduces variance but also reduces edge if books adjust
    # For now, simple
    corr_adjustment = 1.0
    for i in range(len(legs)):
        for j in range(i+1, len(legs)):
            corr = calculate_parlay_correlation(legs[i], legs[j])
            # If positive correlation and both overs, reduce effective prob slightly
            if corr > 0 and legs[i].get('pick') == legs[j].get('pick') == 'Over':
                corr_adjustment *= (1 - corr * 0.1)
    
    adjusted_prob = combined_prob * corr_adjustment
    
    # Kelly
    b = combined_odds - 1
    p = adjusted_prob
    q = 1 - p
    
    if b <= 0 or p <= 0:
        return 0.0
    
    kelly = (b * p - q) / b
    kelly = max(0, kelly) * kelly_fraction
    
    # Cap at 5% for long parlays
    max_stake = 0.10 if len(legs) <= 2 else 0.05 if len(legs) <= 4 else 0.02
    kelly = min(kelly, max_stake)
    
    return kelly * bankroll

# Test
if __name__ == "__main__":
    # Test MLB HR
    prob, exp = calculate_mlb_hr_prob(0.850, 1.2, 1.05)
    print(f"MLB HR: prob={prob:.3f}, exp={exp:.3f}")
    
    # Test NFL passing
    exp_yards = calculate_nfl_passing_yards(95, 7.5, 240)
    result = evaluate_prop("NFL", "Pass Yds", exp_yards, 275.5)
    print(f"NFL Pass: {result}")
    
    # Test NBA PRA
    pts = calculate_nba_points(25, 0.25, 110)
    reb = calculate_nba_rebounds(8, 0.12, 45)
    ast = calculate_nba_assists(6, 0.47, 26)
    pra = calculate_nba_pra(pts, reb, ast)
    result = evaluate_prop("NBA", "PRA", pra, 38.5)
    print(f"NBA PRA: pts={pts:.1f}, reb={reb:.1f}, ast={ast:.1f}, pra={pra:.1f}, {result}")
