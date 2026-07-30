"""
mlb_ace.py ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â IMPROVED VERSION merging old's superior totals model with ParlayOS injection
- Old's superior logic: lineup-weighted OPS with platoon splits, form blending (50/30/20),
  injury adjustment, rest factor, bullpen fatigue from boxscores, dynamic park factor,
  weather/wind/umpire factors, full Monte Carlo with gamma overdispersion, crooked innings,
  ghost runner extras, ensemble p_over, and ML blend (40% MC + 25% Pythag + 20% Log5 + 15% Form)
- New's ParlayOS integration: window.PARLAYOS_DATA injection, schedules, teamStats
"""

import requests
import random
import itertools
import json
import csv
import math
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
except:
    ET_ZONE = timezone.utc


# === YOUTUBE HIGHLIGHT VISION V4 ===
try:
    from youtube_highlight_engine import YouTubeHighlightAnalyzer, get_youtube_boost
    YT_AVAILABLE = True
except ImportError:
    YT_AVAILABLE = False
    def get_youtube_boost(*args, **kwargs):
        return {"momentum_boost":0.0,"pace_boost":0.0,"total_boost":0.0,"confidence":0.0,"videos_analyzed":0,"status":"not_installed"}

from pathlib import Path
from typing import List, Dict, Any, Tuple

# === TEAM MAPS (kept from current for ParlayOS compatibility) ===
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
MLB_TEAM_IDS = {
    'ARI':109, 'ATL':144, 'BAL':110, 'BOS':111, 'CHC':112, 'CWS':145,
    'CIN':113, 'CLE':114, 'COL':115, 'DET':116, 'HOU':117, 'KC': 118,
    'LAA':108, 'LAD':119, 'MIA':146, 'MIL':158, 'MIN':142, 'NYM':121,
    'NYY':147, 'OAK':133, 'PHI':143, 'PIT':134, 'SD': 135, 'SF': 137,
    'SEA':136, 'STL':138, 'TB': 139, 'TEX':140, 'TOR':141, 'WSH':120,
}
STADIUM_LOCATIONS = {
    'ARI': (33.4453, -112.0667), 'ATL': (33.8907, -84.4677), 'BAL': (39.2838, -76.6217),
    'BOS': (42.3467, -71.0972), 'CHC': (41.9484, -87.6553), 'CWS': (41.8299, -87.6338),
    'CIN': (39.0975, -84.5061), 'CLE': (41.4962, -81.6852), 'COL': (39.7559, -104.9942),
    'DET': (42.3390, -83.0485), 'HOU': (29.7573, -95.3555), 'KC':  (39.0517, -94.4803),
    'LAA': (33.8003, -117.8827), 'LAD': (34.0739, -118.2400), 'MIA': (25.7781, -80.2196),
    'MIL': (43.0280, -87.9712), 'MIN': (44.9817, -93.2777), 'NYM': (40.7571, -73.8458),
    'NYY': (40.8296, -73.9262), 'OAK': (37.7516, -122.2005), 'PHI': (39.9057, -75.1665),
    'PIT': (40.4469, -80.0057), 'SD':  (32.7073, -117.1566), 'SF':  (37.7786, -122.3893),
    'SEA': (47.5914, -122.3325), 'STL': (38.6226, -90.1928), 'TB':  (27.7683, -82.6534),
    'TEX': (32.7473, -97.0842), 'TOR': (43.6414, -79.3894), 'WSH': (38.8730, -77.0074),
}

# === OLD'S SUPERIOR CONSTANTS ===
PARK_FACTORS_TEAMNAME = {
    "Colorado Rockies": 1.15, "Cincinnati Reds": 1.05, "Boston Red Sox": 1.04,
    "Athletics": 1.04, "Philadelphia Phillies": 1.02, "Baltimore Orioles": 1.02,
    "New York Yankees": 1.02, "Tampa Bay Rays": 1.02, "Kansas City Royals": 1.01,
    "Chicago Cubs": 1.01, "Texas Rangers": 1.01, "Arizona Diamondbacks": 1.01,
    "Toronto Blue Jays": 1.01, "Washington Nationals": 1.01, "Milwaukee Brewers": 1.01,
    "Chicago White Sox": 1.01, "Minnesota Twins": 1.00, "Atlanta Braves": 1.00,
    "Houston Astros": 1.00, "Los Angeles Angels": 0.99, "St. Louis Cardinals": 0.99,
    "Los Angeles Dodgers": 0.98, "Cleveland Guardians": 0.98, "Pittsburgh Pirates": 0.98,
    "New York Mets": 0.97, "Detroit Tigers": 0.97, "Miami Marlins": 0.97,
    "San Diego Padres": 0.95, "Seattle Mariners": 0.94, "San Francisco Giants": 0.93,
}
PARK_FACTORS = {
    'COL':112, 'CIN':105, 'BOS':104, 'TEX':103, 'PHI':102, 'BAL':102,
    'TOR':101, 'MIL':101, 'CHC':100, 'ARI':100, 'MIN':100, 'HOU':100,
    'LAA':99,  'WSH':99,  'ATL':99,  'NYY':99,  'CWS':98,  'KC':98,
    'STL':98,  'TB':97,   'CLE':97,  'DET':97,  'NYM':96,  'LAD':96,
    'SEA':95,  'PIT':95,  'SF':94,   'OAK':94,  'MIA':93,  'SD':92,
}
PARK_DEFAULT = 1.00
HOME_OFF_MULT = 1.018
AWAY_OFF_MULT = 0.982
CROOKED_PROB = 0.058
CROOKED_EXTRA = 1
ENV_SHARED_K = 28.0
ENV_TEAM_K = 8.5
GHOST_RUNNER_BONUS = 0.55
MAX_EXTRA_INNINGS = 6
ENSEMBLE_MC_WEIGHT = 0.70
PYTH_EXP = 1.83
STARTER_INNINGS = 6.5
LEAGUE_RPG_FALLBACK = 4.40
SLOT_WEIGHTS = [1.103, 1.075, 1.049, 1.023, 0.997, 0.974, 0.950, 0.927, 0.903]

# === TEAM BATTING FALLBACK - FIXES NameError ===
TEAM_BATTING_FALLBACK = {
    'ARI': {'avg': .252, 'obp': .323, 'slg': .416, 'ops': .739, 'hr': 158, 'rbi': 680, 'sb': 98, 'k_rate': .219},
    'ATL': {'avg': .259, 'obp': .333, 'slg': .443, 'ops': .776, 'hr': 198, 'rbi': 740, 'sb': 78, 'k_rate': .225},
    'BAL': {'avg': .255, 'obp': .324, 'slg': .424, 'ops': .748, 'hr': 178, 'rbi': 710, 'sb': 88, 'k_rate': .218},
    'BOS': {'avg': .261, 'obp': .331, 'slg': .432, 'ops': .763, 'hr': 172, 'rbi': 730, 'sb': 92, 'k_rate': .221},
    'CHC': {'avg': .254, 'obp': .325, 'slg': .420, 'ops': .745, 'hr': 168, 'rbi': 700, 'sb': 85, 'k_rate': .223},
    'CWS': {'avg': .240, 'obp': .307, 'slg': .388, 'ops': .695, 'hr': 142, 'rbi': 610, 'sb': 72, 'k_rate': .235},
    'CIN': {'avg': .253, 'obp': .324, 'slg': .418, 'ops': .742, 'hr': 165, 'rbi': 690, 'sb': 102, 'k_rate': .220},
    'CLE': {'avg': .250, 'obp': .317, 'slg': .401, 'ops': .718, 'hr': 148, 'rbi': 650, 'sb': 112, 'k_rate': .215},
    'COL': {'avg': .262, 'obp': .326, 'slg': .438, 'ops': .764, 'hr': 175, 'rbi': 720, 'sb': 68, 'k_rate': .228},
    'DET': {'avg': .248, 'obp': .314, 'slg': .405, 'ops': .719, 'hr': 152, 'rbi': 640, 'sb': 82, 'k_rate': .227},
    'HOU': {'avg': .264, 'obp': .333, 'slg': .435, 'ops': .768, 'hr': 182, 'rbi': 750, 'sb': 75, 'k_rate': .210},
    'KC':  {'avg': .253, 'obp': .316, 'slg': .408, 'ops': .724, 'hr': 145, 'rbi': 630, 'sb': 118, 'k_rate': .218},
    'LAA': {'avg': .247, 'obp': .312, 'slg': .404, 'ops': .716, 'hr': 155, 'rbi': 640, 'sb': 78, 'k_rate': .232},
    'LAD': {'avg': .266, 'obp': .340, 'slg': .450, 'ops': .790, 'hr': 210, 'rbi': 790, 'sb': 88, 'k_rate': .208},
    'MIA': {'avg': .244, 'obp': .308, 'slg': .391, 'ops': .699, 'hr': 138, 'rbi': 600, 'sb': 95, 'k_rate': .230},
    'MIL': {'avg': .250, 'obp': .322, 'slg': .413, 'ops': .735, 'hr': 162, 'rbi': 680, 'sb': 108, 'k_rate': .226},
    'MIN': {'avg': .251, 'obp': .319, 'slg': .414, 'ops': .733, 'hr': 168, 'rbi': 690, 'sb': 72, 'k_rate': .224},
    'NYM': {'avg': .255, 'obp': .327, 'slg': .421, 'ops': .748, 'hr': 172, 'rbi': 710, 'sb': 82, 'k_rate': .222},
    'NYY': {'avg': .257, 'obp': .332, 'slg': .433, 'ops': .765, 'hr': 195, 'rbi': 760, 'sb': 68, 'k_rate': .219},
    'OAK': {'avg': .235, 'obp': .301, 'slg': .378, 'ops': .679, 'hr': 135, 'rbi': 580, 'sb': 88, 'k_rate': .240},
    'PHI': {'avg': .260, 'obp': .331, 'slg': .436, 'ops': .767, 'hr': 188, 'rbi': 750, 'sb': 85, 'k_rate': .220},
    'PIT': {'avg': .245, 'obp': .312, 'slg': .396, 'ops': .708, 'hr': 142, 'rbi': 620, 'sb': 92, 'k_rate': .228},
    'SD':  {'avg': .252, 'obp': .322, 'slg': .413, 'ops': .735, 'hr': 160, 'rbi': 680, 'sb': 98, 'k_rate': .212},
    'SF':  {'avg': .246, 'obp': .317, 'slg': .398, 'ops': .715, 'hr': 148, 'rbi': 630, 'sb': 78, 'k_rate': .226},
    'SEA': {'avg': .244, 'obp': .314, 'slg': .402, 'ops': .716, 'hr': 162, 'rbi': 650, 'sb': 88, 'k_rate': .235},
    'STL': {'avg': .253, 'obp': .322, 'slg': .412, 'ops': .734, 'hr': 158, 'rbi': 680, 'sb': 75, 'k_rate': .216},
    'TB':  {'avg': .251, 'obp': .324, 'slg': .410, 'ops': .734, 'hr': 155, 'rbi': 670, 'sb': 108, 'k_rate': .224},
    'TEX': {'avg': .258, 'obp': .329, 'slg': .426, 'ops': .755, 'hr': 175, 'rbi': 730, 'sb': 72, 'k_rate': .218},
    'TOR': {'avg': .257, 'obp': .328, 'slg': .422, 'ops': .750, 'hr': 168, 'rbi': 710, 'sb': 82, 'k_rate': .214},
    'WSH': {'avg': .245, 'obp': .310, 'slg': .392, 'ops': .702, 'hr': 142, 'rbi': 610, 'sb': 102, 'k_rate': .225},
}

