"""
Prop Engine V2 Fixed - No Circular Imports
- MLB: K, HR, Hits, TB
- NFL: Pass Yds, Rush Yds, Rec, Rec Yds
- NBA: Pts, Reb, Ast, PRA
"""

import math

def calculate_mlb_hr_prob(batter_ops=0.750, pitcher_hr9=1.2, park_factor=1.0, platoon_adv=1.0):
    base_hr_rate = 0.03
    ops_mult = max(0.3, min(2.5, (batter_ops / 0.700) ** 1.5))
    pitcher_mult = max(0.5, min(2.0, pitcher_hr9 / 1.0))
    hr_per_pa = base_hr_rate * ops_mult * pitcher_mult * park_factor * platoon_adv
    expected_hr = hr_per_pa * 4.2
    prob_over_0_5 = 1 - math.exp(-expected_hr)
    return prob_over_0_5, expected_hr

def calculate_mlb_hits_prob(batter_avg=0.250, obp=0.320, pitcher_whip=1.30, pitcher_k9=8.5, park_factor=1.0):
    k_rate = min(0.35, max(0.10, pitcher_k9 / 27.0))
    hit_per_pa = batter_avg * (1 - k_rate * 0.5) * park_factor
    whip_mult = max(0.7, min(1.3, 1.3 - (pitcher_whip - 1.3) * 0.3))
    hit_per_pa *= whip_mult
    expected_hits = hit_per_pa * 4.2
    p0 = math.exp(-expected_hits)
    p1 = expected_hits * math.exp(-expected_hits)
    prob_over_0_5 = 1 - p0
    prob_over_1_5 = 1 - p0 - p1
    return prob_over_0_5, prob_over_1_5, expected_hits

def evaluate_prop(sport, prop_type, expected, line, over_prob=None):
    if over_prob is None:
        std = math.sqrt(max(1.0, expected)) * 0.8
        z = (expected - line) / std if std > 0 else 0
        over_prob = 1 / (1 + math.exp(-z * 1.2))
    edge = over_prob - 0.5
    pick = "Over" if over_prob >= 0.5 else "Under"
    prob = over_prob if pick == "Over" else 1 - over_prob
    return {
        "expected": round(expected, 2),
        "line": line,
        "prob": round(prob, 4),
        "over_prob": round(over_prob, 4),
        "edge": round(edge, 4),
        "edge_pct": round(edge*100, 1),
        "pick": pick,
        "qualifies": abs(edge) >= 0.05
    }
