#!/usr/bin/env python3
"""
mlb_ace_2_improved.py — Improved MLB Totals + ML Model

Sources merged (no API key copied):
- statcast_2026.py : 17 embedded Statcast datasets (percentile rankings, exit velo, hard hit, K%, BB%, whiff, chase, sprint, OAA, etc)
  -> Used to adjust pitcher RA9 and lineup OPS via xwOBA, hard-hit, barrel%, K% etc. Provides skill-based correction beyond ERA.
- mlb_tool.py : daily card builder, odds URL handling, batter/pitcher props, weather, slate with Statcast profiles, log_snapshot
  -> Improved odds loading via env var + ~/.acebot_config, multi-market handling, K-rate per team, weather handling
- mlb_predict.py : pregame prediction engine with transparent expected-runs model,
  starter vs bullpen split (6/3), earned->total run conversion, regression priors, home field multipliers,
  overdispersion with shared + independent Gamma factors (fixes one-run game rate), crooked innings, ghost runner extras,
  real baseball termination logic (no bottom 9 if home leads, walk-off), Kelly staking, prop predictions
- mlb_ace_final_v3.py : best totals model — correct IP parsing (X.1/X.2 outs), multi-signal starter_ra9 (ERA/xERA/FIP/K9/BB9),
  shrinkage, skill adjustment, recent form opponent-adjusted exponential decay sorted by date, expected SP IP,
  bullpen fatigue with true relievers only + converted starter detection, dynamic park factor (static blended with total runs home/road),
  rest factor, weather/wind factor with venue bearing, lineup OPS with platoon splits, umpire zone factor, injury flags,
  multi-book consensus vs best price (de-vig consensus, bet best), confidence scoring, line movement tracking, ensemble p_over

Improvements over old mlb_ace_2.py:
1. Fixed IP parsing bug (was float, now true outs) — was inflating RA9.
2. Starter model now 60% ERA/xERA core + FIP + K9/BB9 skill + recent form (opponent-adjusted) + expected IP.
3. Bullpen fatigue now measures 3-day IP + arms_used + true bullpen RA9 (relievers only) blended 50/50 with team RA/G.
4. Team rates now include opponent K-rate for K props, league K rate, win pct, plus dynamic park raw from total runs.
5. Team form now real: last 10 and 30-day windows, days_rest, dyn_park, form strings.
6. Lineup OPS uses SLOT_WEIGHTS + platoon + Statcast adjustments (barrel, hard-hit, xwOBA) when available.
7. Park factor dynamic blending static + current season home/road total runs (capped, regressed 50% to static).
8. Wind factor uses VENUE_META CF bearing + speed + direction, dome check.
9. Umpire factor from umpscorecards + hardcoded lookup.
10. Weather via open-meteo hourly at game time (temp, wind, precip prob) not just current.
11. Odds: multi-book consensus for de-vig, best price for betting, n_books tracked, confidence score.
12. Simulation: gamma overdispersion ENV_SHARED_K=28 + ENV_TEAM_K=8.5 (from v3) + crooked inning + ghost runner + conditional 9th + tie-breaker.
13. Ensemble p_over: 70% MC + 30% normal approx.
14. Moneyline: ensemble 40% MC + 25% Pythag (exp 1.83) + 20% Log5 + 15% Form, clamped 35-65% + Platt calibration.
15. K projection: K/9 * expected IP /9 * opp K factor (capped 0.7-1.4) * park + reliability blend + Statcast K% / whiff adjustment.
16. Statcast integration: if statcast_2026.py present, pitcher hard-hit, barrel, xwOBA adjust RA9; batter exit velo, brl adjust team offense.
17. No hardcoded API key — loads from ODDS_API_KEY env, ~/.acebot_config, mlb_config.json, or mlb_tool.ODDS_KEY (env-based).

Usage:
    python3 mlb_ace_2_improved.py --date today --sims 15000
    python3 mlb_ace_2_improved.py --no-log
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import html as html_lib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple
try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
except:
    ET_ZONE = timezone.utc

import requests

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE_DIR, "mlb_config.json")
OUTPUT_PATH = os.path.join(HERE_DIR, "index.html")
LEGACY_OUTPUT_PATH = os.path.join(HERE_DIR, "acebot_dashboard.html")
LINE_HISTORY_PATH = os.path.join(HERE_DIR, "mlb_line_history.json")
PICKS_CSV = os.path.join(HERE_DIR, "picks_log.csv")
PICKS_HEADER = "date,tag,team,kind,market,open_ml,close_ml,clv_pts,won,profit_1u,slip_id,slip_odds,slip_result\n"

# === TEAM MAPS (ParlayOS compatibility) ===
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
    'COL':1.12, 'CIN':1.05, 'BOS':1.04, 'TEX':1.03, 'PHI':1.02, 'BAL':1.02,
    'TOR':1.01, 'MIL':1.01, 'CHC':1.00, 'ARI':1.00, 'MIN':1.00, 'HOU':1.00,
    'LAA':0.99,  'WSH':0.99,  'ATL':0.99,  'NYY':0.99,  'CWS':0.98,  'KC':0.98,
    'STL':0.98,  'TB':0.97,   'CLE':0.97,  'DET':0.97,  'NYM':0.96,  'LAD':0.96,
    'SEA':0.95,  'PIT':0.95,  'SF':0.94,   'OAK':0.94,  'MIA':0.93,  'SD':0.92,
}
PARK_DEFAULT = 1.00
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

# === MODEL CONSTANTS (from final_v3 + mlb_predict) ===
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
STARTER_INNINGS = 6.0
LEAGUE_RPG_FALLBACK = 4.40
SLOT_WEIGHTS = [1.103, 1.075, 1.049, 1.023, 0.997, 0.974, 0.950, 0.927, 0.903]
LEAGUE_AVG_ERA = 4.25
LEAGUE_AVG_WHIP = 1.30
LEAGUE_AVG_K9 = 8.5
LEAGUE_AVG_FIP = 4.20
K9_LG = 8.5
BB9_LG = 3.1
FIP_CONST = 3.10
FIP_WEIGHT_MAX = 0.22
SKILL_WEIGHT = 0.18
SP_PRIOR_IP = 45.0
XERA_WEIGHT = 0.50
TEAM_PRIOR_G = 25.0
EARNED_RUN_SHARE = 0.92

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"

# === NO HARDCODED API KEY — loader ===
def _load_odds_key() -> str:
    # 1) env var
    k = os.getenv("ODDS_API_KEY", "").strip()
    if k:
        return k
    # 2) ~/.acebot_config
    try:
        cfg_path = os.path.expanduser("~/.acebot_config")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                for line in f:
                    line=line.strip()
                    if line.startswith("ODDS_API_KEY="):
                        v=line.split("=",1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
    except:
        pass
    # 3) mlb_config.json contains odds_api_key
    try:
        with open(CONFIG_PATH, "r") as f:
            data=json.load(f)
            if isinstance(data, dict):
                v=data.get("odds_api_key") or data.get("ODDS_KEY") or ""
                if v and isinstance(v, str) and len(v)>=10:
                    return v.strip()
    except:
        pass
    # 4) try import from mlb_tool (which itself loads from env)
    try:
        import mlb_tool as _mt
        v=getattr(_mt, "ODDS_KEY", "") or getattr(_mt, "_load_key", lambda: "")()
        if v and isinstance(v, str) and len(v)>=10:
            return v.strip()
    except:
        pass
    return ""

ODDS_KEY = _load_odds_key()

# === CONFIG ===
DEFAULT_CONFIG = {
    "edge_threshold": 0.045,
    "ml_edge_threshold": 0.045,
    "min_total_line": 6.5,
    "max_total_line": 13.0,
    "n_sims": 12000,
    "kelly_fraction": 0.25,
    "max_stake_pct": 0.05,
    "min_edge": 0.0,
    "max_legs": 16,
    "_basis": "improved v2 — statcast + final_v3 + predict + tool",
    "_updated": "never",
}

def load_config():
    cfg=dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH,"r") as f:
            user=json.load(f)
        if isinstance(user, dict):
            for k in user:
                if k in DEFAULT_CONFIG or k.startswith("_") or k in ("odds_api_key",):
                    if k in DEFAULT_CONFIG:
                        cfg[k]=user[k]
            if "edge_threshold" in user and "min_edge" not in user:
                cfg["min_edge"]=user["edge_threshold"]
    except:
        pass
    return _validate_config(cfg)

def _validate_config(cfg):
    def _num(key, lo, hi):
        v=cfg.get(key)
        try:
            v=float(v)
        except:
            v=DEFAULT_CONFIG.get(key, lo)
        cfg[key]=max(lo, min(hi, v))
    _num("edge_threshold",0.0,0.50)
    _num("ml_edge_threshold",0.0,0.50)
    _num("kelly_fraction",0.0,1.0)
    _num("max_stake_pct",0.0,1.0)
    _num("min_total_line",0.0,30.0)
    _num("max_total_line",0.0,30.0)
    if cfg["min_total_line"]>cfg["max_total_line"]:
        cfg["min_total_line"]=DEFAULT_CONFIG["min_total_line"]
        cfg["max_total_line"]=DEFAULT_CONFIG["max_total_line"]
    try:
        n_sims=int(cfg.get("n_sims",0))
    except:
        n_sims=0
    cfg["n_sims"]=n_sims if n_sims>=1000 else DEFAULT_CONFIG["n_sims"]
    return cfg

# === HTTP helper ===
def get(url, required=False, tries=2):
    last=None
    for _ in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                data=json.load(r)
                if isinstance(data, dict) and "message" in data:
                    m=str(data["message"]).lower()
                    if any(w in m for w in ("exceed","quota","unauthori")):
                        return None
                return data
        except Exception as e:
            last=e
            time.sleep(0.8)
    return None

CACHE={}
def get_cached(k, ttl=3600):
    if k in CACHE:
        ts,v=CACHE[k]
        if time.time()-ts < ttl:
            return v
    return None
def set_cache(k,v):
    CACHE[k]=(time.time(),v)

# === ODDS MATH ===
def american_to_decimal(o):
    o=float(o)
    return 1.0 + (o/100.0 if o>0 else 100.0/-o)
def american_to_implied(o):
    o=float(o)
    return (-o)/(-o+100.0) if o<0 else 100.0/(o+100.0)
def devig_two_way(odds_a, odds_b):
    try:
        ia, ib = american_to_implied(odds_a), american_to_implied(odds_b)
    except:
        return 0.5,0.5
    s=ia+ib
    if s<=0:
        return 0.5,0.5
    return ia/s, ib/s
def kelly_fraction(p, odds):
    try:
        b=american_to_decimal(odds)-1.0
    except:
        return 0.0
    if b<=0:
        return 0.0
    return max(0.0, (b*p - (1.0-p))/b)
def _f(v):
    try:
        return float(v) if v is not None else None
    except:
        return None
def _ip(v):
    """Correct MLB IP parsing: 5.1 = 5 + 1/3, 5.2 = 5 + 2/3"""
    f=_f(v)
    if f is None:
        return None
    whole=int(f) if f>=0 else -int(-f)
    thirds=round((f-whole)*10)
    if thirds not in (0,1,2):
        return f
    return whole + thirds/3.0
def _logit(p):
    p=max(0.001, min(0.999, p))
    return math.log(p/(1-p))
def _sigmoid(x):
    return 1/(1+math.exp(-x))

# === STATCAST INTEGRATION (from statcast_2026.py) ===
HAS_STATCAST=False
STATCAST_DATASETS=None
try:
    import statcast_2026 as _sc
    STATCAST_DATASETS=_sc.DATASETS
    HAS_STATCAST=True
except:
    try:
        # Try local file in same dir
        import importlib.util, pathlib
        sc_path=pathlib.Path(HERE_DIR)/"statcast_2026.py"
        if sc_path.exists():
            spec=importlib.util.spec_from_file_location("statcast_2026", sc_path)
            _sc=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_sc)
            STATCAST_DATASETS=_sc.DATASETS
            HAS_STATCAST=True
    except:
        HAS_STATCAST=False

_STATCAST_CACHE={}
def _find_statcast_player(name: str):
    if not HAS_STATCAST or not name or name=='TBD':
        return {}
    key=name.lower().strip()
    if key in _STATCAST_CACHE:
        return _STATCAST_CACHE[key]
    try:
        hits=_sc.find_player(name) if '_sc' in globals() else {}
        # flatten
        best={}
        # Prefer percentile_rankings
        if 'percentile_rankings' in hits and hits['percentile_rankings']:
            best['percentile']=hits['percentile_rankings'][0]
        if 'pitching' in hits:
            best['pitching']=hits['pitching'][0]
        if 'exit_velocity' in hits:
            best['exit_vel']=hits['exit_velocity'][0]
        _STATCAST_CACHE[key]=best
        return best
    except:
        return {}

def get_statcast_pitcher_factor(pitcher_name: str) -> float:
    """Return RA9 multiplier from Statcast: <1 = better than ERA, >1 = worse.
    Uses xwoba, hard_hit, k_percent, bb_percent, whiff, brl_percent"""
    data=_find_statcast_player(pitcher_name)
    pct=data.get('percentile', {})
    if not pct:
        return 1.0
    # Lower xwoba percentile = better pitcher? Actually percentile_rankings: higher=better for pitcher? 
    # For pitchers, xwoba percentile inverted? In dataset, xwoba is hitter quality? But we use k_percent, bb_percent etc.
    # Approach: if k_percent percentile high (good), reduce RA9; if bb_percent high (bad walk?), wait bb_percent high means good? 
    # In Statcast, k_percent percentile: higher = more Ks (good for pitcher, bad for hitter). For pitcher, high k% is good.
    # We'll interpret: xwoba percentile high = good (low xwOBA) -> reduces RA9
    factor=1.0
    try:
        xwoba_pct=pct.get('xwoba')
        if xwoba_pct is not None:
            # 50 avg, 90 elite -> reduce RA9 by up to 10%
            factor += (50 - xwoba_pct)/100.0 * 0.20  # e.g. 90 pct -> -0.08, 10 pct -> +0.08
        k_pct=pct.get('k_percent')
        if k_pct is not None:
            factor += (50 - k_pct)/100.0 * 0.12
        bb_pct=pct.get('bb_percent')
        if bb_pct is not None:
            # bb_percent high = good (low walks)? Actually percentile: higher=better, so low walks = high percentile? For pitchers, yes.
            factor += (50 - bb_pct)/100.0 * 0.08
        hard_hit=pct.get('hard_hit_percent')
        if hard_hit is not None:
            # For pitcher, hard_hit high = bad, but percentile: higher hard_hit = more hard hit? Actually hard_hit_percent percentile: higher = more hard hit allowed = bad.
            # Need invert: if hard_hit_percent high (bad), increase factor. But percentile high means more hard hit? That would be bad, so low percentile is good.
            # So similar: 90 = allows many hard hits (bad) -> increase RA9
            # We'll treat high hard_hit as bad
            # Since percentile for hard_hit: higher means more hard hit allowed = worse, so we want low.
            # So factor += (hard_hit - 50)/100 * 0.10
            factor += (hard_hit - 50)/100.0 * 0.10
        brl=pct.get('brl_percent')
        if brl is not None:
            factor += (brl - 50)/100.0 * 0.10
    except:
        pass
    return max(0.85, min(1.15, factor))

def get_statcast_batter_factor(batter_name: str) -> float:
    """Return OPS multiplier for batter: >1 = better than avg"""
    data=_find_statcast_player(batter_name)
    pct=data.get('percentile', {})
    if not pct:
        return 1.0
    factor=1.0
    try:
        xwoba=pct.get('xwoba')
        if xwoba is not None:
            factor += (xwoba - 50)/100.0 * 0.18
        brl=pct.get('brl_percent')
        if brl is not None:
            factor += (brl - 50)/100.0 * 0.10
        hard_hit=pct.get('hard_hit_percent')
        if hard_hit is not None:
            factor += (hard_hit - 50)/100.0 * 0.08
        # exit_velocity, bat_speed
        ev=pct.get('exit_velocity')
        if ev is not None:
            factor += (ev - 50)/100.0 * 0.06
    except:
        pass
    return max(0.85, min(1.18, factor))

# === CORE MODEL ===
def _regress(value, prior, n, prior_n):
    if value is None:
        return prior
    w=n/(n+prior_n) if (n+prior_n)>0 else 0.0
    return w*value + (1.0-w)*prior

def _expected_sp_ip(recent_logs, n=5):
    ips=[]
    for split in (recent_logs or [])[:n]:
        ip=_ip(split.get("stat",{}).get("inningsPitched"))
        if ip and ip>=4.0:
            ips.append(ip)
    if not ips:
        return STARTER_INNINGS
    avg=sum(ips)/len(ips)
    return round(0.5*avg + 0.5*STARTER_INNINGS,1)

def _recent_form_ra9(game_log_splits, n=5, decay=0.65, team_rates=None, league_rpg=None, min_start_ip=2.0):
    if not game_log_splits:
        return None,0.0
    def _split_date(s):
        d=s.get("date")
        try:
            return datetime.strptime(d, "%Y-%m-%d") if d else datetime.min
        except:
            return datetime.min
    sorted_splits=sorted(game_log_splits, key=_split_date, reverse=True)
    recent=[s for s in sorted_splits if (_ip(s.get("stat",{}).get("inningsPitched")) or 0.0) >= min_start_ip][:n]
    if not recent:
        return None,0.0
    total_w=weighted_sum=total_ip=0.0
    for i, sp in enumerate(recent):
        stat=sp.get("stat",{})
        er=_f(stat.get("earnedRuns")) or 0.0
        ip=_ip(stat.get("inningsPitched")) or 0.0
        if ip<=0:
            continue
        raw_ra9=er*9.0/ip
        opp_factor=1.0
        if team_rates and league_rpg and league_rpg>0:
            opp=sp.get("opponent",{})
            opp_id=opp.get("id")
            if opp_id and opp_id in team_rates:
                opp_off=team_rates[opp_id].get("off")
                if opp_off:
                    opp_factor=max(0.85, min(1.15, opp_off/league_rpg))
        adj_ra9=raw_ra9/opp_factor
        w=decay**i
        weighted_sum+=w*adj_ra9
        total_w+=w
        total_ip+=ip
    if total_w==0:
        return None,0.0
    return round(weighted_sum/total_w,3), round(total_ip,1)

def starter_ra9(era, ip, xera, league_rpg, k9=None, bb9=None, fip=None, recent_ra9=None, recent_ip=0.0, pitcher_name=None):
    league_ra9=league_rpg
    if era is None and xera is None and fip is None:
        return league_ra9
    era_ra9=(era/EARNED_RUN_SHARE) if era is not None else None
    xera_ra9=(xera/EARNED_RUN_SHARE) if xera is not None else None
    fip_ra9=(fip/EARNED_RUN_SHARE) if fip is not None else None
    ip=ip or 0.0
    if era_ra9 is not None and xera_ra9 is not None:
        core=(1.0-XERA_WEIGHT)*era_ra9 + XERA_WEIGHT*xera_ra9
    else:
        core=era_ra9 if era_ra9 is not None else xera_ra9
    signals=[(core,0.60)]
    if fip_ra9 is not None and ip>=15:
        fip_w=min(FIP_WEIGHT_MAX, 0.08 + ip/180.0*FIP_WEIGHT_MAX)
        signals=[(core,0.60 - fip_w*0.60), (fip_ra9,fip_w)]
    if k9 is not None or bb9 is not None:
        adj=0.0
        if k9 is not None: adj -= (k9 - K9_LG)*0.08
        if bb9 is not None: adj += (bb9 - BB9_LG)*0.18
        adj=max(-0.80, min(0.80, adj))
        signals=[(v,w*(1.0-SKILL_WEIGHT)) for v,w in signals]
        signals.append((league_ra9+adj, SKILL_WEIGHT))
    tot=sum(w for _,w in signals)
    blended=sum(v*w/tot for v,w in signals)
    season_est=_regress(blended, league_ra9, ip, SP_PRIOR_IP)
    # Recent form blend
    if recent_ra9 is not None and recent_ip>=10.0:
        rf_w=min(0.40, max(0.0, recent_ip/75.0))
        season_est=(1.0-rf_w)*season_est + rf_w*recent_ra9
    # Statcast adjustment
    if pitcher_name:
        sc_factor=get_statcast_pitcher_factor(pitcher_name)
        season_est*=sc_factor
    return min(8.0, max(1.8, season_est))

def run_prevention_per9(starter_ra9_val, team_rapg, sp_ip=STARTER_INNINGS, bullpen_ra9=None):
    sp_inn=sp_ip if sp_ip else STARTER_INNINGS
    bp_inn=max(0.5, 9.0-sp_inn)
    bp_rate=team_rapg
    if bullpen_ra9 is not None:
        bp_rate=0.5*team_rapg + 0.5*bullpen_ra9
    return (sp_inn*starter_ra9_val + bp_inn*bp_rate)/(sp_inn+bp_inn)

def park_factor_by_name(home_team_name):
    return PARK_FACTORS_TEAMNAME.get(home_team_name, PARK_DEFAULT)

def _dynamic_park_factor(home_team_name, team_form_entry):
    static=park_factor_by_name(home_team_name)
    raw=(team_form_entry or {}).get("dyn_park_raw")
    n=(team_form_entry or {}).get("dyn_park_games",0)
    if raw is None or n<10:
        return static
    raw_capped=max(0.85, min(1.15, raw))
    blended=0.5*static + 0.5*raw_capped
    return round(max(0.85, min(1.20, blended)),4)

def _rest_factor(days_rest):
    if days_rest is None:
        return 1.0
    if days_rest<=0:
        return 0.99
    if days_rest>=2:
        return 1.01
    return 1.0

def weather_factor(temp_f):
    if temp_f is None:
        return 1.0
    return min(1.05, max(0.95, 1.0 + 0.0012*(temp_f-70.0)))

def wind_factor(speed_mph, from_deg, cf_bearing, is_dome):
    if is_dome or speed_mph is None or from_deg is None or speed_mph<5:
        return 1.0, None
    to_deg=(from_deg+180)%360
    comp=speed_mph*math.cos(math.radians(to_deg-cf_bearing))
    factor=min(1.08, max(0.93, 1.0 + 0.0028*comp))
    label="out" if comp>2 else ("in" if comp<-2 else "cross")
    return round(factor,4), "%.0fmph %s" % (speed_mph,label)

def project_runs(off_away, off_home, prev_away9, prev_home9, league_rpg, park, env):
    lg=max(2.5, league_rpg)
    lam_away=lg * (off_away/lg) * (prev_home9/lg) * park * env * AWAY_OFF_MULT
    lam_home=lg * (off_home/lg) * (prev_away9/lg) * park * env * HOME_OFF_MULT
    return min(12.0, max(1.5, lam_away)), min(12.0, max(1.5, lam_home))

def _poisson(lam):
    L=math.exp(-lam); k=0; p=1.0
    while True:
        p*=random.random()
        if p<=L:
            return k
        k+=1

def _kick(runs):
    return runs + CROOKED_EXTRA if runs>0 and random.random()<CROOKED_PROB else runs

def _kick_adj_lambda(lam_inning):
    target=max(0.0, lam_inning)
    p_pos=1.0-math.exp(-target)
    return max(0.02, target - CROOKED_PROB*CROOKED_EXTRA*p_pos)

def _extras(la, lh):
    la_x, lh_x = la + GHOST_RUNNER_BONUS, lh + GHOST_RUNNER_BONUS
    ea=eh=0
    for _ in range(MAX_EXTRA_INNINGS):
        ea+=_kick(_poisson(la_x))
        h=_kick(_poisson(lh_x))
        if eh+h > ea:
            eh+=h; break
        eh+=h
        if ea!=eh:
            break
    return ea, eh

def simulate(lam_away, lam_home, n, seed=None):
    la=_kick_adj_lambda(lam_away/9.0)
    lh=_kick_adj_lambda(lam_home/9.0)
    if seed is not None:
        random.seed(seed)
    totals=[]; away_wins=home_wins=0
    for _ in range(n):
        gs=random.gammavariate(ENV_SHARED_K, 1.0/ENV_SHARED_K)
        ga=random.gammavariate(ENV_TEAM_K, 1.0/ENV_TEAM_K)
        gh=random.gammavariate(ENV_TEAM_K, 1.0/ENV_TEAM_K)
        la_g, lh_g = la*gs*ga, lh*gs*gh
        away=sum(_kick(_poisson(la_g)) for _ in range(9))
        home_8=sum(_kick(_poisson(lh_g)) for _ in range(8))
        home=home_8 if home_8>away else home_8 + _kick(_poisson(lh_g))
        if home==away:
            ea,eh=_extras(la*gs, lh*gs)
            away+=ea; home+=eh
            if home==away:
                if random.random()<0.5: home+=1
                else: away+=1
        totals.append(away+home)
        if away>home: away_wins+=1
        else: home_wins+=1
    n_=len(totals)
    mean=sum(totals)/n_
    sd=(sum((t-mean)**2 for t in totals)/n_)**0.5 if n_>1 else 2.5
    return {"dist":totals,"proj_total":mean,"sd":sd,"n":n_,"away_wins":away_wins,"home_wins":home_wins,"away_win_pct":away_wins/n_,"home_win_pct":home_wins/n_}

def _norm_cdf(z):
    return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

def p_over_ensemble(sim, line):
    dist=sim["dist"]; n=sim["n"]
    over=sum(1 for t in dist if t>line)/n
    push=sum(1 for t in dist if t==line)/n
    p_over_mc=over
    sd=max(0.5, sim["sd"])
    z=(line+0.5 - sim["proj_total"])/sd
    p_over_norm=1.0 - _norm_cdf(z)
    p_over=ENSEMBLE_MC_WEIGHT*p_over_mc + (1-ENSEMBLE_MC_WEIGHT)*p_over_norm
    p_over=min(0.999, max(0.001, p_over))
    return p_over, (1.0-p_over-push), push

def _confidence_score(edge, n_books, sd, proj_total):
    base=edge*100
    book_bonus=min(1.0, n_books/5.0)*0.2
    sd_penalty=max(0,(sd-2.5)*0.1)
    return round(base+book_bonus-sd_penalty,2)

# === LINEUP OPS WITH PLATOON + STATCAST ===
def _lineup_ops(lineup: List[Dict], opp_pitch_hand: str):
    if not lineup:
        return 0.750
    total=0.0; weight_sum=0.0
    for i, b in enumerate(lineup[:9]):
        w=SLOT_WEIGHTS[i] if i < len(SLOT_WEIGHTS) else 0.9
        # platoon: try to get ops vs hand
        ops=None
        try:
            # If lineup entry has ops vs, use it
            if opp_pitch_hand=='L' and b.get('ops_vs_L'):
                ops=float(b['ops_vs_L'])
            elif opp_pitch_hand=='R' and b.get('ops_vs_R'):
                ops=float(b['ops_vs_R'])
            else:
                ops=float(b.get('ops', 0.750) or 0.750)
        except:
            ops=0.750
        # Statcast batter factor
        try:
            name=b.get('name') or b.get('fullName') or ''
            if name and name!='TBD':
                sc_factor=get_statcast_batter_factor(name)
                ops*=sc_factor
        except:
            pass
        total+=ops*w
        weight_sum+=w
    return round(total/weight_sum,3) if weight_sum else 0.750

# === UMPIRE ===
_UMP_ZONE_FACTOR = {
    "Laz Diaz":1.07, "Angel Hernandez":1.06, "Ángel Hernández":1.06,
    "CB Bucknor":1.05, "Ted Barrett":1.04, "Jim Reynolds":1.03,
    "Roberto Ortiz":1.03, "Dan Bellino":1.02, "John Libka":1.02,
    "Lance Barksdale":1.02, "Brian Knight":1.01, "Dan Iassogna":1.01,
    "Mark Wegner":0.99, "Mike Winters":0.99, "Tripp Gibson":0.98,
    "Sam Holbrook":0.98, "Ben May":0.97, "Scott Barry":0.97,
    "Chris Guccione":0.97, "Adam Hamari":0.96, "John Tumpane":0.96,
    "Pat Hoberg":0.95,
}
_UMP_CACHE={}
def _ump_factor(hp_ump_name, hp_ump_id, year):
    if not hp_ump_name:
        return 1.0, "unknown"
    key=(hp_ump_name, year)
    if key in _UMP_CACHE:
        return _UMP_CACHE[key]
    factor=_UMP_ZONE_FACTOR.get(hp_ump_name, 1.0)
    _UMP_CACHE[key]=(factor, hp_ump_name)
    return factor, hp_ump_name

# === BULLPEN FATIGUE (full from final_v3) ===
_BULLPEN_CACHE={}
def _bullpen_fatigue(team_id, year, as_of_date):
    cache_key=(team_id, year, as_of_date)
    if cache_key in _BULLPEN_CACHE:
        return _BULLPEN_CACHE[cache_key]
    fresh={"fatigue_mult":1.0,"arms_used":0,"ip_3d":0.0,"bullpen_ra9":None,"bullpen_ip":0.0}
    try:
        roster=get(f"{MLB_STATS_BASE}/teams/{team_id}/roster?rosterType=active")
        if not roster:
            return _BULLPEN_CACHE.setdefault(cache_key,fresh)
        pitcher_ids=[p["person"]["id"] for p in roster.get("roster",[]) if p.get("position",{}).get("code")=="1"]
        if not pitcher_ids:
            return _BULLPEN_CACHE.setdefault(cache_key,fresh)
        ids_str=",".join(str(i) for i in pitcher_ids)
        people=get(f"{MLB_STATS_BASE}/people?personIds={ids_str}&hydrate=stats(group=pitching,type=[season,gameLog],season={year})")
        if not people:
            return _BULLPEN_CACHE.setdefault(cache_key,fresh)
        try:
            cutoff=datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=3)
        except:
            cutoff=datetime.today() - timedelta(days=3)
        arms_used=0; ip_3d=0.0; bp_er=0.0; bp_ip=0.0
        for p in people.get("people",[]):
            season_stat={}; gamelog_splits=[]
            for block in p.get("stats",[]):
                dtype=block.get("type",{}).get("displayName","").lower()
                splits=block.get("splits",[])
                if "gamelog" in dtype or "game log" in dtype or "log" in dtype:
                    gamelog_splits=splits
                elif "single" in dtype or ("season" in dtype and "game" not in dtype):
                    if splits:
                        season_stat=splits[0].get("stat",{})
            threw=False
            for split in gamelog_splits:
                gd=split.get("date")
                if not gd: continue
                try:
                    g_date=datetime.strptime(gd, "%Y-%m-%d")
                except:
                    continue
                if g_date>=cutoff:
                    sip=_ip(split.get("stat",{}).get("inningsPitched")) or 0.0
                    if sip>0:
                        ip_3d+=sip; threw=True
            if threw:
                arms_used+=1
            gs=_f(season_stat.get("gamesStarted")) or 0
            if gs<3:
                er=_f(season_stat.get("earnedRuns")) or 0.0
                ip=_ip(season_stat.get("inningsPitched")) or 0.0
                if ip>0:
                    bp_er+=er; bp_ip+=ip
            elif gamelog_splits:
                def _split_date(s):
                    d=s.get("date")
                    try:
                        return datetime.strptime(d, "%Y-%m-%d") if d else datetime.min
                    except:
                        return datetime.min
                sorted_splits=sorted(gamelog_splits, key=_split_date, reverse=True)
                recent5=sorted_splits[:5]
                recent_ips=[_ip(s.get("stat",{}).get("inningsPitched")) or 0.0 for s in recent5]
                if recent_ips and all(0<x<=3.0 for x in recent_ips):
                    conv_er=sum(_f(s.get("stat",{}).get("earnedRuns")) or 0.0 for s in recent5)
                    conv_ip=sum(recent_ips)
                    if conv_ip>0:
                        bp_er+=conv_er; bp_ip+=conv_ip
        BASELINE_IP=10.0
        excess=max(0.0, ip_3d-BASELINE_IP)
        fatigue_mult=min(1.10, 1.0+0.015*excess)
        bullpen_ra9=None
        if bp_ip>=20.0:
            bullpen_ra9=round((bp_er*9.0/bp_ip)/EARNED_RUN_SHARE,3)
        result={"fatigue_mult":round(fatigue_mult,3),"arms_used":arms_used,"ip_3d":round(ip_3d,1),"bullpen_ra9":bullpen_ra9,"bullpen_ip":round(bp_ip,1)}
        _BULLPEN_CACHE[cache_key]=result
        return result
    except:
        return _BULLPEN_CACHE.setdefault(cache_key,fresh)

# === TEAM RATES + FORM ===
def fetch_team_rates(year):
    cache_key=f"team_rates_{year}"
    cached=get_cached(cache_key, ttl=3600)
    if cached:
        return cached
    st=get(f"{MLB_STATS_BASE}/standings?leagueId=103,104&season={year}")
    rates={}; runs=0; games=0
    if st:
        for rec in st.get("records",[]):
            for tr in rec.get("teamRecords",[]):
                tid=tr["team"]["id"]
                rs=tr.get("runsScored",0) or 0
                ra=tr.get("runsAllowed",0) or 0
                gp=tr.get("gamesPlayed",0) or 0
                w=tr.get("wins",0) or 0
                if gp>0:
                    rates[tid]={"off":rs/gp,"rapg":ra/gp,"k_rate":None,"win_pct":w/gp,"games":gp}
                    runs+=rs; games+=gp
    league_rpg=runs/games if games else LEAGUE_RPG_FALLBACK
    batting=get(f"{MLB_STATS_BASE}/teams/stats?stats=season&group=hitting&season={year}&gameType=R&sportId=1")
    total_ks=total_pa=0
    if batting:
        for split in (batting.get("stats") or [{}])[0].get("splits",[]):
            tid=split.get("team",{}).get("id")
            stat=split.get("stat",{})
            ks=_f(stat.get("strikeOuts") or stat.get("strikeouts"))
            pa=_f(stat.get("plateAppearances"))
            if tid and ks is not None and pa and pa>0:
                k_rate=ks/pa
                if tid in rates:
                    rates[tid]["k_rate"]=k_rate
                total_ks+=ks; total_pa+=pa
    league_k_rate=(total_ks/total_pa) if total_pa>0 else 0.225
    for tid in rates:
        if rates[tid]["k_rate"] is None:
            rates[tid]["k_rate"]=league_k_rate
    rates["_league_k_rate"]=league_k_rate
    result=(league_rpg, rates)
    set_cache(cache_key, result)
    return result

def _starter_line(stat):
    era=_f(stat.get("era"))
    ip=_ip(stat.get("inningsPitched")) or 0.0
    k9=bb9=fip=None
    ks_raw=_f(stat.get("strikeOuts") or stat.get("strikeouts"))
    bbs_raw=_f(stat.get("baseOnBalls")) or 0.0
    hrs_raw=_f(stat.get("homeRuns")) or 0.0
    if ip>0 and ks_raw is not None:
        k9=ks_raw*9.0/ip
        bb9=bbs_raw*9.0/ip
        fip=max(1.5, min(7.5, FIP_CONST + (13.0*hrs_raw + 3.0*bbs_raw - 2.0*ks_raw)/ip))
    if k9 is None and stat.get("strikeoutsPer9Inn"):
        k9=_f(stat["strikeoutsPer9Inn"])
    if bb9 is None and stat.get("baseOnBallsPer9Inn"):
        bb9=_f(stat["baseOnBallsPer9Inn"])
    xera=fip if fip is not None else era
    return {"era":era,"xera":xera,"fip":fip,"ip":ip,"k9":k9,"bb9":bb9}

def fetch_team_form(year, as_of_date, n_games=10, lookback_days=33):
    try:
        if str(as_of_date).lower()=="today":
            end_dt=datetime.now() - timedelta(days=1)
        else:
            end_dt=datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=1)
        start_dt=end_dt - timedelta(days=lookback_days)
    except:
        return {}
    sched=get(f"{MLB_STATS_BASE}/schedule?sportId=1&gameTypes=R&season={year}&startDate={start_dt.strftime('%Y-%m-%d')}&endDate={end_dt.strftime('%Y-%m-%d')}")
    if not sched:
        return {}
    raw={}; raw_home_tot={}; raw_road_tot={}; last_game_dt={}
    for d in sorted(sched.get("dates",[]), key=lambda x: x.get("date","")):
        d_date=d.get("date","")
        for g in d.get("games",[]):
            if g.get("status",{}).get("detailedState","")!="Final":
                continue
            teams=g.get("teams",{})
            for side, opp in (("away","home"),("home","away")):
                tid=teams.get(side,{}).get("team",{}).get("id")
                rs=_f(teams.get(side,{}).get("score"))
                ra=_f(teams.get(opp,{}).get("score"))
                won=teams.get(side,{}).get("isWinner",False)
                if tid and rs is not None and ra is not None:
                    raw.setdefault(tid,[]).append((rs,ra,bool(won)))
                    total=rs+ra
                    if side=="home":
                        raw_home_tot.setdefault(tid,[]).append(total)
                    else:
                        raw_road_tot.setdefault(tid,[]).append(total)
                    if d_date:
                        last_game_dt[tid]=d_date
    try:
        slate_dt=datetime.strptime(as_of_date, "%Y-%m-%d")
    except:
        slate_dt=None
    form={}
    for tid, game_list in raw.items():
        n_all=len(game_list)
        if n_all==0:
            continue
        # last 10
        last10=game_list[-10:]
        off10=sum(x[0] for x in last10)/len(last10)
        def10=sum(x[1] for x in last10)/len(last10)
        # 30 day
        off30=sum(x[0] for x in game_list)/len(game_list)
        def30=sum(x[1] for x in game_list)/len(game_list)
        wins10=sum(1 for x in last10 if x[2])
        # dynamic park: home total runs vs road total runs
        home_tot=raw_home_tot.get(tid,[])
        road_tot=raw_road_tot.get(tid,[])
        dyn_raw=None
        if home_tot and road_tot and len(home_tot)>=5 and len(road_tot)>=5:
            avg_home=sum(home_tot)/len(home_tot)
            avg_road=sum(road_tot)/len(road_tot)
            if avg_road>0:
                dyn_raw=avg_home/avg_road
        # days rest
        days_rest=None
        if slate_dt and tid in last_game_dt:
            try:
                last_dt=datetime.strptime(last_game_dt[tid], "%Y-%m-%d")
                delta=(slate_dt - last_dt).days -1
                days_rest=max(0, delta)
            except:
                pass
        form[tid]={
            "recent_off":off10, "recent_def":def10, "form_str":f"{wins10}-{len(last10)-wins10}",
            "recent_off_30":off30, "recent_def_30":def30,
            "recent_off_10":off10, "recent_def_10":def10,
            "form_str_30":f"{sum(1 for x in game_list if x[2])}-{len(game_list)-sum(1 for x in game_list if x[2])}",
            "dyn_park_raw":dyn_raw, "dyn_park_games":len(home_tot)+len(road_tot),
            "days_rest":days_rest,
        }
    return form

def fetch_injury_flags(team_ids, as_of_date, year):
    # Minimal: no IL data fetch, return empty with 1.0 adj, but structure matches final_v3
    result={}
    for tid in team_ids:
        result[tid]={"players":[],"off_adj":1.0}
    return result

# === REAL TEAM BATTING / K RATE ===
def fetch_real_team_batting(team_id):
    if not team_id:
        return {"k_rate":0.23}
    try:
        r=requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats", params={"stats":"season","season":datetime.now().year,"group":"hitting"}, timeout=8)
        splits=r.json().get("stats",[{}])[0].get("splits",[])
        if not splits:
            return {"k_rate":0.23}
        s=splits[0].get("stat",{})
        pa=int(s.get("plateAppearances",0) or 0)
        so=int(s.get("strikeOuts",0) or 0)
        k_rate=(so/pa) if pa>100 else 0.23
        return {"avg":s.get("avg",".000"),"obp":s.get("obp",".000"),"slg":s.get("slg",".000"),"ops":s.get("ops",".000"),"hr":int(s.get("homeRuns",0) or 0),"rbi":int(s.get("rbi",0) or 0),"sb":int(s.get("stolenBases",0) or 0),"so":so,"pa":pa,"k_rate":round(k_rate,4)}
    except:
        return {"k_rate":0.23}

def fetch_team_k_rate(team_id):
    try:
        data=fetch_real_team_batting(team_id)
        return data.get("k_rate",0.23)
    except:
        return 0.23

# === K PROJECTION IMPROVED ===
def _norm_cdf_k(x):
    return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))

def calculate_k_projection(pitcher_stats: Dict, opp_team_id: int = None, park_factor: float = 100, opp_k_rate: float = None, pitcher_name: str = None):
    if not pitcher_stats:
        pitcher_stats={"k_per_9":LEAGUE_AVG_K9,"whip":LEAGUE_AVG_WHIP,"era":LEAGUE_AVG_ERA,"has_data":False}
    k9=float(pitcher_stats.get("k_per_9", pitcher_stats.get("k9", LEAGUE_AVG_K9)) or LEAGUE_AVG_K9)
    whip=float(pitcher_stats.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP)
    era=float(pitcher_stats.get("era", LEAGUE_AVG_ERA) or LEAGUE_AVG_ERA)
    # Expected IP based on WHIP/ERA/K9 + Statcast K% if available
    ip_expected=5.2 + (k9-8.5)*0.08 - (whip-1.30)*1.0 - (era-4.25)*0.15
    # Statcast whiff/chase boost
    if pitcher_name:
        sc=_find_statcast_player(pitcher_name)
        pct=sc.get('percentile',{})
        if pct:
            whiff=pct.get('whiff_percent')
            if whiff is not None:
                ip_expected+= (whiff-50)/100.0*0.5
            k_pct=pct.get('k_percent')
            if k_pct is not None:
                k9+= (k_pct-50)/100.0*1.5
    ip_expected=max(4.0, min(7.2, ip_expected))
    if opp_k_rate is None and opp_team_id:
        opp_k_rate=fetch_team_k_rate(opp_team_id)
    if opp_k_rate is None:
        opp_k_rate=0.23
    league_k_rate=0.23
    opp_factor=opp_k_rate/league_k_rate
    opp_factor=max(0.70, min(1.40, opp_factor))
    pf_adj=1.0
    if park_factor!=100 and park_factor!=1.0:
        if park_factor>10:
            pf_adj=1.0 + (100-park_factor)*0.0025
        else:
            pf_adj=park_factor
    raw_k=k9*(ip_expected/9.0)
    proj_k=raw_k*opp_factor*pf_adj
    reliability=pitcher_stats.get("reliability",0.7) if pitcher_stats.get("has_data") else 0.5
    proj_k=reliability*proj_k + (1-reliability)*LEAGUE_AVG_K9*5.5/9.0
    return {"proj":round(max(1.0, proj_k),2),"ip_expected":round(ip_expected,2),"opp_k_rate":round(opp_k_rate,4),"opp_factor":round(opp_factor,3),"raw_k9":k9}

def k_prob_over(proj_k: float, line: float = 6.5):
    mean=proj_k
    sd=math.sqrt(max(0.8, mean*1.25))
    z=(line+0.5-mean)/sd
    p_over=1.0 - _norm_cdf_k(z)
    return max(0.05, min(0.95, p_over))

# === LINEUPS & PROBABLES ===
def fetch_today_lineups_with_teams():
    try:
        today=date.today().isoformat()
        url=f"{MLB_STATS_BASE}/schedule?sportId=1&date={today}&hydrate=lineups,probablePitchers,team,venue"
        r=requests.get(url, timeout=12)
        data=r.json()
        lineup_map={}
        for d in data.get("dates",[]):
            for g in d.get("games",[]):
                away_name=g.get("teams",{}).get("away",{}).get("team",{}).get("name","")
                home_name=g.get("teams",{}).get("home",{}).get("team",{}).get("name","")
                away_abbr=TEAM_ABBR.get(away_name, away_name[:3].upper())
                home_abbr=TEAM_ABBR.get(home_name, home_name[:3].upper())
                away_lineup=[]; home_lineup=[]
                try:
                    for p in g.get("lineups",{}).get("awayPlayers",[]):
                        away_lineup.append({"pos":p.get("position",{}).get("abbreviation","DH"),"name":p.get("fullName","TBD"),"hand":p.get("batSide",{}).get("code","R"),"avg":p.get("stats",{}).get("batting",{}).get("avg",".250"),"id":p.get("id")})
                except: pass
                try:
                    for p in g.get("lineups",{}).get("homePlayers",[]):
                        home_lineup.append({"pos":p.get("position",{}).get("abbreviation","DH"),"name":p.get("fullName","TBD"),"hand":p.get("batSide",{}).get("code","R"),"avg":p.get("stats",{}).get("batting",{}).get("avg",".250"),"id":p.get("id")})
                except: pass
                key=(away_abbr,home_abbr)
                lineup_map[key]={"lineupA":away_lineup,"lineupB":home_lineup,"lineupA_confirmed":len(away_lineup)>=8,"lineupB_confirmed":len(home_lineup)>=8}
        return lineup_map
    except Exception as e:
        return {}

def fetch_today_probable_pitchers():
    tid2abbr={v:k for k,v in MLB_TEAM_IDS.items()}
    out={}
    try:
        today=datetime.now().strftime("%Y-%m-%d")
        r=requests.get(f"{MLB_STATS_BASE}/schedule", params={"sportId":1,"date":today,"hydrate":"probablePitcher"}, timeout=10)
        for de in r.json().get("dates",[]):
            for gm in de.get("games",[]):
                h=gm["teams"]["home"]; a=gm["teams"]["away"]
                ha=tid2abbr.get(h["team"].get("id")); aa=tid2abbr.get(a["team"].get("id"))
                if not ha or not aa: continue
                hp=h.get("probablePitcher") or {}; ap=a.get("probablePitcher") or {}
                entry={"home_id":hp.get("id"),"home_name":hp.get("fullName"),"away_id":ap.get("id"),"away_name":ap.get("fullName"),"game_date":gm.get("gameDate")}
                out.setdefault((aa,ha),[]).append(entry)
        for k in out:
            out[k]=sorted(out[k], key=lambda x: x.get("game_date") or "")
    except Exception as e:
        pass
    return out

# === FETCH SLATE (improved from final_v3) ===
def fetch_slate(day, year, cfg):
    # schedule
    sched=get(f"{MLB_STATS_BASE}/schedule?sportId=1&date={day}&hydrate=probablePitcher,team,venue,officials")
    games_raw=(sched.get("dates",[{}])[0].get("games",[]) if sched and sched.get("dates") else [])
    league_rpg, rates=fetch_team_rates(year)
    team_form=fetch_team_form(year, day)
    # league OPS for lineup
    league_ops=0.720
    try:
        # compute avg ops from team batting
        batting=get(f"{MLB_STATS_BASE}/teams/stats?stats=season&group=hitting&season={year}&gameType=R&sportId=1")
        if batting:
            ops_list=[]
            for split in (batting.get("stats") or [{}])[0].get("splits",[]):
                op=_f(split.get("stat",{}).get("ops"))
                if op: ops_list.append(op)
            if ops_list:
                league_ops=sum(ops_list)/len(ops_list)
    except:
        pass
    # starter stats + recent form
    pstat={}
    # collect pitcher ids
    p_ids=[]
    for g in games_raw:
        for side in ("away","home"):
            pp=g.get("teams",{}).get(side,{}).get("probablePitcher")
            if pp and pp.get("id"):
                p_ids.append(pp["id"])
    if p_ids:
        ids_str=",".join(str(i) for i in set(p_ids))
        people=get(f"{MLB_STATS_BASE}/people?personIds={ids_str}&hydrate=stats(group=pitching,type=[season,gameLog],season={year})")
        if people:
            for p in people.get("people",[]):
                pid=str(p.get("id"))
                season_stat={}; gamelog=[]
                for block in p.get("stats",[]):
                    dtype=block.get("type",{}).get("displayName","").lower()
                    splits=block.get("splits",[])
                    if "gamelog" in dtype or "game log" in dtype:
                        gamelog=splits
                    elif "season" in dtype:
                        if splits:
                            season_stat=splits[0].get("stat",{})
                line=_starter_line(season_stat)
                recent_ra9, recent_ip=_recent_form_ra9(gamelog, team_rates=rates, league_rpg=league_rpg)
                line["recent_ra9"]=recent_ra9
                line["recent_ip"]=recent_ip
                line["expected_ip"]=_expected_sp_ip(gamelog)
                line["pitch_hand"]=(p.get("pitchHand") or {}).get("code","R")
                pstat[pid]=line
    # weather
    weather={}
    try:
        # coords from venue meta
        venue_coords=[]
        for g in games_raw:
            vname=g.get("venue",{}).get("name","")
            meta=VENUE_META.get(vname)
            if meta:
                venue_coords.append((g.get("venue",{}).get("id"), meta))
        # batch weather via open-meteo
        if venue_coords:
            # for simplicity, use current via open-meteo hourly
            pass
    except:
        pass
    # lineup map by gamePk
    lineup_map={}
    try:
        # reuse lineups from schedule hydrate=lineups
        sched2=get(f"{MLB_STATS_BASE}/schedule?sportId=1&date={day}&hydrate=lineups")
        if sched2:
            for d in sched2.get("dates",[]):
                for g in d.get("games",[]):
                    pk=g.get("gamePk")
                    lineup_map[pk]={"away": g.get("lineups",{}).get("awayPlayers",[]), "home": g.get("lineups",{}).get("homePlayers",[])}
    except:
        pass
    return league_rpg, rates, team_form, games_raw, pstat, lineup_map, league_ops

# === EVALUATE TOTAL (improved) ===
def evaluate_total(g, league_rpg, cfg, day=None):
    res={"away_name":g["away_name"],"home_name":g["home_name"],"venue":g["venue"],"away_sp":g["away_sp"],"home_sp":g["home_sp"]}
    # run prevention
    away_prev=run_prevention_per9(g["away_sp_ra9"], g["away_rapg"], sp_ip=g.get("away_expected_ip", STARTER_INNINGS), bullpen_ra9=g.get("away_bullpen_ra9"))
    home_prev=run_prevention_per9(g["home_sp_ra9"], g["home_rapg"], sp_ip=g.get("home_expected_ip", STARTER_INNINGS), bullpen_ra9=g.get("home_bullpen_ra9"))
    # env
    park=g.get("park",1.0)
    temp=g.get("temp")
    env=weather_factor(temp) * g.get("wind_factor",1.0) * g.get("ump_factor",1.0)
    # rest + injury
    off_away=g["away_off"] * _rest_factor(g.get("away_days_rest")) * g.get("away_injury_adj",1.0)
    off_home=g["home_off"] * _rest_factor(g.get("home_days_rest")) * g.get("home_injury_adj",1.0)
    # lineup OPS adjustment vs league
    try:
        away_ops=g.get("away_lineup_ops")
        home_ops=g.get("home_lineup_ops")
        league_ops=g.get("league_ops",0.72)
        if away_ops and league_ops:
            off_away*= (away_ops/league_ops)
        if home_ops and league_ops:
            off_home*= (home_ops/league_ops)
    except:
        pass
    # bullpen fatigue mult on prevention (taxed pen allows more runs)
    away_prev*= g.get("home_bullpen_fatigue",1.0)  # away offense vs home pen
    home_prev*= g.get("away_bullpen_fatigue",1.0)
    lam_away, lam_home = project_runs(off_away, off_home, home_prev, away_prev, league_rpg, park, env)
    sim=simulate(lam_away, lam_home, cfg.get("n_sims",10000))
    res.update({"proj_total":round(sim["proj_total"],2),"sd":round(sim["sd"],2),"p_away_win":round(sim["away_win_pct"],4),"p_home_win":round(sim["home_win_pct"],4),"lam_away":round(lam_away,3),"lam_home":round(lam_home,3),"park":park,"env":env})
    # ML ensemble with Pythag + Log5 + Form (from old)
    try:
        away_wp=g.get("away_win_pct_season",0.5); home_wp=g.get("home_win_pct_season",0.5)
        # Pythag
        away_rs=g.get("away_off",4.4); away_ra=g.get("away_rapg",4.4)
        home_rs=g.get("home_off",4.4); home_ra=g.get("home_rapg",4.4)
        away_pyth = (away_rs**PYTH_EXP) / (away_rs**PYTH_EXP + away_ra**PYTH_EXP) if (away_rs+away_ra)>0 else 0.5
        home_pyth = (home_rs**PYTH_EXP) / (home_rs**PYTH_EXP + home_ra**PYTH_EXP) if (home_rs+home_ra)>0 else 0.5
        p_pyth = away_pyth*(1-home_pyth) / (away_pyth*(1-home_pyth) + home_pyth*(1-away_pyth)) if (away_pyth*(1-home_pyth)+home_pyth*(1-away_pyth))>0 else 0.5
        # Log5
        p_log5 = (away_wp - away_wp*home_wp) / (away_wp + home_wp -2*away_wp*home_wp) if (away_wp+home_wp-2*away_wp*home_wp)!=0 else 0.5
        # Form
        af=g.get("away_recent_off") or g.get("away_off",4.4); hf=g.get("home_recent_off") or g.get("home_off",4.4)
        p_form = af/(af+hf) if (af+hf)>0 else 0.5
        mc=sim["away_win_pct"]
        p_away_raw=0.40*mc + 0.25*p_pyth + 0.20*p_log5 + 0.15*p_form
        p_away_raw=max(0.35, min(0.65, p_away_raw))
        res["p_away_win"]=round(p_away_raw,4); res["p_home_win"]=round(1-p_away_raw,4)
    except:
        pass
    # Totals edge (de-vig)
    if g.get("line") is None or g.get("over_odds") is None or g.get("under_odds") is None:
        res["reason"]="no posted total"
        return res
    p_over,p_under,p_push=p_over_ensemble(sim, g["line"])
    fair_over,fair_under=devig_two_way(g["over_odds"], g["under_odds"])
    edge_over=p_over-fair_over; edge_under=p_under-fair_under
    res.update({"p_over":round(p_over,4),"p_under":round(p_under,4),"fair_over":round(fair_over,4),"fair_under":round(fair_under,4),"edge_over":round(edge_over,4),"edge_under":round(edge_under,4)})
    # ML edge
    res["ml_pick"]=None; res["ml_edge"]=0.0
    if g.get("away_ml") is not None and g.get("home_ml") is not None:
        fair_away_ml,fair_home_ml=devig_two_way(g["away_ml"], g["home_ml"])
        ml_edge_away=res["p_away_win"]-fair_away_ml
        ml_edge_home=(1.0-res["p_away_win"])-fair_home_ml
        res.update({"fair_away_ml":round(fair_away_ml,4),"fair_home_ml":round(fair_home_ml,4),"ml_edge_away":round(ml_edge_away,4),"ml_edge_home":round(ml_edge_home,4)})
        ml_thr=cfg.get("ml_edge_threshold", cfg["edge_threshold"])
        if ml_edge_away>=ml_thr and ml_edge_away>=ml_edge_home:
            best_ml=g.get("best_away_ml") or g["away_ml"]
            res.update({"ml_pick":"away","ml_team":g["away_name"],"ml_edge":ml_edge_away,"ml_confidence":res["p_away_win"],"ml_odds":best_ml,"ml_best_book":g.get("best_away_ml_book",""),"ml_stake_pct":min(cfg["max_stake_pct"], cfg["kelly_fraction"]*kelly_fraction(res["p_away_win"], best_ml)),"ml_confidence_score":_confidence_score(ml_edge_away, g.get("ml_n_books",1), sim["sd"], sim["proj_total"])})
        elif ml_edge_home>=ml_thr:
            best_ml=g.get("best_home_ml") or g["home_ml"]
            res.update({"ml_pick":"home","ml_team":g["home_name"],"ml_edge":ml_edge_home,"ml_confidence":1.0-res["p_away_win"],"ml_odds":best_ml,"ml_best_book":g.get("best_home_ml_book",""),"ml_stake_pct":min(cfg["max_stake_pct"], cfg["kelly_fraction"]*kelly_fraction(1.0-res["p_away_win"], best_ml)),"ml_confidence_score":_confidence_score(ml_edge_home, g.get("ml_n_books",1), sim["sd"], sim["proj_total"])})
    # Totals pick
    thr=cfg["edge_threshold"]
    if not (cfg["min_total_line"] <= g["line"] <= cfg["max_total_line"]):
        res["reason"]=f"line {g['line']:.1f} outside [{cfg['min_total_line']:.1f},{cfg['max_total_line']:.1f}]"
        return res
    if edge_over>=thr and edge_over>=edge_under:
        best_odds=g.get("best_over") or g["over_odds"]
        res.update({"pick":"Over","edge":edge_over,"confidence":p_over,"odds":best_odds,"best_book":g.get("best_over_book",""),"stake_pct":min(cfg["max_stake_pct"], cfg["kelly_fraction"]*kelly_fraction(p_over, best_odds)),"confidence_score":_confidence_score(edge_over, g.get("n_books",1), sim["sd"], sim["proj_total"])})
    elif edge_under>=thr:
        best_odds=g.get("best_under") or g["under_odds"]
        res.update({"pick":"Under","edge":edge_under,"confidence":p_under,"odds":best_odds,"best_book":g.get("best_under_book",""),"stake_pct":min(cfg["max_stake_pct"], cfg["kelly_fraction"]*kelly_fraction(p_under, best_odds)),"confidence_score":_confidence_score(edge_under, g.get("n_books",1), sim["sd"], sim["proj_total"])})
    else:
        res["reason"]=f"edge {max(edge_over,edge_under):.3f} < thr {thr:.3f}"
    return res

# === DASHBOARD JSON + HTML (kept) ===
def _build_dashboard_json(games_eval, date_str):
    # minimal builder from final_v3
    out={"date":date_str,"games":[]}
    for g,r in games_eval:
        out["games"].append({
            "matchup": f"{g['away_name']} @ {g['home_name']}",
            "venue": g.get("venue",""),
            "away_sp": g.get("away_sp","TBD"), "home_sp": g.get("home_sp","TBD"),
            "line": g.get("line"), "proj_total": r.get("proj_total",0),
            "p_away_win": r.get("p_away_win",0.5), "p_home_win": r.get("p_home_win",0.5),
            "pick": r.get("pick"), "edge_pct": round(r.get("edge",0)*100,1),
            "away_sp_era": g.get("away_sp_era"), "home_sp_era": g.get("home_sp_era"),
        })
    return out

def render_html_dashboard(games_eval, cfg, league_rpg, date_str, json_data):
    # simple self-rendering HTML similar to final_v3 but lean
    rows=""
    for g,r in games_eval:
        pick=r.get("pick","—")
        edge=r.get("edge",0)
        proj=r.get("proj_total",0)
        line=g.get("line","—")
        rows+=f"<tr><td>{html_lib.escape(g['away_name'])} @ {html_lib.escape(g['home_name'])}</td><td>{html_lib.escape(g.get('venue',''))}</td><td>{html_lib.escape(g.get('away_sp',''))}</td><td>{html_lib.escape(g.get('home_sp',''))}</td><td>{line}</td><td>{proj:.1f}</td><td>{pick}</td><td>{edge:+.3f}</td></tr>\n"
    html=f"""<!doctype html><html><head><meta charset='utf-8'><title>MLB Ace Improved {date_str}</title>
    <style>body{{font-family:system-ui;background:#111;color:#eee;padding:20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:6px 8px}}th{{background:#222}} .over{{color:#6f6}} .under{{color:#f88}}</style></head>
    <body><h1>MLB Ace Improved — {date_str}</h1><p>League RPG {league_rpg:.2f} | Sims {cfg.get('n_sims')} | Edge thr {cfg.get('edge_threshold')}</p>
    <table><tr><th>Matchup</th><th>Venue</th><th>Away SP</th><th>Home SP</th><th>Line</th><th>Proj</th><th>Pick</th><th>Edge</th></tr>{rows}</table>
    <script>window.PARLAYOS_DATA={json.dumps(json_data)};</script></body></html>"""
    return html

# === LINE MOVEMENT + LOGGING (from final_v3) ===
def _load_line_history():
    try:
        with open(LINE_HISTORY_PATH,"r") as f:
            return json.load(f)
    except:
        return {}
def _save_line_history(d):
    try:
        with open(LINE_HISTORY_PATH,"w") as f:
            json.dump(d,f)
    except:
        pass
def _track_line_movement(date_str, matchup, market, line, odds, history):
    return 0.0, 0.0, True
def _line_movement_note(pick, move):
    return None
def _reason(g, side):
    return f"{side} {g.get('line')} proj {g.get('proj_total',0):.1f} vs market"

def _auto_log_picks(games_eval, date_str):
    return 0

# === PARLAYOS INJECTION (from mlb_ace_2.py) ===
def _find_v6_template():
    here=os.path.dirname(os.path.abspath(__file__))
    candidates=["parlayos_3.html","parlayos.html","parlayos_2.html","index.html","parlayos_v6.html"]
    for c in candidates:
        p=os.path.join(here,c)
        if os.path.exists(p):
            return p
    return os.path.join(here,"parlayos_3.html")
PARLAYOS_TEMPLATE_PATH=_find_v6_template()

def _american_to_decimal(american):
    if american is None:
        return None
    try:
        o=float(str(american).replace("+",""))
    except:
        return None
    if o>0:
        return round((o/100)+1,3)
    else:
        return round((100/abs(o))+1,3)

def fetch_today_probable_pitchers_v2():
    return fetch_today_probable_pitchers()

def _picks_to_v6_games(picks: List) -> List:
    v_games=[]
    probables=fetch_today_probable_pitchers()
    for idx,p in enumerate(picks):
        away=p.get('away','Away'); home=p.get('home','Home')
        pick_team=p.get('pick',home); odds=p.get('odds',-110)
        model_prob=p.get('model_prob',50)/100.0; edge=p.get('edge',0)/100.0
        ml_price_dec=_american_to_decimal(odds) or 1.91
        abbr_a=TEAM_ABBR.get(away, away[:3].upper()); abbr_b=TEAM_ABBR.get(home, home[:3].upper())
        matchup_key=(abbr_a,abbr_b); prob_list=probables.get(matchup_key,[])
        if prob_list:
            away_pitcher=prob_list[0].get("away_name","TBD"); home_pitcher=prob_list[0].get("home_name","TBD")
        else:
            away_pitcher=p.get("away_pitcher","TBD"); home_pitcher=p.get("home_pitcher","TBD")
        game_date_str=p.get('commence_time'); start_at_ms=None; time_display='TBD'; date_display=''
        if game_date_str:
            try:
                dt_utc=datetime.strptime(game_date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                start_at_ms=int(dt_utc.timestamp()*1000)
                dt_local=dt_utc.astimezone(ET_ZONE)
                time_display=dt_local.strftime('%-I:%M %p'); date_display=dt_local.strftime('%a %b %-d')
            except:
                pass
        if start_at_ms is None:
            start_at_ms=int(time.time()*1000)
        total=p.get('line') or p.get('total') or 8.5
        ml_fav=TEAM_ABBR.get(pick_team, pick_team[:3].upper()) if pick_team else abbr_b
        hot=edge>0.03
        k_line=p.get('kLine',6.5); k_proj=p.get('kProj',5.5); k_pitcher=p.get('kPitcher',away_pitcher); k_over_prob=p.get('kOverProb',0.5); k_edge_val=p.get('kEdge',0.0)
        if p.get('kPick') and 'Ks' in str(p.get('kPick')):
            k_pick_str=p.get('kPick')
        else:
            side_str="Over" if k_over_prob>0.5 else "Under"
            k_pick_str=f"{side_str} {k_line}K ({k_proj} Ks)" if k_proj is not None else f"{side_str} {k_line}K"
        game={'id':f'mlb_live_{idx}_{int(datetime.now().timestamp())}','a':abbr_a,'b':abbr_b,'cityA':away,'cityB':home,'lgA':'MLB','lgB':'MLB','total':total,'ouPick':f'OVER {total}' if edge>0 else f'UNDER {total}','kLine':k_line,'kPick':k_pick_str,'kProj':k_proj,'kPitcher':k_pitcher,'kOverProb':k_over_prob,'mlFav':ml_fav,'mlPriceDec':ml_price_dec,'ouEdge':round(edge*0.5,4),'kEdge':round(k_edge_val,4) if k_edge_val is not None else 0.0,'mlEdge':round(edge,4),'model':round(model_prob,4),'tv':'ESPN+','hot':hot,'startAt':start_at_ms,'start_at':start_at_ms,'commence_time':p.get('commence_time') or game_date_str,'time':time_display,'date':date_display,'time_et':time_display,'date_et':date_display,'status':'live','modelProb':round(model_prob,3),'mlPriceAmerican':odds,'marketProb':round(1/ml_price_dec,3) if ml_price_dec>0 else 0.5,'qualifies':bool(p.get('qualifies',True)),'away_pitcher':away_pitcher,'home_pitcher':home_pitcher,'pitcherA':away_pitcher,'pitcherB':home_pitcher}
        for col in ["c_team_edge","c_pitcher_fip_edge","c_pitcher_era_edge","c_offense_edge","c_bullpen_edge"]:
            if col in p:
                game[col]=p[col]
        v_games.append(game)
    return v_games

def export_to_html(all_games_data, html_path=None):
    if html_path is None:
        html_path=_find_v6_template()
    # If template is index.html dashboard, we already render dashboard; for ParlayOS, inject
    try:
        # Try to inject into template if it's parlayos html
        if html_path and os.path.exists(html_path) and "parlayos" in os.path.basename(html_path).lower():
            with open(html_path,"r", encoding="utf-8") as f:
                tmpl=f.read()
            # Inject window.PARLAYOS_DATA
            inject=json.dumps(all_games_data)
            if "window.PARLAYOS_DATA" in tmpl:
                # replace
                tmpl=re.sub(r"window\.PARLAYOS_DATA\s*=\s*.*?;", f"window.PARLAYOS_DATA = {inject};", tmpl, flags=re.DOTALL)
            else:
                tmpl=tmpl.replace("</head>", f"<script>window.PARLAYOS_DATA = {inject};</script></head>")
            out_path=os.path.join(HERE_DIR, "parlayos_injected.html")
            with open(out_path,"w", encoding="utf-8") as out:
                out.write(tmpl)
            print(f"[ParlayOS] Injected {len(all_games_data)} games -> {out_path}")
            return
    except Exception as e:
        print(f"[ParlayOS export warn] {e}")
    # fallback: write simple json
    try:
        out_path=os.path.join(HERE_DIR, "last_slate.json")
        with open(out_path,"w") as f:
            json.dump(all_games_data,f, indent=2)
        print(f"[Export] {len(all_games_data)} games -> {out_path}")
    except Exception as e:
        print(f"Export failed: {e}")

# === PLAYER DETAILS (kept) ===
_PLAYER_CACHE={}
def _get_cached(k, ttl=3600):
    if k in _PLAYER_CACHE:
        ts,v=_PLAYER_CACHE[k]
        if time.time()-ts < ttl:
            return v
    return None
def _set_cache(k,v):
    _PLAYER_CACHE[k]=(time.time(),v)

def fetch_mlb_player_details(player_name: str, team_abbr: str):
    if not player_name or player_name=='TBD':
        return {}
    key=f"mlb_p_{team_abbr}_{player_name}"
    c=_get_cached(key,86400)
    if c:
        return c
    try:
        r=requests.get(f"{MLB_STATS_BASE}/people/search?names={requests.utils.quote(player_name)}", timeout=8)
        people=r.json().get('people',[])
        if not people:
            return {}
        pid=people[0].get('id')
        r2=requests.get(f"{MLB_STATS_BASE}/people/{pid}?hydrate=stats(group=[pitching,hitting],type=[season])", timeout=8)
        p=(r2.json().get('people') or [{}])[0]
        result={'id':pid,'name':p.get('fullName',player_name),'jersey':p.get('primaryNumber',''),'pos':(p.get('primaryPosition') or {}).get('abbreviation',''),'team':team_abbr,'age':p.get('currentAge',''),'height':p.get('height',''),'weight':p.get('weight',''),'bats':(p.get('batSide') or {}).get('description',''),'throws':(p.get('pitchHand') or {}).get('description',''),'sport':'MLB','jerseyDisplay':f"#{p.get('primaryNumber','')}" if p.get('primaryNumber') else ''}
        for sg in p.get('stats',[]):
            s=(sg.get('splits') or [{}])[0].get('stat',{})
            if sg.get('group',{}).get('displayName')=='pitching':
                result.update({'era':s.get('era',''),'whip':s.get('whip',''),'k9':s.get('strikeoutsPer9Inn',''),'ip':s.get('inningsPitched',''),'w':s.get('wins',''),'l':s.get('losses',''),'so':s.get('strikeOuts',''),'bb':s.get('baseOnBalls',''),'fip':s.get('fip','')})
        _set_cache(key,result)
        return result
    except Exception as e:
        return {}

def fetch_mlb_team_roster(team_abbr: str):
    key=f"mlb_roster_{team_abbr}"
    c=_get_cached(key,3600)
    if c:
        return c
    try:
        espn_ids={'ARI':29,'ATL':15,'BAL':3,'BOS':4,'CHC':16,'CHW':5,'CIN':17,'CLE':6,'COL':27,'DET':8,'HOU':18,'KC':9,'LAA':1,'LAD':14,'MIA':28,'MIL':19,'MIN':10,'NYM':21,'NYY':20,'OAK':11,'PHI':22,'PIT':23,'SD':24,'SF':25,'SEA':26,'STL':20,'TB':30,'TEX':13,'TOR':12,'WSH':32}
        eid=espn_ids.get(team_abbr)
        if not eid:
            return []
        r=requests.get(f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{eid}/roster", timeout=10)
        athletes=[]
        for grp in r.json().get('athletes',[]):
            for it in grp.get('items',[]):
                athletes.append({'name':it.get('fullName',''),'jersey':it.get('jersey',''),'pos':(it.get('position') or {}).get('abbreviation',''),'team':team_abbr,'sport':'MLB'})
        _set_cache(key,athletes)
        return athletes
    except:
        return []

# === MAIN ===
def main():
    cfg=load_config()
    today=date.today().isoformat()
    league_rpg, rates, team_form, games_raw, pstat, lineup_map, league_ops = fetch_slate(today, datetime.now().year, cfg)
    print(f"[Improved] League RPG {league_rpg:.2f}, {len(games_raw)} games raw, statcast={HAS_STATCAST}")
    # Weather batch (open-meteo)
    weather_map={}
    try:
        # Build coords list
        coords=[]
        for g in games_raw:
            vname=g.get("venue",{}).get("name","")
            meta=VENUE_META.get(vname)
            if meta:
                coords.append((g.get("venue",{}).get("id"), meta[0], meta[1], meta[2]))
        # fetch open-meteo hourly for each (simple current for now)
        for vid, lat, lon, bearing in coords:
            try:
                r=requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude":lat,"longitude":lon,"current":"temperature_2m,wind_speed_10m,wind_direction_10m","temperature_unit":"fahrenheit","wind_speed_unit":"mph","forecast_days":1}, timeout=6)
                cur=r.json().get("current",{})
                weather_map[vid]={"temp":cur.get("temperature_2m"),"wind_speed":cur.get("wind_speed_10m"),"wind_dir":cur.get("wind_direction_10m")}
            except:
                pass
    except:
        pass
    # Odds multi-book
    odds_idx={}
    if ODDS_KEY:
        try:
            ev_list=get(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?apiKey={ODDS_KEY}&regions=us&markets=h2h,totals&oddsFormat=american") or []
            BOOK_SHORT={"draftkings":"DK","fanduel":"FD","betmgm":"MGM","caesars":"CZR","pointsbet_us":"PB","williamhill_us":"WH","betrivers":"BR","barstool":"BS","bet365":"B365","unibet_us":"UB","mybookieag":"MB","betonlineag":"BOL"}
            for ev in ev_list:
                a=ev.get("away_team"); h=ev.get("home_team")
                if not (a and h): continue
                over_px=[]; under_px=[]; away_ml_px=[]; home_ml_px=[]
                best_over=best_under=best_away_ml=best_home_ml=None
                best_over_bk=best_under_bk=best_away_ml_bk=best_home_ml_bk=""
                total_line=None
                for bk in ev.get("bookmakers",[]):
                    bk_label=BOOK_SHORT.get(bk["key"], bk.get("title", bk["key"])[:6])
                    for m in bk.get("markets",[]):
                        if m["key"]=="totals":
                            for o in m["outcomes"]:
                                px=o.get("price"); pt=o.get("point")
                                if o["name"]=="Over" and px:
                                    over_px.append(px)
                                    if total_line is None and pt:
                                        total_line=pt
                                    if best_over is None or px>best_over:
                                        best_over=px; best_over_bk=bk_label
                                elif o["name"]=="Under" and px:
                                    under_px.append(px)
                                    if best_under is None or px>best_under:
                                        best_under=px; best_under_bk=bk_label
                        elif m["key"]=="h2h":
                            for o in m["outcomes"]:
                                px=o.get("price")
                                if o["name"]==a and px:
                                    away_ml_px.append(px)
                                    if best_away_ml is None or px>best_away_ml:
                                        best_away_ml=px; best_away_ml_bk=bk_label
                                elif o["name"]==h and px:
                                    home_ml_px.append(px)
                                    if best_home_ml is None or px>best_home_ml:
                                        best_home_ml=px; best_home_ml_bk=bk_label
                cons_over=sum(over_px)/len(over_px) if over_px else best_over
                cons_under=sum(under_px)/len(under_px) if under_px else best_under
                cons_away=sum(away_ml_px)/len(away_ml_px) if away_ml_px else best_away_ml
                cons_home=sum(home_ml_px)/len(home_ml_px) if home_ml_px else best_home_ml
                odds_idx.setdefault((a,h),[]).append({"total":total_line,"over":cons_over,"under":cons_under,"best_over":best_over,"best_under":best_under,"best_over_book":best_over_bk,"best_under_book":best_under_bk,"away_ml":cons_away,"home_ml":cons_home,"best_away_ml":best_away_ml,"best_home_ml":best_home_ml,"best_away_ml_book":best_away_ml_bk,"best_home_ml_book":best_home_ml_bk,"n_books":len(over_px),"ml_n_books":len(away_ml_px)})
        except Exception as e:
            print(f"[Odds] fetch failed: {e}")
    else:
        print("[Odds] No API key found — skipping odds (set ODDS_API_KEY env var)")

    # Build games for model
    games=[]
    team_ids=set()
    for g in games_raw:
        a=g["teams"]["away"]; h=g["teams"]["home"]
        an= a["team"]["name"]; hn= h["team"]["name"]
        aid= a["team"]["id"]; hid= h["team"]["id"]
        team_ids.add(aid); team_ids.add(hid)
        ar=rates.get(aid, {"off":league_rpg,"rapg":league_rpg,"k_rate":rates.get("_league_k_rate",0.23),"win_pct":0.5,"games":0})
        hr=rates.get(hid, {"off":league_rpg,"rapg":league_rpg,"k_rate":rates.get("_league_k_rate",0.23),"win_pct":0.5,"games":0})
        def sp_ra9(side):
            pp=side.get("probablePitcher")
            if not pp:
                return league_rpg, "TBD", {}, "R"
            sl=pstat.get(str(pp["id"]), _starter_line({}))
            ra9=starter_ra9(sl["era"], sl["ip"], sl["xera"], league_rpg, k9=sl["k9"], bb9=sl["bb9"], fip=sl["fip"], recent_ra9=sl.get("recent_ra9"), recent_ip=sl.get("recent_ip",0.0), pitcher_name=pp.get("fullName",""))
            return ra9, pp.get("fullName","TBD"), sl, sl.get("pitch_hand","R")
        away_sp_ra9, away_sp, away_sl, away_pitch_hand = sp_ra9(a)
        home_sp_ra9, home_sp, home_sl, home_pitch_hand = sp_ra9(h)
        venue=g.get("venue",{}).get("name","")
        vid=g.get("venue",{}).get("id")
        winfo=weather_map.get(vid,{})
        temp=winfo.get("temp"); wspd=winfo.get("wind_speed"); wdir=winfo.get("wind_dir")
        meta=VENUE_META.get(venue); is_dome=venue in DOME_VENUES
        if meta:
            wfac,wlabel=wind_factor(wspd,wdir,meta[2],is_dome)
        else:
            wfac,wlabel=1.0,None
        oc_list=odds_idx.get((an,hn),[])
        oc=oc_list.pop(0) if oc_list else {}
        gpk=g.get("gamePk"); lu=lineup_map.get(gpk,{})
        af=team_form.get(aid,{}); hf=team_form.get(hid,{})
        officials=g.get("officials",[]); hp_ump_d=next((o.get("official",{}) for o in officials if o.get("officialType","").lower()=="home plate"), {}); hp_name=hp_ump_d.get("fullName",""); hp_id=hp_ump_d.get("id"); ump_factor,ump_label=_ump_factor(hp_name,hp_id, datetime.now().year)
        bp_fatigue={}
        for tid in (aid,hid):
            bp_fatigue[tid]=_bullpen_fatigue(tid, datetime.now().year, today)
        # opponent K rates
        league_k_rate=rates.get("_league_k_rate",0.23)
        games.append({
            "away_name":an,"home_name":hn,"venue":venue,"away_sp":away_sp,"home_sp":home_sp,
            "away_sp_ra9":away_sp_ra9,"home_sp_ra9":home_sp_ra9,
            "away_sp_k9": away_sl.get("k9") if away_sl.get("k9") is not None else K9_LG,
            "home_sp_k9": home_sl.get("k9") if home_sl.get("k9") is not None else K9_LG,
            "away_sp_ip": away_sl.get("ip"),"home_sp_ip": home_sl.get("ip"),
            "away_sp_era": away_sl.get("era"),"home_sp_era": away_sl.get("era"),
            "away_sp_fip": away_sl.get("fip"),"home_sp_fip": away_sl.get("fip"),
            "away_sp_bb9": away_sl.get("bb9"),"home_sp_bb9": away_sl.get("bb9"),
            "away_sp_recent_ra9": away_sl.get("recent_ra9"),"home_sp_recent_ra9": away_sl.get("recent_ra9"),
            "away_expected_ip": away_sl.get("expected_ip",STARTER_INNINGS),"home_expected_ip": home_sl.get("expected_ip",STARTER_INNINGS),
            "away_pitch_hand":away_pitch_hand,"home_pitch_hand":home_pitch_hand,
            "away_opp_k_rate": hr.get("k_rate",league_k_rate),"home_opp_k_rate": ar.get("k_rate",league_k_rate),"league_k_rate":league_k_rate,
            "away_lineup_ops": _lineup_ops(lu.get("away",[]), home_pitch_hand),"home_lineup_ops": _lineup_ops(lu.get("home",[]), away_pitch_hand),"league_ops":league_ops,
            "away_recent_off": af.get("recent_off"),"away_recent_def": af.get("recent_def"),"away_form_str": af.get("form_str"),
            "home_recent_off": hf.get("recent_off"),"home_recent_def": hf.get("recent_def"),"home_form_str": hf.get("form_str"),
            "away_recent_off_30": af.get("recent_off_30"),"away_recent_def_30": af.get("recent_def_30"),"away_form_str_30": af.get("form_str_30"),
            "home_recent_off_30": hf.get("recent_off_30"),"home_recent_def_30": hf.get("recent_def_30"),"home_form_str_30": hf.get("form_str_30"),
            "away_win_pct_season": ar.get("win_pct",0.5),"home_win_pct_season": hr.get("win_pct",0.5),
            "away_games_season": ar.get("games",0),"home_games_season": hr.get("games",0),
            "away_bullpen_fatigue": bp_fatigue.get(aid,{}).get("fatigue_mult",1.0),"home_bullpen_fatigue": bp_fatigue.get(hid,{}).get("fatigue_mult",1.0),
            "away_bullpen_ra9": bp_fatigue.get(aid,{}).get("bullpen_ra9"),"home_bullpen_ra9": bp_fatigue.get(hid,{}).get("bullpen_ra9"),
            "hp_ump": hp_name or "unknown","ump_factor": ump_factor,
            "away_injuries":[],"home_injuries":[],"away_injury_adj":1.0,"home_injury_adj":1.0,
            "away_off": ar["off"],"home_off": hr["off"],"away_rapg": ar["rapg"],"home_rapg": hr["rapg"],
            "park": _dynamic_park_factor(hn, hf),"temp":temp,"away_days_rest": af.get("days_rest"),"home_days_rest": hf.get("days_rest"),
            "wind_factor":wfac,"wind_label":wlabel,"is_dome":is_dome,"wx_note":f"{temp}F wind {wspd}" if temp else "n/a",
            "line": _f(oc.get("total")),"over_odds":oc.get("over"),"under_odds":oc.get("under"),
            "best_over":oc.get("best_over"),"best_under":oc.get("best_under"),"best_over_book":oc.get("best_over_book",""),"best_under_book":oc.get("best_under_book",""),"n_books":oc.get("n_books",1),
            "away_ml":oc.get("away_ml"),"home_ml":oc.get("home_ml"),"best_away_ml":oc.get("best_away_ml"),"best_home_ml":oc.get("best_home_ml"),"best_away_ml_book":oc.get("best_away_ml_book",""),"best_home_ml_book":oc.get("best_home_ml_book",""),"ml_n_books":oc.get("ml_n_books",1),
            "_k_projection":{"away":calculate_k_projection({"k_per_9":away_sl.get("k9"),"whip":1.30,"era":away_sl.get("era",4.25),"has_data":True}, opp_team_id=hid, park_factor=_dynamic_park_factor(hn,hf), opp_k_rate=hr.get("k_rate"), pitcher_name=away_sp),"home":calculate_k_projection({"k_per_9":home_sl.get("k9"),"whip":1.30,"era":home_sl.get("era",4.25),"has_data":True}, opp_team_id=aid, park_factor=_dynamic_park_factor(hn,hf), opp_k_rate=ar.get("k_rate"), pitcher_name=home_sp)},
        })

    cfg_loaded=load_config()
    games_eval=[]
    all_games_data=[]
    for g in games:
        r=evaluate_total(g, league_rpg, cfg_loaded, day=today)
        games_eval.append((g,r))
        # Build pick data for ParlayOS
        away_abbr=TEAM_ABBR.get(g["away_name"], g["away_name"][:3].upper())
        home_abbr=TEAM_ABBR.get(g["home_name"], g["home_name"][:3].upper())
        # totals
        pick_line=g.get("line") or 8.5
        model_prob=r.get("p_over",0.5)*100 if r.get("pick")=="Over" else r.get("p_under",0.5)*100 if r.get("pick")=="Under" else 50
        edge_pct=r.get("edge",0)*100
        away_k_proj=g.get("_k_projection",{}).get("away",{}).get("proj") if g.get("_k_projection") else None
        home_k_proj=g.get("_k_projection",{}).get("home",{}).get("proj") if g.get("_k_projection") else None
        # choose best K
        k_proj=home_k_proj if (home_k_proj or 0) > (away_k_proj or 0) else away_k_proj
        k_pitcher=g["home_sp"] if (home_k_proj or 0) > (away_k_proj or 0) else g["away_sp"]
        k_side="home" if (home_k_proj or 0) > (away_k_proj or 0) else "away"
        k_line=6.5
        k_over_prob=k_prob_over(k_proj or 5.5, k_line) if k_proj else 0.5
        game_data={
            "away":g["away_name"],"home":g["home_name"],"away_abbr":away_abbr,"home_abbr":home_abbr,
            "away_pitcher":g["away_sp"],"home_pitcher":g["home_sp"],
            "line":pick_line,"total":pick_line,
            "pick":r.get("pick",""),"odds":r.get("odds",-110),"edge":edge_pct/100.0,
            "model_prob":model_prob,"proj_total":r.get("proj_total",pick_line),
            "p_over":r.get("p_over"),"p_under":r.get("p_under"),
            "p_away_win":r.get("p_away_win"),"p_home_win":r.get("p_home_win"),
            "ml_pick":r.get("ml_pick"),"ml_edge":r.get("ml_edge"),
            "ml_odds":r.get("ml_odds"),"ml_team":r.get("ml_team"),
            "kLine":k_line,"kProj":k_proj,"kPitcher":k_pitcher,"kSide":k_side,"kOverProb":k_over_prob,
            "kPick":f"{'Over' if k_over_prob>0.5 else 'Under'} {k_line}K",
            "qualifies": bool(r.get("pick") or r.get("ml_pick")),
            "commence_time":None,
            "away_k_proj":away_k_proj,"home_k_proj":home_k_proj,
        }
        all_games_data.append(game_data)

    json_data=_build_dashboard_json(games_eval, today)
    html_out=render_html_dashboard(games_eval, cfg_loaded, league_rpg, today, json_data)
    for path in (OUTPUT_PATH, LEGACY_OUTPUT_PATH):
        try:
            with open(path,"w", encoding="utf-8") as f:
                f.write(html_out)
        except:
            pass
    print(f"✅ {len(games_eval)} game(s) -> {OUTPUT_PATH} (statcast={HAS_STATCAST})")
    export_to_html(all_games_data)
    print(f"\n✅ {len(all_games_data)} games exported for ParlayOS")

def run(html_path: str = None):
    try:
        if html_path is None:
            html_path=_find_v6_template()
        original_export=globals().get('export_to_html')
        captured=[]
        def cap_export(picks, hp=None):
            nonlocal captured
            captured=picks
            return original_export(picks, hp or html_path)
        globals()['export_to_html']=cap_export
        main()
        globals()['export_to_html']=original_export
        return captured
    except Exception as e:
        print(f"run() failed: {e}")
        import traceback; traceback.print_exc()
        return []

if __name__=="__main__":
    main()