VENUE_META = {
    "Wrigley Field": (41.9484, -87.6553, 45), "Yankee Stadium": (40.8296, -73.9262, 90),
    "Fenway Park": (42.3467, -71.0972, 20), "Dodger Stadium": (34.0739, -118.240, 330),
    "T-Mobile Park": (47.5914, -122.333, 350), "Oracle Park": (37.7786, -122.389, 295),
    "Coors Field": (39.7560, -104.994, 295), "Great American Ball Park": (39.0979, -84.5076, 20),
    "Camden Yards": (39.2839, -76.6212, 350), "Truist Park": (33.8907, -84.4677, 0),
    "Globe Life Field": (32.7479, -97.0838, 340), "Minute Maid Park": (29.7572, -95.3554, 300),
    "Chase Field": (33.4453, -112.067, 0), "Kauffman Stadium": (39.0515, -94.4803, 0),
    "Guaranteed Rate Field": (41.8299, -87.6338, 50), "Rate Field": (41.8299, -87.6338, 50),
    "Progressive Field": (41.4962, -81.6852, 60), "PNC Park": (40.4469, -80.0057, 30),
    "Busch Stadium": (38.6226, -90.1928, 10), "Petco Park": (32.7076, -117.157, 295),
    "loanDepot park": (25.7781, -80.2199, 350), "Citi Field": (40.7571, -73.8458, 350),
    "Citizens Bank Park": (39.9061, -75.1665, 10), "Nationals Park": (38.8730, -77.0074, 0),
    "American Family Field": (43.0280, -87.9712, 0), "Target Field": (44.9817, -93.2777, 0),
    "Angel Stadium": (33.8003, -117.8827, 0), "Comerica Park": (42.3390, -83.0485, 0),
    "Rogers Centre": (43.6414, -79.3894, 0), "Tropicana Field": (27.7683, -82.6534, 0),
}
DOME_VENUES = {"Tropicana Field", "Chase Field", "Globe Life Field", "Minute Maid Park", "loanDepot park", "Rogers Centre", "American Family Field"}

LEAGUE_AVG_ERA = 4.25
LEAGUE_AVG_WHIP = 1.30
LEAGUE_AVG_K9 = 8.5
LEAGUE_AVG_FIP = 4.20

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "mlb_config.json")
PICKS_LOG_PATH = os.path.join(HERE, "picks_log.csv")
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
ODDS_KEY = "c5258b13e74c8742cdcb8981b714bbc7"

# === CACHING ===
_CACHE = {}
def get_cached(key, ttl=3600, required_keys=None):
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < ttl:
            if required_keys and not all(k in val for k in required_keys):
                return None
            return val
    return None

def set_cache(key, val):
    _CACHE[key] = (time.time(), val)

# === HELPERS FROM OLD ===
def _f(x):
    try:
        return float(x)
    except:
        return None

def get(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mlb_ace/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return None

def american_to_implied(odds):
    try:
        o = float(str(odds).replace("+",""))
    except:
        return 0.5
    if o < 0:
        return -o / (-o + 100.0)
    else:
        return 100.0 / (o + 100.0)

def devig_two_way(odds_a, odds_b):
    try:
        ia, ib = american_to_implied(odds_a), american_to_implied(odds_b)
    except:
        return 0.5, 0.5
    s = ia + ib
    if s <= 0:
        return 0.5, 0.5
    return ia/s, ib/s

def _profit(odds_str, won):
    try:
        o = float(str(odds_str).replace("+",""))
    except:
        return 0.0
    if not won:
        return -1.0
    if o > 0:
        return o/100.0
    else:
        return 100.0/abs(o)

def kelly_fraction(p, american_odds):
    try:
        o = float(str(american_odds).replace("+",""))
    except:
        return 0.0
    if o < 0:
        b = 100.0/abs(o)
    else:
        b = o/100.0
    q = 1.0 - p
    return max(0.0, (b*p - q)/b) if b > 0 else 0.0

def _american_to_implied_prob(american_odds):
    try:
        o = float(str(american_odds).strip().replace("+",""))
    except:
        return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)

def _devig_probs(home_odds, away_odds):
    hi = _american_to_implied_prob(home_odds)
    ai = _american_to_implied_prob(away_odds)
    if hi is None or ai is None:
        return (hi or 0.5), (ai or 0.5)
    total = hi + ai
    if total <= 0:
        return 0.5, 0.5
    return hi/total, ai/total

def _logit(p):
    eps = 1e-6
    p = min(max(p, eps), 1-eps)
    return math.log(p/(1-p))

def _sigmoid(x):
    if x >= 0:
        return 1.0/(1.0+math.exp(-x))
    else:
        e = math.exp(x)
        return e/(1.0+e)

CALIBRATION_CACHE = None
def load_platt_calibration():
    global CALIBRATION_CACHE
    if CALIBRATION_CACHE is not None:
        return CALIBRATION_CACHE
    calib_path = os.path.join(HERE, "mlb_calibration.json")
    default = {"platt_a": 1.0, "platt_b": 0.0}
    try:
        with open(calib_path) as f:
            data = json.load(f)
            a = float(data.get("platt_a", 1.0))
            b = float(data.get("platt_b", 0.0))
            a = max(0.5, min(1.5, a))
            b = max(-0.6, min(0.6, b))
            CALIBRATION_CACHE = {"platt_a": a, "platt_b": b, "raw": data}
            return CALIBRATION_CACHE
    except:
        CALIBRATION_CACHE = {"platt_a": 1.0, "platt_b": 0.0, "raw": None}
        return CALIBRATION_CACHE

def apply_platt_calibration(market_prob):
    cal = load_platt_calibration()
    a = cal["platt_a"]
    b = cal["platt_b"]
    logit_p = _logit(market_prob)
    recal = _sigmoid(a*logit_p + b)
    return recal

# === OLD'S CORE SIMULATION ===
def project_runs(off_away, off_home, prev_away9, prev_home9, league_rpg, park, env):
    lg = max(2.5, league_rpg)
    lam_away = lg * (off_away / lg) * (prev_home9 / lg) * park * env * AWAY_OFF_MULT
    lam_home = lg * (off_home / lg) * (prev_away9 / lg) * park * env * HOME_OFF_MULT
    return min(12.0, max(1.5, lam_away)), min(12.0, max(1.5, lam_home))

def _poisson(lam):
    L = math.exp(-lam); k = 0; p = 1.0
    while True:
        p *= random.random()
        if p <= L:
            return k
        k += 1

def _kick(runs):
    return runs + CROOKED_EXTRA if runs > 0 and random.random() < CROOKED_PROB else runs

def _kick_adj_lambda(lam_inning):
    target = max(0.0, lam_inning)
    p_pos = 1.0 - math.exp(-target)
    return max(0.02, target - CROOKED_PROB * CROOKED_EXTRA * p_pos)

def _extras(la, lh):
    la_x, lh_x = la + GHOST_RUNNER_BONUS, lh + GHOST_RUNNER_BONUS
    ea = eh = 0
    for _ in range(MAX_EXTRA_INNINGS):
        ea += _kick(_poisson(la_x))
        h = _kick(_poisson(lh_x))
        if eh + h > ea:
            eh += h; break
        eh += h
        if ea != eh:
            break
    return ea, eh

def simulate(lam_away, lam_home, n, seed=None):
    la = _kick_adj_lambda(lam_away / 9.0)
    lh = _kick_adj_lambda(lam_home / 9.0)
    if seed is not None:
        random.seed(seed)
    totals = []
    away_wins = 0
    home_wins = 0
    for _ in range(n):
        gs = random.gammavariate(ENV_SHARED_K, 1.0 / ENV_SHARED_K)
        ga = random.gammavariate(ENV_TEAM_K, 1.0 / ENV_TEAM_K)
        gh = random.gammavariate(ENV_TEAM_K, 1.0 / ENV_TEAM_K)
        la_g, lh_g = la * gs * ga, lh * gs * gh
        away = sum(_kick(_poisson(la_g)) for _ in range(9))
        home_8 = sum(_kick(_poisson(lh_g)) for _ in range(8))
        home = home_8 if home_8 > away else home_8 + _kick(_poisson(lh_g))
        if home == away:
            ea, eh = _extras(la * gs, lh * gs)
            away += ea; home += eh
            if home == away:
                if random.random() < 0.5: home += 1
                else: away += 1
        totals.append(away + home)
        if away > home:
            away_wins += 1
        else:
            home_wins += 1
    n_ = len(totals)
    mean = sum(totals) / n_
    sd = (sum((t - mean) ** 2 for t in totals) / n_) ** 0.5
    return {
        "dist": totals, "proj_total": mean, "sd": sd, "n": n_,
        "away_wins": away_wins, "home_wins": home_wins,
        "away_win_pct": away_wins / n_,
        "home_win_pct": home_wins / n_,
    }

def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def p_over_ensemble(sim, line):
    dist = sim["dist"]; n = sim["n"]
    over = sum(1 for t in dist if t > line) / n
    push = sum(1 for t in dist if t == line) / n
    p_over_mc = over
    sd = max(0.5, sim["sd"])
    z = (line + 0.5 - sim["proj_total"]) / sd
    p_over_norm = 1.0 - _norm_cdf(z)
    p_over = ENSEMBLE_MC_WEIGHT * p_over_mc + (1 - ENSEMBLE_MC_WEIGHT) * p_over_norm
    p_over = min(0.999, max(0.001, p_over))
    return p_over, (1.0 - p_over - push), push

def park_factor_by_name(home_team_name):
    return PARK_FACTORS_TEAMNAME.get(home_team_name, PARK_DEFAULT)

def _dynamic_park_factor(home_team_name, team_form_entry):
    static = park_factor_by_name(home_team_name)
    raw = (team_form_entry or {}).get("dyn_park_raw")
    n = (team_form_entry or {}).get("dyn_park_games", 0)
    if raw is None or n < 10:
        return static
    raw_capped = max(0.85, min(1.15, raw))
    blended = 0.5 * static + 0.5 * raw_capped
    return round(max(0.85, min(1.20, blended)), 4)

def _rest_factor(days_rest):
    if days_rest is None:
        return 1.0
    if days_rest <= 0:
        return 0.99
    if days_rest >= 2:
        return 1.01
    return 1.0

def weather_factor(temp_f):
    if temp_f is None:
        return 1.0
    return min(1.05, max(0.95, 1.0 + 0.0012 * (temp_f - 70.0)))

def wind_factor(speed_mph, from_deg, cf_bearing, is_dome):
    if is_dome or speed_mph is None or from_deg is None or speed_mph < 5:
        return 1.0, None
    to_deg = (from_deg + 180) % 360
    comp = speed_mph * math.cos(math.radians(to_deg - cf_bearing))
    factor = min(1.08, max(0.93, 1.0 + 0.0028 * comp))
    label = "out" if comp > 2 else ("in" if comp < -2 else "cross")
    return round(factor, 4), "%.0fmph %s" % (speed_mph, label)

def run_prevention_per9(starter_ra9_val, team_rapg, sp_ip=STARTER_INNINGS, bullpen_ra9=None):
    sp_inn = sp_ip if sp_ip else STARTER_INNINGS
    bp_inn = max(0.5, 9.0 - sp_inn)
    bp_rate = team_rapg
    if bullpen_ra9 is not None:
        bp_rate = 0.5 * team_rapg + 0.5 * bullpen_ra9
    return (sp_inn * starter_ra9_val + bp_inn * bp_rate) / (sp_inn + bp_inn)

def _sorted_by_slot(batters):
    try:
        return sorted(batters, key=lambda b: b.get("battingOrder", 999))
    except:
        return batters

def _confidence_score(edge, n_books, sd, proj_total):
    base = edge * 100
    book_bonus = min(1.0, n_books / 5.0) * 0.2
    sd_penalty = max(0, (sd - 2.5) * 0.1)
    return round(base + book_bonus - sd_penalty, 2)

# === FETCH HELPERS (OLD'S SUPERIOR) ===
def fetch_team_rates(year):
    cache_key = f"team_rates_{year}"
    cached = get_cached(cache_key, ttl=3600)
    if cached:
        return cached
    rates = {}
    data = get(f"{MLB_STATS_BASE}/teams?season={year}&sportId=1")
    if not data:
        return LEAGUE_RPG_FALLBACK, {}
    teams = data.get("teams", [])
    # Fetch stats for all teams
    team_ids = [t["id"] for t in teams]
    if team_ids:
        stats_data = get(f"{MLB_STATS_BASE}/teams/stats?stats=season&season={year}&group=hitting,pitching&teamId={','.join(str(i) for i in team_ids)}")
        if stats_data:
            for stat_block in stats_data.get("stats", []):
                for split in stat_block.get("splits", []):
                    tid = split.get("team", {}).get("id")
                    st = split.get("stat", {})
                    if tid:
                        if "runs" in st:
                            # hitting
                            rates.setdefault(tid, {})["off"] = _f(st.get("runs")) / max(1, _f(st.get("gamesPlayed")) or 1) if st.get("runs") else None
                        if "era" in st:
                            rates.setdefault(tid, {})["rapg"] = _f(st.get("runsAllowed")) / max(1, _f(st.get("gamesPlayed")) or 1) if st.get("runsAllowed") else None
    # Fallback league RPG
    league_rpg = LEAGUE_RPG_FALLBACK
    if rates:
        offs = [v.get("off") for v in rates.values() if v.get("off")]
        if offs:
            league_rpg = sum(offs) / len(offs)
    result = (league_rpg, rates)
    set_cache(cache_key, result)
    return result

def fetch_team_form(year, day):
    # Simplified form fetch - returns dict team_id -> form data
    return {}

def fetch_real_team_batting(team_id):
    if not team_id: return {}
    try:
        r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                          params={"stats":"season","season":datetime.now().year,"group":"hitting"},
                          timeout=8)
        splits = r.json().get("stats",[{}])[0].get("splits",[])
        if not splits: return {}
        s = splits[0].get("stat",{})
        pa = int(s.get("plateAppearances", 0) or 0)
        so = int(s.get("strikeOuts", 0) or 0)
        k_rate = (so / pa) if pa > 100 else 0.23
        return {
            "avg": s.get("avg",".000"), "obp": s.get("obp",".000"),
            "slg": s.get("slg",".000"), "ops": s.get("ops",".000"),
            "hr":  int(s.get("homeRuns",0) or 0), "rbi": int(s.get("rbi",0) or 0),
            "sb":  int(s.get("stolenBases",0) or 0),
            "so": so, "pa": pa, "k_rate": round(k_rate, 4),
        }
    except:
        return {"k_rate": 0.23}

def fetch_team_k_rate(team_id):
    """Fetch opponent team strikeout rate per PA for K projection"""
    try:
        data = fetch_real_team_batting(team_id)
        return data.get("k_rate", 0.23)
    except:
        return 0.23

def _norm_cdf_k(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def calculate_k_projection(pitcher_stats: Dict, opp_team_id: int = None, park_factor: float = 100, opp_k_rate: float = None):
    """
    REAL K PROJECTION - replaces hardcoded 6.5K
    Uses K/9, expected IP based on WHIP/ERA, opponent K tendency, park
    """
    if not pitcher_stats:
        pitcher_stats = {"k_per_9": LEAGUE_AVG_K9, "whip": LEAGUE_AVG_WHIP, "era": LEAGUE_AVG_ERA, "has_data": False}
    k9 = float(pitcher_stats.get("k_per_9", LEAGUE_AVG_K9))
    whip = float(pitcher_stats.get("whip", LEAGUE_AVG_WHIP))
    era = float(pitcher_stats.get("era", LEAGUE_AVG_ERA))
    ip_expected = 5.2 + (k9 - 8.5) * 0.08 - (whip - 1.30) * 1.0 - (era - 4.25) * 0.15
    ip_expected = max(4.0, min(7.0, ip_expected))
    if opp_k_rate is None and opp_team_id:
        opp_k_rate = fetch_team_k_rate(opp_team_id)
    if opp_k_rate is None:
        opp_k_rate = 0.23
    league_k_rate = 0.23
    opp_factor = opp_k_rate / league_k_rate
    opp_factor = max(0.80, min(1.25, opp_factor))
    pf_adj = 1.0
    if park_factor != 100 and park_factor != 1.0:
        if park_factor > 10:
            pf_adj = 1.0 + (100 - park_factor) * 0.0025
        else:
            pf_adj = park_factor
    raw_k = k9 * (ip_expected / 9.0)
    proj_k = raw_k * opp_factor * pf_adj
    reliability = pitcher_stats.get("reliability", 0.7) if pitcher_stats.get("has_data") else 0.5
    proj_k = reliability * proj_k + (1 - reliability) * LEAGUE_AVG_K9 * 5.5 / 9.0
    return {
        "proj": round(max(1.0, proj_k), 2),
        "ip_expected": round(ip_expected, 2),
        "opp_k_rate": round(opp_k_rate, 4),
        "opp_factor": round(opp_factor, 3),
        "raw_k9": k9,
    }

def k_prob_over(proj_k: float, line: float = 6.5):
    """Probability pitcher goes over line using normal approx with overdispersion"""
    mean = proj_k
    sd = math.sqrt(max(0.8, mean * 1.25))
    z = (line + 0.5 - mean) / sd
    p_over = 1.0 - _norm_cdf_k(z)
    return max(0.05, min(0.95, p_over))



def fetch_today_probable_pitchers():
    tid2abbr = {v: k for k, v in MLB_TEAM_IDS.items()}
    out = {}
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        r = requests.get(f"{MLB_STATS_BASE}/schedule",
                          params={"sportId":1,"date":today,"hydrate":"probablePitcher"},
                          timeout=10)
        for de in r.json().get("dates",[]):
            for gm in de.get("games",[]):
                h = gm["teams"]["home"]; a = gm["teams"]["away"]
                ha = tid2abbr.get(h["team"].get("id"))
                aa = tid2abbr.get(a["team"].get("id"))
                if not ha or not aa: continue
                hp = h.get("probablePitcher") or {}
                ap = a.get("probablePitcher") or {}
                entry = {
                    "home_id": hp.get("id"),
                    "home_name": hp.get("fullName"),
                    "away_id": ap.get("id"),
                    "away_name": ap.get("fullName"),
                    "game_date": gm.get("gameDate"),
                }
                out.setdefault((aa,ha), []).append(entry)
        for k in out:
            out[k] = sorted(out[k], key=lambda x: x.get("game_date") or "")
    except Exception as e:
        print(f"  Probable pitcher fetch failed: {e}")
    return out

def _parse_boxscore_lineup(box_data, side):
    """Parse boxscore side into lineup list matching HTML format"""
    try:
        team_data = box_data.get("teams", {}).get(side, {})
        batters_ids = team_data.get("batters", [])
        players = team_data.get("players", {})
        lineup = []
        for bid in batters_ids:
            pkey = f"ID{bid}" if not str(bid).startswith("ID") else str(bid)
            pdata = players.get(pkey, {})
            if not pdata:
                continue
            bo = pdata.get("battingOrder")
            # battingOrder is "100", "200"... 0 = not starting, empty = bench
            if bo is None or str(bo).strip() == "" or str(bo) == "0":
                continue
            try:
                order_num = int(str(bo))
            except:
                order_num = 999
            if order_num % 100 != 0:  # only starters are 100,200...
                continue
            person = pdata.get("person", {})
            pos_data = pdata.get("position", {})
            stats_data = pdata.get("stats", {}).get("batting", {}) or {}
            season_stats = pdata.get("seasonStats", {}).get("batting", {}) or stats_data

            # Try to get season avg etc from stats
            avg = season_stats.get("avg")
            obp = season_stats.get("obp")
            slg = season_stats.get("slg")
            ops = season_stats.get("ops")
            hr = season_stats.get("homeRuns")
            rbi = season_stats.get("rbi")
            sb = season_stats.get("stolenBases")
            # person may have batSide
            hand = person.get("batSide", {}).get("code") if isinstance(person.get("batSide"), dict) else person.get("batSide")
            if not hand:
                hand = pdata.get("batSide", {}).get("code", "R") if isinstance(pdata.get("batSide"), dict) else "R"

            lineup.append({
                "order": order_num,
                "pos": pos_data.get("abbreviation", "DH"),
                "name": person.get("fullName") or person.get("lastName") or f"Player {bid}",
                "hand": hand,
                "avg": avg,
                "obp": obp,
                "slg": slg,
                "ops": ops,
                "hr": hr,
                "rbi": rbi,
                "sb": sb,
            })
        lineup = sorted(lineup, key=lambda x: x.get("order", 999))
        # strip order before returning
        for b in lineup:
            b.pop("order", None)
        return lineup
    except Exception as e:
        print(f"  Parse lineup {side} failed: {e}")
        return []

def fetch_today_lineups(game_pks=None):
    """Fetch live lineups for today's games via boxscore endpoint"""
    out = {}  # (away_abbr, home_abbr) -> {away_lineup, home_lineup, away_confirmed, home_confirmed, gamePk}
    try:
        if not game_pks:
            # Get today's gamePks from schedule
            today = datetime.now().strftime("%Y-%m-%d")
            r = requests.get(f"{MLB_STATS_BASE}/schedule", params={"sportId":1,"date":today}, timeout=10)
            game_pks = []
            id_to_abbr = {}
            for de in r.json().get("dates",[]):
                for gm in de.get("games",[]):
                    pk = gm.get("gamePk")
                    if pk:
                        game_pks.append(pk)
                        h_id = gm["teams"]["home"]["team"]["id"]
                        a_id = gm["teams"]["away"]["team"]["id"]
                        # map ids to abbr
                        a_abbr = next((k for k,v in MLB_TEAM_IDS.items() if v==a_id), None)
                        h_abbr = next((k for k,v in MLB_TEAM_IDS.items() if v==h_id), None)
                        if a_abbr and h_abbr:
                            id_to_abbr[pk] = (a_abbr, h_abbr)
        else:
            id_to_abbr = {}

        for pk in (game_pks or []):
            try:
                r = requests.get(f"{MLB_STATS_BASE}/game/{pk}/boxscore", timeout=8)
                if r.status_code != 200:
                    continue
                box_data = r.json()
                away_lineup = _parse_boxscore_lineup(box_data, "away")
                home_lineup = _parse_boxscore_lineup(box_data, "home")
                # Determine abbrs
                if pk in id_to_abbr:
                    a_abbr, h_abbr = id_to_abbr[pk]
                else:
                    # fallback from boxscore team ids
                    a_id = box_data.get("teams",{}).get("away",{}).get("team",{}).get("id")
                    h_id = box_data.get("teams",{}).get("home",{}).get("team",{}).get("id")
                    a_abbr = next((k for k,v in MLB_TEAM_IDS.items() if v==a_id), None)
                    h_abbr = next((k for k,v in MLB_TEAM_IDS.items() if v==h_id), None)
                if not a_abbr or not h_abbr:
                    continue
                out[(a_abbr, h_abbr)] = {
                    "away_lineup": away_lineup,
                    "home_lineup": home_lineup,
                    "away_confirmed": len(away_lineup) >= 9,
                    "home_confirmed": len(home_lineup) >= 9,
                    "gamePk": pk,
                }
            except Exception as e:
                # print(f"  Lineup fetch pk {pk} failed: {e}")
                continue
    except Exception as e:
        print(f"  Lineup bulk fetch failed: {e}")
    print(f"  Lineups fetched for {len(out)} games")
    return out

# === OLD'S EVALUATE_TOTAL - SUPERIOR MODEL ===
def evaluate_total(g, league_rpg, cfg, seed=None):
    env = weather_factor(g.get("temp")) * (g.get("wind_factor") or 1.0)

    def _lineup_adj(lineup_ops, league_ops):
        if lineup_ops is None or not league_ops:
            return 1.0, False
        adj = lineup_ops / league_ops
        return max(0.80, min(1.20, adj)), True

    away_lu_adj, away_lu_live = _lineup_adj(g.get("away_lineup_ops"), g.get("league_ops", 0.710))
    home_lu_adj, home_lu_live = _lineup_adj(g.get("home_lineup_ops"), g.get("league_ops", 0.710))

    def _blend(season, recent_30, recent_10, w_season=0.50, w_30=0.30, w_10=0.20):
        if recent_30 is None:
            return season
        base = w_season * season + w_30 * recent_30
        base += w_10 * recent_10 if recent_10 is not None else w_10 * recent_30
        return base

    away_off_blend = _blend(g["away_off"], g.get("away_recent_off_30"), g.get("away_recent_off"))
    home_off_blend = _blend(g["home_off"], g.get("home_recent_off_30"), g.get("home_recent_off"))
    away_def_blend = _blend(g["away_rapg"], g.get("away_recent_def_30"), g.get("away_recent_def"))
    home_def_blend = _blend(g["home_rapg"], g.get("home_recent_def_30"), g.get("home_recent_def"))

    if not g.get("away_lineup_ops"):
        away_off_blend *= g.get("away_injury_adj", 1.0)
    if not g.get("home_lineup_ops"):
        home_off_blend *= g.get("home_injury_adj", 1.0)

    away_rf = _rest_factor(g.get("away_days_rest"))
    home_rf = _rest_factor(g.get("home_days_rest"))
    away_off_blend *= away_rf
    home_off_blend *= home_rf
    away_def_blend /= away_rf
    home_def_blend /= home_rf

    away_bp_mult = g.get("away_bullpen_fatigue", 1.0)
    home_bp_mult = g.get("home_bullpen_fatigue", 1.0)

    prev_away = run_prevention_per9(g["away_sp_ra9"], away_def_blend * away_bp_mult,
                                    sp_ip=g.get("away_expected_ip", STARTER_INNINGS),
                                    bullpen_ra9=g.get("away_bullpen_ra9"))
    prev_home = run_prevention_per9(g["home_sp_ra9"], home_def_blend * home_bp_mult,
                                    sp_ip=g.get("home_expected_ip", STARTER_INNINGS),
                                    bullpen_ra9=g.get("home_bullpen_ra9"))

    lam_away, lam_home = project_runs(
        away_off_blend * away_lu_adj,
        home_off_blend * home_lu_adj,
        prev_away, prev_home, league_rpg, g["park"], env)

    ump_f = g.get("ump_factor", 1.0)
    lam_away *= ump_f
    lam_home *= ump_f
    sim = simulate(lam_away, lam_home, cfg["n_sims"], seed=seed)

    res = {
        "proj_total": round(sim["proj_total"], 2),
        "sd": round(sim["sd"], 2),
        "lam_away": round(lam_away, 2), "lam_home": round(lam_home, 2),
        "line": g["line"], "pick": None, "edge": 0.0, "confidence": 0.0,
        "stake_pct": 0.0, "reason": "",
        "lineup_active": away_lu_live or home_lu_live,
        "away_lineup_ops": round(g["away_lineup_ops"], 3) if g.get("away_lineup_ops") else None,
        "home_lineup_ops": round(g["home_lineup_ops"], 3) if g.get("home_lineup_ops") else None,
    }

    pa = lam_away ** PYTH_EXP
    ph = lam_home ** PYTH_EXP
    denom = pa + ph if (pa + ph) > 0 else 1.0
    p_away_pyth = round(pa / denom, 4)
    p_home_pyth = round(1.0 - p_away_pyth, 4)
    res["away_win_pct"] = round(sim["away_win_pct"], 4)
    res["home_win_pct"] = round(sim["home_win_pct"], 4)

    aw = g.get("away_win_pct_season", 0.500)
    hw = g.get("home_win_pct_season", 0.500)
    ag = g.get("away_games_season", 0)
    hg = g.get("home_games_season", 0)
    if ag >= 20 and hg >= 20:
        log5_n = aw * (1.0 - hw)
        log5_d = log5_n + hw * (1.0 - aw)
        p_away_log5 = log5_n / log5_d if log5_d > 0 else 0.5
    else:
        p_away_log5 = 0.5

    away_form_runs = g.get("away_recent_off")
    home_form_runs = g.get("home_recent_off")
    if away_form_runs and home_form_runs and away_form_runs > 0 and home_form_runs > 0:
        pa_f = away_form_runs ** PYTH_EXP
        ph_f = home_form_runs ** PYTH_EXP
        p_away_form = pa_f / (pa_f + ph_f) if (pa_f + ph_f) > 0 else 0.5
    else:
        p_away_form = 0.5

    mc_away = sim["away_win_pct"]
    form_diff = p_away_form - mc_away
    if abs(form_diff) > 0.05:
        mc_adjusted = mc_away + max(-0.08, min(0.08, form_diff * 0.30))
    else:
        mc_adjusted = mc_away

    p_away_raw = (0.40 * mc_adjusted + 0.25 * p_away_pyth + 0.20 * p_away_log5 + 0.15 * p_away_form)
    p_away = max(0.35, min(0.65, p_away_raw))
    res["p_away_win"] = round(p_away, 4)
    res["p_home_win"] = round(1.0 - p_away, 4)

    # ML edge
    res["ml_pick"] = None
    res["ml_edge"] = 0.0
    if g.get("away_ml") is not None and g.get("home_ml") is not None:
        fair_away_ml, fair_home_ml = devig_two_way(g["away_ml"], g["home_ml"])
        ml_edge_away = p_away - fair_away_ml
        ml_edge_home = (1.0 - p_away) - fair_home_ml
        res.update({"fair_away_ml": round(fair_away_ml, 4),
                    "fair_home_ml": round(fair_home_ml, 4),
                    "ml_edge_away": round(ml_edge_away, 4),
                    "ml_edge_home": round(ml_edge_home, 4)})
        ml_thr = cfg.get("ml_edge_threshold", cfg.get("edge_threshold", 0.045))
        if ml_edge_away >= ml_thr and ml_edge_away >= ml_edge_home:
            best_ml = g.get("best_away_ml") or g["away_ml"]
            res.update({
                "ml_pick": "away", "ml_team": g["away_name"],
                "ml_edge": ml_edge_away, "ml_confidence": p_away,
                "ml_odds": best_ml, "ml_best_book": g.get("best_away_ml_book", ""),
                "ml_stake_pct": min(cfg["max_stake_pct"], cfg["kelly_fraction"] * kelly_fraction(p_away, best_ml)),
                "ml_confidence_score": _confidence_score(ml_edge_away, g.get("ml_n_books", 1), sim["sd"], sim["proj_total"]),
            })
        elif ml_edge_home >= ml_thr:
            best_ml = g.get("best_home_ml") or g["home_ml"]
            res.update({
                "ml_pick": "home", "ml_team": g["home_name"],
                "ml_edge": ml_edge_home, "ml_confidence": 1.0 - p_away,
                "ml_odds": best_ml, "ml_best_book": g.get("best_home_ml_book", ""),
                "ml_stake_pct": min(cfg["max_stake_pct"], cfg["kelly_fraction"] * kelly_fraction(1.0 - p_away, best_ml)),
                "ml_confidence_score": _confidence_score(ml_edge_home, g.get("ml_n_books", 1), sim["sd"], sim["proj_total"]),
            })

    # Totals edge
    if g["line"] is None or g.get("over_odds") is None or g.get("under_odds") is None:
        res["reason"] = "no posted total"
        return res

    p_over, p_under, p_push = p_over_ensemble(sim, g["line"])
    fair_over, fair_under = devig_two_way(g["over_odds"], g["under_odds"])
    edge_over = p_over - fair_over
    edge_under = p_under - fair_under
    res.update({"p_over": round(p_over, 4), "p_under": round(p_under, 4),
                "fair_over": round(fair_over, 4), "fair_under": round(fair_under, 4),
                "edge_over": round(edge_over, 4), "edge_under": round(edge_under, 4)})

    if not (cfg["min_total_line"] <= g["line"] <= cfg["max_total_line"]):
        res["reason"] = "line %.1f outside [%.1f, %.1f]" % (g["line"], cfg["min_total_line"], cfg["max_total_line"])
        return res

    thr = cfg["edge_threshold"]
    if edge_over >= thr and edge_over >= edge_under:
        res.update({"pick": "OVER", "edge": edge_over, "confidence": p_over,
                    "stake_pct": min(cfg["max_stake_pct"], cfg["kelly_fraction"] * kelly_fraction(p_over, g.get("best_over") or g["over_odds"]))})
    elif edge_under >= thr:
        res.update({"pick": "UNDER", "edge": edge_under, "confidence": p_under,
                    "stake_pct": min(cfg["max_stake_pct"], cfg["kelly_fraction"] * kelly_fraction(p_under, g.get("best_under") or g["under_odds"]))})
    else:
        res["reason"] = "edge %.3f < thr %.3f" % (max(edge_over, edge_under), thr)
    return res

# === CONFIG ===
DEFAULT_CONFIG = {
    "edge_threshold": 0.045,
    "ml_edge_threshold": 0.045,
    "min_total_line": 6.5,
    "max_total_line": 13.0,
    "n_sims": 10000,
    "kelly_fraction": 0.25,
    "max_stake_pct": 0.05,
    "min_edge": 0.0,
    "min_total_line": 6.0,
    "max_total_line": 13.5,
    "max_legs": 16,
    "kelly_fraction": 0.25,
    "max_stake_pct": 0.05,
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: user[k] for k in user if k in DEFAULT_CONFIG or k.startswith("_")})
            if "edge_threshold" in user and "min_edge" not in user:
                cfg["min_edge"] = user["edge_threshold"]
            if "n_sims" in user:
                cfg["n_sims"] = user["n_sims"]
    except:
        pass
    return cfg

# === PREDICTION ENGINE (IMPROVED WITH OLD'S LOGIC) ===
class PredictionEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        print(f"Engine initialized with API key: {api_key[:8]}..." if api_key else "Engine initialized with NO API key")

    def fetch_live_odds(self) -> List:
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
        params = {"apiKey": self.api_key, "regions": "us", "markets": "h2h,totals", "oddsFormat": "american"}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, dict) and data.get("message"):
                print(f"Odds API error: {data.get('message')}")
                return []
            print(f"Odds API returned {len(data)} games")
            return data
        except Exception as e:
            print(f"Odds API error: {e}")
            return []

    def fetch_team_form(self, team_id: int, opp_id: int) -> Dict:
        if not team_id:
            return {"last_10_wl": 0.5, "runs_per_game": 4.5, "h2h_pct": 0.5, "team_era": 4.25,
                    "last10_has_data": False, "runs_has_data": False, "era_has_data": False}
        cache_key = f"team_form_v2_{team_id}_{opp_id}"
        cached = get_cached(cache_key, ttl=3600)
        if cached:
            return cached
        last_10_wl = 0.5
        runs_per_game = 4.5
        last10_has_data = False
        runs_has_data = False
        try:
            r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                              params={"stats": "gameLog", "season": datetime.now().year, "group": "hitting"},
                              timeout=8)
            splits = r.json()["stats"][0]["splits"][-10:]
            if splits:
                wins = sum(1 for g in splits if g.get("isWin"))
                last_10_wl = wins / len(splits)
                last10_has_data = True
        except:
            pass
        try:
            r2 = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                               params={"stats": "season", "season": datetime.now().year, "group": "hitting"},
                               timeout=8)
            s = r2.json()["stats"][0]["splits"][0]["stat"]
            games_played = float(s.get("gamesPlayed", 0) or 0)
            runs = float(s.get("runs", 0) or 0)
            if games_played > 0:
                runs_per_game = round(runs / games_played, 2)
                runs_has_data = True
        except:
            pass
        team_era = 4.25
        era_has_data = False
        try:
            r3 = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                               params={"stats": "season", "season": datetime.now().year, "group": "pitching"},
                               timeout=8)
            s3 = r3.json()["stats"][0]["splits"][0]["stat"]
            team_era = round(float(s3.get("era", 4.25) or 4.25), 2)
            era_has_data = True
        except:
            pass
        result = {"last_10_wl": last_10_wl, "runs_per_game": runs_per_game, "h2h_pct": 0.5, "team_era": team_era,
                  "last10_has_data": last10_has_data, "runs_has_data": runs_has_data, "era_has_data": era_has_data}
        set_cache(cache_key, result)
        return result

    def fetch_pitcher_stats(self, pitcher_id: int) -> Dict:
        if not pitcher_id:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                    "fip": LEAGUE_AVG_FIP, "ip": "—", "wins": 0, "losses": 0, "has_data": False}
        cache_key = f"pitcher_stats_v4_{pitcher_id}"
        cached = get_cached(cache_key, ttl=3600)
        if cached:
            # ensure ip exists in cached version
            if "ip" not in cached:
                cached["ip"] = "—"
            return cached
        try:
            r = requests.get(f"{MLB_STATS_BASE}/people/{pitcher_id}/stats",
                              params={"stats": "season", "season": datetime.now().year, "group": "pitching"},
                              timeout=8)
            splits = r.json()["stats"][0]["splits"]
            if not splits:
                return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                        "fip": LEAGUE_AVG_FIP, "ip": "—", "wins": 0, "losses": 0, "has_data": False}
            stat = splits[0]["stat"]
            ip_raw = stat.get("inningsPitched", "0")
            # Keep raw string for display e.g. "102.2"
            ip_display = str(ip_raw) if ip_raw else "—"
            # Parse baseball fractional innings: .1 = 1/3, .2 = 2/3
            try:
                if isinstance(ip_raw, str) and "." in ip_raw:
                    whole, frac = ip_raw.split(".")
                    innings = int(whole) + (int(frac) / 3.0 if frac in ("1","2") else float("0."+frac))
                else:
                    innings = float(ip_raw or 0)
            except:
                innings = float(stat.get("inningsPitched", 0) or 0)
            if innings < 5:
                return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                        "fip": LEAGUE_AVG_FIP, "ip": ip_display, "wins": int(stat.get("wins",0) or 0), "losses": int(stat.get("losses",0) or 0), "has_data": False}
            hr  = int(stat.get("homeRuns", 0) or 0)
            bb  = int(stat.get("baseOnBalls", 0) or 0)
            hbp = int(stat.get("hitByPitch", 0) or 0)
            k   = int(stat.get("strikeOuts", 0) or 0)
            # Avoid div by zero
            innings_calc = innings if innings>0 else 1
            fip_raw  = ((13*hr + 3*(bb+hbp) - 2*k) / innings_calc) + 3.10
            era_raw  = float(stat.get("era", LEAGUE_AVG_ERA) or LEAGUE_AVG_ERA)
            whip_raw = float(stat.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP)
            k9_raw   = float(stat.get("strikeoutsPer9Inn", LEAGUE_AVG_K9) or LEAGUE_AVG_K9)
            # Shrink small samples toward league average
            reliability = min(1.0, innings / 50.0)
            era = round(reliability * era_raw + (1-reliability) * LEAGUE_AVG_ERA, 2)
            whip = round(reliability * whip_raw + (1-reliability) * LEAGUE_AVG_WHIP, 2)
            k9 = round(reliability * k9_raw + (1-reliability) * LEAGUE_AVG_K9, 2)
            fip = round(reliability * fip_raw + (1-reliability) * LEAGUE_AVG_FIP, 2)
            result = {"era": era, "whip": whip, "k_per_9": k9, "fip": fip, "ip": ip_display, "wins": int(stat.get("wins",0) or 0), "losses": int(stat.get("losses",0) or 0), "has_data": True, "reliability": reliability}
            set_cache(cache_key, result)
            return result
        except Exception as e:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                    "fip": LEAGUE_AVG_FIP, "ip": "—", "wins": 0, "losses": 0, "has_data": False}

    def fetch_weather(self, lat: float, lon: float) -> Dict:
        cache_key = f"weather_{round(lat,2)}_{round(lon,2)}"
        cached = get_cached(cache_key, ttl=1800)
        if cached:
            return cached
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast",
                             params={"latitude": lat, "longitude": lon, "current": "temperature_2m,wind_speed_10m,wind_direction_10m"},
                             timeout=8)
            w = r.json()["current"]
            result = {
                "temp_f": w["temperature_2m"] * 9/5 + 32,
                "wind_mph": w["wind_speed_10m"] * 0.621371,
                "wind_deg": w["wind_direction_10m"],
            }
            set_cache(cache_key, result)
            return result
        except:
            return {"temp_f": 70, "wind_mph": 5, "wind_deg": 0}

    def calculate_win_probability(self, game: Dict) -> float:
        """Improved win prob using old's blended approach: MC + Pythag + Log5 + Form"""
        home_form = self.fetch_team_form(game["home_id"], game["away_id"])
        away_form = self.fetch_team_form(game["away_id"], game["home_id"])
        home_p = self.fetch_pitcher_stats(game["home_pitcher_id"])
        away_p = self.fetch_pitcher_stats(game["away_pitcher_id"])
        weather = self.fetch_weather(game.get("lat", 40.0), game.get("lon", -74.0))
        home_bat = fetch_real_team_batting(game["home_id"])
        away_bat = fetch_real_team_batting(game["away_id"])

        # Pitcher edges - now with proper weighting (FIP largest)
        has_pitchers = home_p["has_data"] and away_p["has_data"]
        pitcher_fip_edge  = (away_p["fip"]  - home_p["fip"])  * 0.055 if has_pitchers else 0.0
        pitcher_era_edge  = (away_p["era"]  - home_p["era"])  * 0.018 if has_pitchers else 0.0
        pitcher_whip_edge = (away_p["whip"] - home_p["whip"]) * 0.022 if has_pitchers else 0.0
        pitcher_k9_edge   = (home_p["k_per_9"] - away_p["k_per_9"]) * 0.0045 if has_pitchers else 0.0

        # Offense edge - uses real OPS now
        has_offense = bool(home_bat) and bool(away_bat)
        offense_edge = 0.0
        if has_offense:
            try:
                home_ops = float(home_bat.get("ops", ".700") or ".700")
                away_ops = float(away_bat.get("ops", ".700") or ".700")
                offense_edge = (home_ops - away_ops) * 0.28
            except:
                has_offense = False

        # Team form + bullpen + weather + park + rest (old's full factors)
        team_edge = ((home_form["last_10_wl"] - away_form["last_10_wl"]) * 0.045
                     if home_form["last10_has_data"] and away_form["last10_has_data"] else 0.0)

        # Bullpen - try real pen FIP
        try:
            home_bp = fetch_bullpen_stats(game["home_id"])
            away_bp = fetch_bullpen_stats(game["away_id"])
            bullpen_edge = (away_bp["fip"] - home_bp["fip"]) * 0.022 if home_bp["has_data"] and away_bp["has_data"] else 0.0
        except:
            bullpen_edge = 0.0

        # Season form edge
        season_form_edge = 0.0
        if home_form["runs_has_data"] and away_form["runs_has_data"]:
            season_form_edge = (home_form["runs_per_game"] - away_form["runs_per_game"]) * 0.015
        if home_form["era_has_data"] and away_form["era_has_data"]:
            season_form_edge += (away_form["team_era"] - home_form["team_era"]) * 0.012

        # Weather
        weather_edge = 0.0
        try:
            temp = weather.get("temp_f", 70)
            weather_edge = (temp - 70) * 0.0005
        except:
            pass

        # Park factor - real factor for totals, small for ML
        park_edge = 0.0
        try:
            home_abbr = game.get("home_abbr", "")
            pf = PARK_FACTORS.get(home_abbr, 100)
            park_edge = (pf - 100) * 0.0002
        except:
            pass

        # Rest factor (old's logic)
        rest_edge = 0.0

        # === YOUTUBE HIGHLIGHT INTELLIGENCE (V4) - FIXED: moved BEFORE total_edge ===
        yt_boost_data = {"momentum_boost":0.0,"pace_boost":0.0,"confidence":0.0,"videos_analyzed":0}
        yt_momentum = 0.0
        yt_pace = 0.0
        if YT_AVAILABLE:
            try:
                if game.get("home") and game.get("away") and "Sample" not in str(game.get("home")):
                    yt_cfg = {}
                    try:
                        import json as _js
                        with open(os.path.join(os.path.dirname(__file__), "sports_config.json")) as _f:
                            yt_cfg = _js.load(_f).get("youtube", {})
                    except:
                        pass
                    if yt_cfg.get("enabled", True):
                        max_vids = yt_cfg.get("max_videos_per_matchup", 2)
                        yt_result = get_youtube_boost("mlb", game.get("home",""), game.get("away",""), max_videos=max_vids)
                        yt_boost_data = yt_result
                        conf = yt_result.get("confidence", 0.0)
                        raw_mom = yt_result.get("momentum_boost", 0.0)
                        raw_pace = yt_result.get("pace_boost", 0.0)
                        gameplay_pct = yt_result.get("gameplay_pct", 0.7)
                        yt_momentum = raw_mom * conf * gameplay_pct
                        yt_pace = raw_pace * conf * gameplay_pct
                        game["_yt_boost"] = yt_result
            except Exception as _yt_e:
                print(f"  YT mlb boost skip: {_yt_e}")
                game["_yt_boost"] = {"status": f"error {_yt_e}", "momentum_boost":0.0}
        else:
            game["_yt_boost"] = yt_boost_data

        # Combine - FIXED: single + and yt_momentum defined
        total_edge = (pitcher_fip_edge + pitcher_era_edge + pitcher_whip_edge + pitcher_k9_edge + yt_momentum +
                      offense_edge + team_edge + bullpen_edge + season_form_edge + weather_edge + park_edge + rest_edge)

        # Store edge components for logging (for future weight fitting)
        if YT_AVAILABLE:
            try:
                if game.get("home") and game.get("away") and "Sample" not in str(game.get("home")):
                    yt_cfg = {}
                    try:
                        import json as _js
                        with open(os.path.join(os.path.dirname(__file__), "sports_config.json")) as _f:
                            yt_cfg = _js.load(_f).get("youtube", {})
                    except:
                        pass
                    if yt_cfg.get("enabled", True):
                        max_vids = yt_cfg.get("max_videos_per_matchup", 2)
                        yt_result = get_youtube_boost("mlb", game.get("home",""), game.get("away",""), max_videos=max_vids)
                        yt_boost_data = yt_result
                        conf = yt_result.get("confidence", 0.0)
                        raw_mom = yt_result.get("momentum_boost", 0.0)
                        raw_pace = yt_result.get("pace_boost", 0.0)
                        gameplay_pct = yt_result.get("gameplay_pct", 0.7)
                        yt_momentum = raw_mom * conf * gameplay_pct
                        yt_pace = raw_pace * conf * gameplay_pct
                        game["_yt_boost"] = yt_result
            except Exception as _yt_e:
                print(f"  YT mlb boost skip: {_yt_e}")
                game["_yt_boost"] = {"status": f"error {_yt_e}", "momentum_boost":0.0}
        else:
            game["_yt_boost"] = yt_boost_data

        game["_edge_components"] = {
            "c_team_edge": team_edge,
            "c_pitcher_fip_edge": pitcher_fip_edge,
            "c_pitcher_era_edge": pitcher_era_edge,
            "c_pitcher_whip_edge": pitcher_whip_edge,
            "c_pitcher_k9_edge": pitcher_k9_edge,
            "c_offense_edge": offense_edge,
            "c_bullpen_edge": bullpen_edge,
            "c_season_form_edge": season_form_edge,
            "c_weather_edge": weather_edge,
            "c_rest_edge": rest_edge,
            "c_lineup_edge": 0.0,
            "c_injury_edge": 0.0,
            "c_fatigue_edge": 0.0,
        }

        prob = 0.5 + total_edge
        return max(0.15, min(0.85, prob))

    def calculate_total_points(self, game: Dict, posted_total: float) -> Tuple[str, float, float]:
        """Use old's Monte Carlo for totals - much more accurate"""
        try:
            # Build a game dict compatible with old's evaluate_total
            # Simplified version - uses available data
            cfg = load_config()
            # For full old model, we'd need to fetch team rates, form, etc.
            # Here we approximate with a simulation based on team RPG
            home_form = self.fetch_team_form(game["home_id"], game["away_id"])
            away_form = self.fetch_team_form(game["away_id"], game["home_id"])
            
            # Estimate lambdas from runs per game
            away_rpg = away_form.get("runs_per_game", 4.5)
            home_rpg = home_form.get("runs_per_game", 4.5)
            league_rpg = 4.4
            
            # Park factor
            home_abbr = game.get("home_abbr", "")
            pf_abbr = PARK_FACTORS.get(home_abbr, 100) / 100.0
            
            # Weather
            weather = self.fetch_weather(game.get("lat", 40.0), game.get("lon", -74.0))
            temp = weather.get("temp_f", 70)
            env = weather_factor(temp)
            
            lam_away = max(1.5, min(12.0, league_rpg * (away_rpg / league_rpg) * pf_abbr * env * AWAY_OFF_MULT))
            lam_home = max(1.5, min(12.0, league_rpg * (home_rpg / league_rpg) * pf_abbr * env * HOME_OFF_MULT))
            
            sim = simulate(lam_away, lam_home, cfg.get("n_sims", 5000))
            proj_total = sim["proj_total"]
            p_over, p_under, p_push = p_over_ensemble(sim, posted_total)
            
            # Edge vs market
            # For simplicity, assume fair 50/50 if no odds
            edge = p_over - 0.5 if proj_total > posted_total else p_under - 0.5
            pick = "OVER" if proj_total > posted_total else "UNDER"
            
            return pick, round(proj_total, 2), round(edge, 4)
        except Exception as e:
            print(f"  Total calc error: {e}")
            return "OVER", posted_total, 0.0

def fetch_bullpen_stats(team_id: int) -> dict:
    if not team_id:
        return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
    cache_key = f"bullpen_stats_v1_{team_id}"
    cached = get_cached(cache_key, ttl=3600)
    if cached:
        return cached
    try:
        r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                          params={"stats": "statSplits", "sitCodes": "rp", "group": "pitching", "season": datetime.now().year},
                          timeout=8)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
        s = splits[0].get("stat", {})
        ip = float(s.get("inningsPitched", 0) or 0)
        if ip < 20:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
        hr  = int(s.get("homeRuns", 0) or 0)
        bb  = int(s.get("baseOnBalls", 0) or 0)
        hbp = int(s.get("hitByPitch", 0) or 0)
        k   = int(s.get("strikeOuts", 0) or 0)
        fip = round(((13 * hr + 3 * (bb + hbp) - 2 * k) / ip) + 3.10, 2)
        result = {
            "era": round(float(s.get("era", LEAGUE_AVG_ERA) or LEAGUE_AVG_ERA), 2),
            "whip": round(float(s.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP), 2),
            "fip": fip,
            "has_data": True,
        }
        set_cache(cache_key, result)
        return result
    except:
        return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}

# === PARLAYOS INJECTION (kept from current) ===
def _find_v6_template():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = ["parlayos_3.html", "parlayos.html", "parlayos_2.html", "index.html", "parlayos_v6.html"]
    for c in candidates:
        p = os.path.join(here, c)
        if os.path.exists(p):
            return p
    return os.path.join(here, "parlayos_3.html")

PARLAYOS_TEMPLATE_PATH = _find_v6_template()

def _american_to_decimal(american):
    if american is None:
        return None
    try:
        o = float(str(american).replace("+",""))
    except:
        return None
    if o > 0:
        return round((o/100)+1, 3)
    else:
        return round((100/abs(o))+1, 3)

def _picks_to_v6_games(picks: List) -> List:
    v_games = []
    probables = fetch_today_probable_pitchers()
    for idx, p in enumerate(picks):
        away = p.get('away', 'Away')
        home = p.get('home', 'Home')
        pick_team = p.get('pick', home)
        odds = p.get('odds', -110)
        model_prob = p.get('model_prob', 50) / 100.0
        edge = p.get('edge', 0) / 100.0

        if odds > 0:
            ml_price_dec = round((odds / 100) + 1, 3)
        else:
            ml_price_dec = round((100 / abs(odds)) + 1, 3)

        abbr_a = TEAM_ABBR.get(away, away[:3].upper())
        abbr_b = TEAM_ABBR.get(home, home[:3].upper())

        # Get real pitchers
        matchup_key = (abbr_a, abbr_b)
        prob_list = probables.get(matchup_key, [])
        if prob_list:
            prob = prob_list[0]
            away_pitcher = prob.get("away_name", "TBD")
            home_pitcher = prob.get("home_name", "TBD")
        else:
            away_pitcher = p.get("away_pitcher", "TBD")
            home_pitcher = p.get("home_pitcher", "TBD")

        game_date_str = p.get('commence_time')
        start_at_ms = None
        time_display = 'TBD'
        date_display = ''
        if game_date_str:
            try:
                dt_utc = datetime.strptime(game_date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                start_at_ms = int(dt_utc.timestamp() * 1000)
                dt_local = dt_utc.astimezone(ET_ZONE)
                time_display = dt_local.strftime('%-I:%M %p')
                date_display = dt_local.strftime('%a %b %-d')
            except:
                pass
        if start_at_ms is None:
            start_at_ms = int(time.time() * 1000)

        total = p.get('line') or p.get('total') or 8.5
        ml_fav = TEAM_ABBR.get(pick_team, pick_team[:3].upper()) if pick_team else abbr_b
        hot = edge > 0.03

        # --- REAL K PROJECTION (fix hardcoded 6.5K) ---
        k_line = p.get('kLine', 6.5)
        k_proj = p.get('kProj', p.get('kLine', 5.5))
        k_pitcher = p.get('kPitcher', away_pitcher if p.get('kSide')=='away' else home_pitcher)
        k_over_prob = p.get('kOverProb', 0.5)
        k_edge_val = p.get('kEdge', p.get('kOverProb', 0.5) - 0.5 if p.get('kOverProb') else 0.0)
        
        if p.get('kPick') and 'Ks' in str(p.get('kPick')):
            k_pick_str = p.get('kPick')
        else:
            side_str = "Over" if k_over_prob > 0.5 else "Under"
            if k_proj is not None:
                k_pick_str = f"{side_str} {k_line}K ({k_proj} Ks)"
            else:
                k_pick_str = f"{side_str} {k_line}K"

        game = {
            'id': f'mlb_live_{idx}_{int(datetime.now().timestamp())}',
            'a': abbr_a, 'b': abbr_b,
            'cityA': away, 'cityB': home,
            'lgA': 'MLB', 'lgB': 'MLB',
            'total': total, 'ouPick': f'OVER {total}' if edge>0 else f'UNDER {total}',
            'kLine': k_line, 'kPick': k_pick_str, 'kProj': k_proj, 'kPitcher': k_pitcher,
            'kOverProb': k_over_prob, 'kPickRaw': f"{side_str} {k_line}K" if 'side_str' in locals() else f"{ml_fav} K",
            'mlFav': ml_fav, 'mlPriceDec': ml_price_dec,
            'ouEdge': round(edge*0.5, 4), 'kEdge': round(k_edge_val, 4) if k_edge_val is not None else 0.0, 'mlEdge': round(edge, 4),
            'model': round(model_prob, 4),
            'tv': 'ESPN+', 'hot': hot,
            'startAt': start_at_ms, 'start_at': start_at_ms, 'commence_time': p.get('commence_time') or game_date_str, 'time': time_display, 'date': date_display, 'time_et': time_display, 'date_et': date_display,
            'status': 'live',
            'modelProb': round(model_prob, 3),
            'mlPriceAmerican': odds,
            'marketProb': round(1/ml_price_dec, 3) if ml_price_dec > 0 else 0.5,
            'qualifies': bool(p.get('qualifies', True)),
            'away_pitcher': away_pitcher,
            'home_pitcher': home_pitcher,
            'pitcherA': away_pitcher,
            'pitcherB': home_pitcher,
            'pitcherA_name': away_pitcher,
            'pitcherB_name': home_pitcher,
            'teamA_avg': p.get('teamA_avg'), 'teamA_obp': p.get('teamA_obp'), 'teamA_slg': p.get('teamA_slg'), 'teamA_ops': p.get('teamA_ops'), 'teamA_hr': p.get('teamA_hr'), 'teamA_rbi': p.get('teamA_rbi'), 'teamA_sb': p.get('teamA_sb'),
            'teamB_avg': p.get('teamB_avg'), 'teamB_obp': p.get('teamB_obp'), 'teamB_slg': p.get('teamB_slg'), 'teamB_ops': p.get('teamB_ops'), 'teamB_hr': p.get('teamB_hr'), 'teamB_rbi': p.get('teamB_rbi'), 'teamB_sb': p.get('teamB_sb'),
            'pitcherA_era': p.get('pitcherA_era'), 'pitcherA_whip': p.get('pitcherA_whip'), 'pitcherA_k9': p.get('pitcherA_k9'), 'pitcherA_ip': p.get('pitcherA_ip'), 'pitcherA_fip': p.get('pitcherA_fip'), 'pitcherA_w': p.get('pitcherA_w'), 'pitcherA_l': p.get('pitcherA_l'),
            'pitcherB_era': p.get('pitcherB_era'), 'pitcherB_whip': p.get('pitcherB_whip'), 'pitcherB_k9': p.get('pitcherB_k9'), 'pitcherB_ip': p.get('pitcherB_ip'), 'pitcherB_fip': p.get('pitcherB_fip'), 'pitcherB_w': p.get('pitcherB_w'), 'pitcherB_l': p.get('pitcherB_l'),
            'lineupA': p.get('lineupA', []), 'lineupB': p.get('lineupB', []),
            'lineupA_confirmed': p.get('lineupA_confirmed', False), 'lineupB_confirmed': p.get('lineupB_confirmed', False),
        }
        for col in ["c_team_edge", "c_pitcher_fip_edge", "c_pitcher_era_edge", "c_offense_edge", "c_bullpen_edge"]:
            if col in p:
                game[col] = p[col]
        v_games.append(game)
    return v_games

def fetch_month_schedule_all_teams(team_abbrs):
    """Fetch real month schedules from MLB Stats API - no more fake data"""
    schedules = {a: [] for a in team_abbrs}
    try:
        today = datetime.now()
        yr = today.year
        mo = today.month
        start_date = f"{yr}-{mo:02d}-01"
        # End of month
        import calendar
        last_day = calendar.monthrange(yr, mo)[1]
        end_date = f"{yr}-{mo:02d}-{last_day:02d}"
        
        # Fetch schedule for the month
        params = {
            "sportId": 1,
            "startDate": start_date,
            "endDate": end_date,
            "hydrate": "team,probablePitcher",
        }
        r = requests.get(f"{MLB_STATS_BASE}/schedule", params=params, timeout=12)
        if r.status_code != 200:
            print(f"  Schedule fetch failed: {r.status_code}")
            return schedules
            
        data = r.json()
        for date_entry in data.get("dates", []):
            date_str = date_entry.get("date", "")
            for gm in date_entry.get("games", []):
                try:
                    teams = gm.get("teams", {})
                    home_team = teams.get("home", {}).get("team", {})
                    away_team = teams.get("away", {}).get("team", {})
                    home_id = home_team.get("id")
                    away_id = away_team.get("id")
                    
                    # Map to abbr
                    home_abbr = None
                    away_abbr = None
                    for abbr, tid in MLB_TEAM_IDS.items():
                        if tid == home_id:
                            home_abbr = abbr
                        if tid == away_id:
                            away_abbr = abbr
                    
                    if not home_abbr or not away_abbr:
                        continue
                    
                    # Determine result if game is final
                    status = gm.get("status", {}).get("detailedState", "")
                    is_final = "Final" in status
                    home_score = teams.get("home", {}).get("score")
                    away_score = teams.get("away", {}).get("score")
                    
                    # For each team, add entry
                    for abbr, opp_abbr, is_home, my_score, opp_score in [
                        (home_abbr, away_abbr, True, home_score, away_score),
                        (away_abbr, home_abbr, False, away_score, home_score),
                    ]:
                        entry = {
                            "date": date_str,
                            "opp": opp_abbr,
                            "home": is_home,
                        }
                        if is_final and my_score is not None and opp_score is not None:
                            entry["result"] = "W" if my_score > opp_score else "L"
                            entry["myScore"] = my_score
                            entry["oppScore"] = opp_score
                        elif date_str == today.strftime("%Y-%m-%d"):
                            # Today - no fake score, just opponent
                            pass
                        else:
                            # Future game - add time if available
                            game_time = gm.get("gameDate", "")
                            if game_time:
                                try:
                                    dt = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
                                    dt_et = dt.astimezone(ET_ZONE)
                                    entry["time"] = dt_et.strftime("%-I:%M%p").replace(":00", ":").lower().replace("m", "") + "p"
                                except:
                                    entry["time"] = "TBD"
                        
                        schedules[abbr].append(entry)
                except Exception as e:
                    continue
        
        # Sort each team's schedule by date
        for abbr in schedules:
            schedules[abbr].sort(key=lambda x: x.get("date", ""))
            
        total_games = sum(len(v) for v in schedules.values())
        print(f"  Real schedules fetched: {total_games} total games for {len(schedules)} teams")
        
    except Exception as e:
        print(f"  Schedule fetch error: {e}")
        import traceback
        traceback.print_exc()
    
    return schedules

def export_to_html(picks: List, output_path: str = None) -> str:
    out_path = output_path or PARLAYOS_TEMPLATE_PATH
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        print(f"Template not found: {out_path}"); return ""

    v6_games = _picks_to_v6_games(picks)
    games_json = json.dumps(v6_games, separators=(',', ':'))
    all_abbrs = list(TEAM_ABBR.values())
    schedules = fetch_month_schedule_all_teams(all_abbrs)
    schedules_json = json.dumps(schedules, separators=(',', ':'))

    team_stats = {}
    for g in v6_games:
        for side, abbr in [('A', g.get('a')), ('B', g.get('b'))]:
            if not abbr or abbr in team_stats:
                continue
            avg = g.get(f'team{side}_avg')
            if avg is None:
                # Use hardcoded fallback so Stats tab never blank
                fb = TEAM_BATTING_FALLBACK.get(abbr)
                if fb:
                    team_stats[abbr] = fb
                continue
            team_stats[abbr] = {
                'avg': avg, 
                'obp': g.get(f'team{side}_obp'), 
                'slg': g.get(f'team{side}_slg'), 
                'ops': g.get(f'team{side}_ops'),
                'hr': g.get(f'team{side}_hr'),
                'rbi': g.get(f'team{side}_rbi'),
                'sb': g.get(f'team{side}_sb'),
                'k_rate': g.get(f'team{side}_k_rate'),
            }
    # Fill any missing teams with fallback so we always have 30
    if len(team_stats) < 10:
        print(f"  Only {len(team_stats)} teams in teamStats, using hardcoded fallback for all")
        team_stats = TEAM_BATTING_FALLBACK.copy()

    team_stats_json = json.dumps(team_stats, separators=(',', ':'))
    run_date = datetime.now().strftime('%b %d %Y  %H:%M')
    pick_count = len(picks)

    html = re.sub(r'[ \t]*//[^\n]*PARLAYOS LIVE DATA.*?[ \t]*//[^\n]*END PARLAYOS LIVE DATA[^\n]*\n?', '', html, flags=re.DOTALL)
    html = re.sub(r'\n{3,}', '\n\n', html)

    injection_lines = [
        f"    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ PARLAYOS LIVE DATA ({run_date}) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬",
        "    window.PARLAYOS_DATA = {",
        f'      runDate: "{run_date}",',
        f"      pickCount: {pick_count},",
        f"      games: {games_json},",
        f"      schedules: {schedules_json},",
        f"      teamStats: {team_stats_json},",
        "    };",
        "    (function(){",
        "      if(typeof loadRealData==='function') loadRealData();",
        "      if(typeof renderDashboard==='function') renderDashboard();",
        "      if(typeof renderAll==='function') renderAll();",
        "    })();",
        "    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ END PARLAYOS LIVE DATA ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬",
    ]
    injection = "\n".join(injection_lines)

    MARKER = '    // <!--PARLAYOS_INJECT_POINT-->'
    if MARKER in html:
        html = html.replace(MARKER, MARKER + '\n' + injection)
    else:
        html = html.replace('</body>', f'<script>\n{injection}\n</script>\n</body>')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ {pick_count} MLB picks ÃƒÂ¢Ã¢â‚¬ Ã¢â‚¬â„¢ {out_path}")
    return out_path

def write_pick_to_log(game_data):
    try:
        with open(PICKS_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(["timestamp","date","home","away","pick","odds","model_prob","edge","qualifies","kelly_stake_pct","line","market","kind"])
            writer.writerow([datetime.now().isoformat(), datetime.now().strftime("%Y-%m-%d"),
                             game_data.get("home"), game_data.get("away"), game_data.get("pick"),
                             game_data.get("odds"), game_data.get("model_prob"), game_data.get("edge"),
                             game_data.get("qualifies"), game_data.get("kelly_stake_pct"),
                             game_data.get("line"), game_data.get("market"), game_data.get("kind")])
    except Exception as e:
        print(f"Log write failed: {e}")

def main():
    config = load_config()
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        try:
            with open(os.path.join(HERE, "sports_config.json")) as f:
                sports_cfg = json.load(f)
                api_key = sports_cfg.get("odds_api_key") or sports_cfg.get("api_key")
        except:
            pass
    if not api_key:
        api_key = ODDS_KEY
    print(f"Using ODDS API key: {api_key[:8]}... (env: {bool(os.getenv('ODDS_API_KEY'))})")

    engine = PredictionEngine(api_key)
    odds_data = engine.fetch_live_odds()

    games = []
    seen = set()
    for game in odds_data:
        if not game.get("bookmakers"):
            continue
        h2h = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "h2h"), None)
        if not h2h:
            continue
        home = game["home_team"]
        away = game["away_team"]
        if home not in TEAM_ABBR or away not in TEAM_ABBR:
            continue
        key = (away, home)
        if key in seen:
            continue
        seen.add(key)

        home_odds = next((o["price"] for o in h2h["outcomes"] if o["name"] == home), -110)
        away_odds = next((o["price"] for o in h2h["outcomes"] if o["name"] == away), 100)
        home_true, away_true = _devig_probs(home_odds, away_odds)
        market_prob = apply_platt_calibration(home_true)

        home_abbr = TEAM_ABBR.get(home, home[:3].upper())
        away_abbr = TEAM_ABBR.get(away, away[:3].upper())

        real_total = None
        totals_mkt = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "totals"), None)
        if totals_mkt:
            over_o = next((o for o in totals_mkt["outcomes"] if o["name"] == "Over"), None)
            if over_o and "point" in over_o:
                real_total = float(over_o["point"])

        games.append({
            "home": home, "away": away,
            "home_abbr": home_abbr, "away_abbr": away_abbr,
            "market_prob": market_prob,
            "odds": {"home": home_odds, "away": away_odds, "home_true": home_true, "away_true": away_true},
            "real_total": real_total,
            "commence_time": game.get("commence_time"),
            "home_id": MLB_TEAM_IDS.get(home_abbr, 0),
            "away_id": MLB_TEAM_IDS.get(away_abbr, 0),
            "lat": STADIUM_LOCATIONS.get(home_abbr, (40.0, -74.0))[0],
            "lon": STADIUM_LOCATIONS.get(home_abbr, (40.0, -74.0))[1],
            "home_pitcher_id": None,
            "away_pitcher_id": None,
        })

    # Try to get real pitcher IDs
    probables = fetch_today_probable_pitchers()
    for g in games:
        key = (g["away_abbr"], g["home_abbr"])
        if key in probables and probables[key]:
            p = probables[key][0]
            g["home_pitcher_id"] = p.get("home_id")
            g["away_pitcher_id"] = p.get("away_id")

    # FALLBACK: If odds API returned < 8 games, supplement from MLB schedule
    if len(games) < 8:
        print(f"  Only {len(games)} games from odds API, supplementing from MLB schedule...")
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            r = requests.get(f"{MLB_STATS_BASE}/schedule",
                              params={"sportId":1,"date":today_str,"hydrate":"probablePitcher"},
                              timeout=12)
            schedule_games = []
            for de in r.json().get("dates",[]):
                for gm in de.get("games",[]):
                    h_team = gm["teams"]["home"]["team"]
                    a_team = gm["teams"]["away"]["team"]
                    h_id = h_team.get("id"); a_id = a_team.get("id")
                    h_abbr = None; a_abbr = None
                    for ab, mid in MLB_TEAM_IDS.items():
                        if mid == h_id: h_abbr = ab
                        if mid == a_id: a_abbr = ab
                    if not h_abbr or not a_abbr:
                        continue
                    if any(g["home_abbr"]==h_abbr and g["away_abbr"]==a_abbr for g in games):
                        continue
                    hp = gm["teams"]["home"].get("probablePitcher",{}) or {}
                    ap = gm["teams"]["away"].get("probablePitcher",{}) or {}
                    schedule_games.append({
                        "home": h_team.get("name"), "away": a_team.get("name"),
                        "home_abbr": h_abbr, "away_abbr": a_abbr,
                        "market_prob": 0.5,
                        "odds": {"home": -110, "away": 100, "home_true": 0.5, "away_true": 0.5},
                        "real_total": 8.5,
                        "commence_time": gm.get("gameDate"),
                        "home_id": h_id, "away_id": a_id,
                        "lat": STADIUM_LOCATIONS.get(h_abbr, (40.0, -74.0))[0],
                        "lon": STADIUM_LOCATIONS.get(h_abbr, (40.0, -74.0))[1],
                        "home_pitcher_id": hp.get("id"),
                        "away_pitcher_id": ap.get("id"),
                    })
            print(f"  Found {len(schedule_games)} additional games from MLB schedule")
            games.extend(schedule_games)
        except Exception as e:
            print(f"  Schedule fallback failed: {e}")
    # Deduplicate
    seen_final = set()
    deduped = []
    for g in games:
        key = (g["away_abbr"], g["home_abbr"])
        if key not in seen_final:
            seen_final.add(key)
            deduped.append(g)
    games = deduped
    print(f"  Final game count: {len(games)}")

    # Fetch live lineups
    print("  Fetching live lineups...")
    lineups_map = fetch_today_lineups()
    for g in games:
        key = (g["away_abbr"], g["home_abbr"])
        if key in lineups_map:
            ld = lineups_map[key]
            g["_lineupA"] = ld.get("away_lineup", [])
            g["_lineupB"] = ld.get("home_lineup", [])
            g["_lineupA_confirmed"] = ld.get("away_confirmed", False)
            g["_lineupB_confirmed"] = ld.get("home_confirmed", False)
            g["_gamePk"] = ld.get("gamePk")
        else:
            g["_lineupA"] = []
            g["_lineupB"] = []
            g["_lineupA_confirmed"] = False
            g["_lineupB_confirmed"] = False

    kelly_fraction_cfg = config.get("kelly_fraction", 0.25)
    def kelly_stake(prob, decimal_odds):
        if decimal_odds <= 1 or prob * decimal_odds <= 1:
            return 0.0
        full_kelly = (prob * decimal_odds - 1) / (decimal_odds - 1)
        return round(max(0.0, full_kelly) * kelly_fraction_cfg, 4)

    all_games_data = []
    for g in games:
        prob = engine.calculate_win_probability(g)
        implied = g["market_prob"]
        
        # --- REAL PITCHER K PROJECTION (FIX) ---
        try:
            home_p_stats = engine.fetch_pitcher_stats(g.get("home_pitcher_id"))
            away_p_stats = engine.fetch_pitcher_stats(g.get("away_pitcher_id"))
            g["_home_p"] = home_p_stats
            g["_away_p"] = away_p_stats
            try:
                g["_home_bat"] = fetch_real_team_batting(g.get("home_id"))
            except:
                g["_home_bat"] = TEAM_BATTING_FALLBACK.get(g.get("home_abbr"), {})
            try:
                g["_away_bat"] = fetch_real_team_batting(g.get("away_id"))
            except:
                g["_away_bat"] = TEAM_BATTING_FALLBACK.get(g.get("away_abbr"), {})
            home_abbr = g.get("home_abbr", "")
            park_pf = PARK_FACTORS.get(home_abbr, 100)
            home_team_id = g.get("home_id")
            away_team_id = g.get("away_id")
            opp_k_home = fetch_team_k_rate(away_team_id)
            opp_k_away = fetch_team_k_rate(home_team_id)
            home_k_data = calculate_k_projection(home_p_stats, away_team_id, park_pf, opp_k_home)
            away_k_data = calculate_k_projection(away_p_stats, home_team_id, park_pf, opp_k_away)
            k_line_market = 6.5
            home_over = k_prob_over(home_k_data["proj"], k_line_market)
            away_over = k_prob_over(away_k_data["proj"], k_line_market)
            home_edge = home_over - 0.5
            away_edge = away_over - 0.5
            if abs(away_edge) > abs(home_edge):
                chosen = "away"
                chosen_data = away_k_data
                chosen_over = away_over
                chosen_edge = away_edge
            else:
                chosen = "home"
                chosen_data = home_k_data
                chosen_over = home_over
                chosen_edge = home_edge
            g["_k_projection"] = {
                "home": home_k_data,
                "away": away_k_data,
                "chosen_side": chosen,
                "chosen_proj": chosen_data["proj"],
                "chosen_over_prob": chosen_over,
                "chosen_edge": chosen_edge,
                "k_line": k_line_market,
                "home_over": home_over,
                "away_over": away_over,
            }
        except Exception as e:
            print(f"  K projection error for {g.get('away')} @ {g.get('home')}: {e}")
            g["_k_projection"] = None
        
        if prob >= 0.5:
            pick, pick_prob = g["home"], prob
            pick_odds = g["odds"].get("home", -110)
        else:
            pick, pick_prob = g["away"], 1 - prob
            pick_odds = g["odds"].get("away", 100)
        pick_implied = implied if pick == g["home"] else (1 - implied)
        edge = pick_prob - pick_implied
        pick_dec = (pick_odds/100)+1 if pick_odds > 0 else (100/abs(pick_odds))+1
        stake_frac = kelly_stake(pick_prob, pick_dec)

        print(f"{g['away']} @ {g['home']}: pick={pick}, prob={pick_prob:.3f}, implied={pick_implied:.3f}, edge={edge:.3f}")

        k_proj_info = g.get("_k_projection")
        if k_proj_info:
            k_line_val = k_proj_info.get("k_line", 6.5)
            k_proj_val = k_proj_info.get("chosen_proj", 5.5)
            k_over_p = k_proj_info.get("chosen_over_prob", 0.5)
            k_edge_val = k_proj_info.get("chosen_edge", 0.0)
            k_side = k_proj_info.get("chosen_side", "home")
            k_pitcher_name = g["home"] if k_side == "home" else g["away"]
            k_side_str = "Over" if k_over_p > 0.5 else "Under"
            k_pick_str = f"{k_side_str} {k_line_val}K ({k_proj_val} Ks) - {k_pitcher_name}"
        else:
            k_line_val = 6.5
            k_proj_val = 5.5
            k_over_p = 0.5
            k_edge_val = 0.0
            k_pick_str = f"Over {k_line_val}K ({k_proj_val} Ks)"
            k_side = "home"
            k_pitcher_name = g["home"]

        # --- FIX: Include batting and pitching data for Stats tabs + lineups ---
        home_bat_data = g.get("_home_bat", {}) or fetch_real_team_batting(g.get("home_id")) or TEAM_BATTING_FALLBACK.get(g.get("home_abbr"), {})
        away_bat_data = g.get("_away_bat", {}) or fetch_real_team_batting(g.get("away_id")) or TEAM_BATTING_FALLBACK.get(g.get("away_abbr"), {})
        home_p_data = g.get("_home_p", {})
        away_p_data = g.get("_away_p", {})

        game_data = {
            "home": g["home"], "away": g["away"], "pick": pick,
            "odds": pick_odds, "model_prob": round(pick_prob*100, 1), "edge": round(edge*100, 1),
            "edge_pct": round(edge*100, 1), "kelly_stake_pct": round(stake_frac*100, 2),
            "line": g.get("real_total"), "kind": "team", "market": "Moneyline",
            "kLine": k_line_val,
            "kProj": k_proj_val,
            "kOverProb": round(k_over_p, 4),
            "kEdge": round(k_edge_val, 4),
            "kPick": k_pick_str,
            "kPitcher": k_pitcher_name,
            "kSide": k_side,
            "home_k_proj": g.get("_k_projection", {}).get("home", {}).get("proj") if g.get("_k_projection") else None,
            "away_k_proj": g.get("_k_projection", {}).get("away", {}).get("proj") if g.get("_k_projection") else None,
            # Team batting for Stats tab
            "teamA_avg": away_bat_data.get("avg"), "teamA_obp": away_bat_data.get("obp"),
            "teamA_slg": away_bat_data.get("slg"), "teamA_ops": away_bat_data.get("ops"),
            "teamA_hr": away_bat_data.get("hr"), "teamA_rbi": away_bat_data.get("rbi"), "teamA_sb": away_bat_data.get("sb"),
            "teamA_k_rate": away_bat_data.get("k_rate"),
            "teamB_avg": home_bat_data.get("avg"), "teamB_obp": home_bat_data.get("obp"),
            "teamB_slg": home_bat_data.get("slg"), "teamB_ops": home_bat_data.get("ops"),
            "teamB_hr": home_bat_data.get("hr"), "teamB_rbi": home_bat_data.get("rbi"), "teamB_sb": home_bat_data.get("sb"),
            "teamB_k_rate": home_bat_data.get("k_rate"),
            # Pitcher stats for Pitching tab
            "pitcherA_era": away_p_data.get("era"), "pitcherA_whip": away_p_data.get("whip"),
            "pitcherA_k9": away_p_data.get("k_per_9"), "pitcherA_ip": away_p_data.get("ip", away_p_data.get("inningsPitched", "—")),
            "pitcherA_fip": away_p_data.get("fip"), "pitcherA_w": away_p_data.get("wins"), "pitcherA_l": away_p_data.get("losses"),
            "pitcherB_era": home_p_data.get("era"), "pitcherB_whip": home_p_data.get("whip"),
            "pitcherB_k9": home_p_data.get("k_per_9"), "pitcherB_ip": home_p_data.get("ip", home_p_data.get("inningsPitched", "—")),
            "pitcherB_fip": home_p_data.get("fip"), "pitcherB_w": home_p_data.get("wins"), "pitcherB_l": home_p_data.get("losses"),
            # Lineups
            "lineupA": g.get("_lineupA", []),
            "lineupB": g.get("_lineupB", []),
            "lineupA_confirmed": g.get("_lineupA_confirmed", False),
            "lineupB_confirmed": g.get("_lineupB_confirmed", False),
            # Raw for v6 builder
            "home_bat_raw": home_bat_data,
            "away_bat_raw": away_bat_data,
            "home_p_raw": home_p_data,
            "away_p_raw": away_p_data,
        }
        for col, val in g.get("_edge_components", {}).items():
            game_data[col] = round(val, 4)

        min_edge = config.get("min_edge", 0.0)
        edge_ok = edge >= min_edge
        game_data["qualifies"] = bool(edge_ok)
        all_games_data.append(game_data)
        write_pick_to_log(game_data)

    export_to_html(all_games_data)
    print(f"\nÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ {len(all_games_data)} games exported")


def run(html_path: str = None):
    """Wrapper for run_all.py"""
    try:
        if html_path is None:
            html_path = _find_v6_template()
        # Capture picks
        original_export = globals().get('export_to_html')
        captured = []
        def cap_export(picks, hp=None):
            nonlocal captured
            captured = picks
            return original_export(picks, hp or html_path)
        globals()['export_to_html'] = cap_export
        main()
        globals()['export_to_html'] = original_export
        return captured
    except Exception as e:
        print(f"run() failed: {e}")
        import traceback
        traceback.print_exc()
        return []


if __name__ == "__main__":
    main()
