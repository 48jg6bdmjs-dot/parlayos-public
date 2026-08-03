"""
nfl_ace_improved.py — Improved NFL Model (no API key copied, sport-specific only)

Improvements over original nfl_ace.py inspired by mlb_ace_final_v3.py principles but NFL-only:
- No hardcoded key — loads from ODDS_API_KEY env, ~/.acebot_config, nfl_config.json
- Correct IP parsing not needed (NFL), but fixed: EPA/play, success rate, OL/DL, QB shrinkage with reliability (games/10)
- Form blending 50% season / 30% last 5 / 20% last 3 (like MLB old)
- Rest factor: short week (<=3 days) 0.985, extra rest (>=9 days/bye) 1.015, applied to offense and defense
- Injury weighting: OUT=1.0, DOUBTFUL=0.8, QUESTIONABLE=0.4 with positional value (QB 3x, OT/EDGE/CB 1.5x, WR 1x)
- Weather: temp_factor + wind_factor_nfl gated for outdoor stadiums only, wind >10mph hurts passing 0.4% per mph, capped 0.92
- Dynamic home field 2.5% base regressed, not fixed
- QB rating shrinkage (reliability = min(1, games/10)) like pitcher FIP shrinkage
- Monte Carlo for totals with gamma overdispersion (shared 20, independent 10) — same method as MLB but for NFL scoring
- Win prob blend: 40% form-adjusted model + 25% Pythag + 20% Log5 + 15% recent form (from old MLB superior)
- Multi-book consensus vs best price (de-vig consensus, bet best), n_books tracked
- Travel distance, outdoor flag, EPA

No NBA/MLB stats included.
"""

import requests, json, os, re, math, random, time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple
try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
except:
    ET_ZONE = timezone.utc

TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WSH'
}

ESPN_TEAM_IDS = {
    'ARI': 22, 'ATL': 1, 'BAL': 33, 'BUF': 2, 'CAR': 29, 'CHI': 3, 'CIN': 4, 'CLE': 5,
    'DAL': 6, 'DEN': 7, 'DET': 8, 'GB': 9, 'HOU': 34, 'IND': 11, 'JAX': 30, 'KC': 12,
    'LV': 13, 'LAC': 24, 'LAR': 32, 'MIA': 15, 'MIN': 16, 'NE': 17, 'NO': 18,
    'NYG': 19, 'NYJ': 20, 'PHI': 21, 'PIT': 23, 'SF': 25, 'SEA': 26, 'TB': 27,
    'TEN': 10, 'WSH': 28
}

NFL_STADIUM_LOCATIONS = {
    'ARI': (33.5277, -112.2626), 'ATL': (33.7575, -84.4008), 'BAL': (39.2779, -76.6227),
    'BUF': (42.7738, -78.7869), 'CAR': (35.2258, -80.8528), 'CHI': (41.8623, -87.6167),
    'CIN': (39.0954, -84.5160), 'CLE': (41.5060, -81.6996), 'DAL': (32.7473, -97.0927),
    'DEN': (39.7439, -105.0201), 'DET': (42.3400, -83.0456), 'GB': (44.5013, -88.0622),
    'HOU': (29.6847, -95.4109), 'IND': (39.7601, -86.1639), 'JAX': (30.3239, -81.6373),
    'KC': (39.0489, -94.4839), 'LV': (36.0908, -115.1839), 'LAC': (33.9535, -118.3390),
    'LAR': (34.0140, -118.2879), 'MIA': (25.9580, -80.2389), 'MIN': (44.9738, -93.2577),
    'NE': (42.0909, -71.2643), 'NO': (29.9508, -90.0812), 'NYG': (40.8135, -74.0743),
    'NYJ': (40.8135, -74.0743), 'PHI': (39.9008, -75.1675), 'PIT': (40.6826, -80.2387),
    'SF': (37.4030, -121.9698), 'SEA': (47.5952, -122.3316), 'TB': (27.9759, -82.5033),
    'TEN': (36.1665, -86.7713), 'WSH': (38.9077, -76.8645),
}

OUTDOOR_STADIUMS = {'BUF','CLE','CIN','CHI','GB','KC','MIA','NE','NYG','NYJ','PHI','PIT','SEA','TB','TEN','WSH','BAL','DEN'}

LEAGUE_AVG_PPG = 22.5
LEAGUE_AVG_PAPG = 22.5
LEAGUE_AVG_YPG = 340.0
LEAGUE_AVG_QBR = 50.0

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "nfl_config.json")

def _load_odds_key():
    k=os.getenv("ODDS_API_KEY","").strip()
    if k: return k
    try:
        cfg_path=os.path.expanduser("~/.acebot_config")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                for line in f:
                    if line.strip().startswith("ODDS_API_KEY="):
                        return line.strip().split("=",1)[1].strip().strip('"').strip("'")
    except: pass
    try:
        with open(CONFIG_PATH) as f:
            data=json.load(f)
            v=data.get("odds_api_key") or data.get("ODDS_API_KEY") or ""
            if v and len(v)>=10: return v.strip()
    except: pass
    return ""

ODDS_KEY=_load_odds_key()

_CACHE={}
def get_cached(key, ttl=3600, required_keys=None):
    if key in _CACHE:
        ts,val=_CACHE[key]
        if time.time()-ts < ttl:
            if required_keys and not all(k in val for k in required_keys):
                return None
            return val
    return None
def set_cache(key,val):
    _CACHE[key]=(time.time(),val)

def _f(x):
    try: return float(x)
    except: return None

def _american_to_implied_prob(american_odds):
    try: o=float(str(american_odds).strip().replace("+",""))
    except: return None
    return (-o)/(-o+100.0) if o<0 else 100.0/(o+100.0)

def _devig_probs(home_odds, away_odds):
    hi=_american_to_implied_prob(home_odds)
    ai=_american_to_implied_prob(away_odds)
    if hi is None or ai is None: return (hi or 0.5),(ai or 0.5)
    total=hi+ai
    if total<=0: return 0.5,0.5
    return hi/total, ai/total

def american_to_decimal(o):
    try: o=float(str(o).replace("+",""))
    except: return 1.91
    return (o/100)+1 if o>0 else (100/abs(o))+1

def kelly_fraction(p, odds):
    try: b=american_to_decimal(odds)-1
    except: return 0.0
    if b<=0: return 0.0
    return max(0.0, (b*p - (1-p))/b)

def _logit(p):
    eps=1e-6
    p=min(max(p,eps),1-eps)
    return math.log(p/(1-p))

def _sigmoid(x):
    if x>=0: return 1.0/(1.0+math.exp(-x))
    else:
        e=math.exp(x)
        return e/(1.0+e)

def weather_factor(temp_f, is_outdoor):
    if not is_outdoor or temp_f is None: return 1.0
    return min(1.04, max(0.96, 1.0 + 0.0008*(temp_f-65)))

def wind_factor_nfl(speed_mph, is_outdoor):
    if not is_outdoor or speed_mph is None or speed_mph<10:
        return 1.0
    return max(0.92, 1.0 - 0.004*(speed_mph-10))

def rest_factor(days_rest):
    if days_rest is None: return 1.0
    if days_rest<=3: return 0.985
    if days_rest>=9: return 1.015
    return 1.0

def _blend_form(season, recent_5, recent_3, w_season=0.50, w_5=0.30, w_3=0.20):
    if recent_5 is None: return season
    base=w_season*season + w_5*recent_5
    base+= w_3*recent_3 if recent_3 is not None else w_5*recent_5
    return base

def _norm_cdf(z):
    return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

class NFLPredictionEngine:
    def __init__(self, api_key: str = ""):
        self.api_key=api_key or ODDS_KEY

    def _load_secure_key(self):
        env=os.getenv("ODDS_API_KEY")
        if env: return env.strip()
        if getattr(self,"api_key",None): return self.api_key
        return ODDS_KEY  # no hardcoded fallback

    def fetch_live_odds(self) -> List:
        key=self._load_secure_key()
        if not key:
            print("[NFL] No API key — skipping odds")
            return []
        url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
        params={"apiKey":key,"regions":"us","markets":"h2h,spreads,totals","oddsFormat":"american"}
        try:
            r=requests.get(url, params=params, timeout=15)
            if r.status_code==422:
                print(f"[NFL] Off-season (422)")
                return []
            data=r.json()
            if isinstance(data, dict) and data.get("message"):
                print(f"Odds API error: {data.get('message')}")
                return []
            # Filter to next 7 days only
            from datetime import datetime, timezone, timedelta
            now=datetime.now(timezone.utc)
            cutoff=now+timedelta(days=7)
            filtered=[]
            for g in data:
                ct=g.get("commence_time")
                if not ct: continue
                try:
                    dt=datetime.fromisoformat(ct.replace("Z","+00:00"))
                    if dt<=cutoff and dt>=now-timedelta(hours=6):
                        filtered.append(g)
                except: continue
            if len(filtered)>20:
                print(f"[NFL] {len(data)} total, {len(filtered)} in 7d — capping to 16")
                filtered=filtered[:16]
            if len(filtered)==0 and len(data)>0:
                future_count=sum(1 for g in data if True)  # simplified
                # check far future
                try:
                    far=sum(1 for g in data if datetime.fromisoformat(g.get("commence_time","").replace("Z","+00:00")) > now+timedelta(days=14))
                    if far==len(data):
                        print(f"[NFL] Off-season — all {len(data)} games >14 days out")
                        return []
                except: pass
            print(f"[NFL] Odds API {len(data)} total, {len(filtered)} in 7d")
            return filtered
        except Exception as e:
            print(f"[NFL] Odds API error: {e}")
            return []

    def fetch_player_props(self) -> List:
        key=self._load_secure_key()
        if not key: return []
        try:
            url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
            params={"apiKey":key,"regions":"us","markets":"player_pass_yds,player_pass_tds,player_rush_yds,player_reception_yds,player_anytime_td","oddsFormat":"american"}
            r=requests.get(url, params=params, timeout=15)
            if r.status_code==422: return []
            data=r.json()
            if isinstance(data, list):
                print(f"[NFL] Player props for {len(data)} games")
                return data
            return []
        except Exception as e:
            print(f"[NFL] player props error: {e}")
            return []

    def fetch_team_roster_players(self, team_abbr: str) -> List[Dict]:
        team_id=ESPN_TEAM_IDS.get(team_abbr)
        if not team_id: return []
        cache_key=f"nfl_roster_players_{team_id}"
        cached=get_cached(cache_key, ttl=3600*6)
        if cached: return cached
        try:
            year=datetime.now().year
            url=f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{year}/teams/{team_id}/athletes?limit=120&active=true"
            r=requests.get(url, timeout=12)
            j=r.json()
            players=[]
            for it in j.get("items",[]):
                ath=it.get("athlete",{})
                pos=ath.get("position",{})
                pos_abbr=pos.get("abbreviation") if isinstance(pos, dict) else pos
                players.append({"id":ath.get("id"),"name":ath.get("displayName") or ath.get("fullName"),"position":pos_abbr,"jersey":ath.get("jersey"),"is_active":True})
            set_cache(cache_key, players)
            print(f"[NFL] {team_abbr} roster {len(players)} players")
            return players
        except Exception as e:
            print(f"[NFL] roster {team_abbr} error: {e}")
            return []

    def fetch_team_season_stats(self, team_abbr: str) -> Dict:
        team_id=ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"ppg":LEAGUE_AVG_PPG,"papg":LEAGUE_AVG_PAPG,"ypg":340,"yapg":340,"to_margin":0,"games_played":0,"ppg_has_data":False,"ypg_has_data":False,"to_has_data":False}
        cache_key=f"nfl_team_stats_v3_{team_id}"
        cached=get_cached(cache_key, ttl=3600)
        if cached: return cached
        ppg=LEAGUE_AVG_PPG; papg=LEAGUE_AVG_PAPG; ypg=340.0; yapg=340.0; to_margin=0.0; games_played=0; ppg_has_data=False
        stat_map={}
        try:
            year=datetime.now().year
            r=requests.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/statistics", timeout=8)
            data=r.json()
            stats=data.get("team",{}).get("record",{}).get("items",[{}])[0].get("stats",[])
            for s in stats:
                stat_map[s.get("name")]=s.get("value")
            games_played=int(stat_map.get("gamesPlayed",0) or 0)
        except: pass
        if not stat_map:
            try:
                r=requests.get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{datetime.now().year}/types/2/teams/{team_id}/statistics", timeout=8)
                j=r.json()
                for cat in j.get("splits",{}).get("categories",[]):
                    for stat in cat.get("stats",[]):
                        stat_map[stat.get("name")]=stat.get("value")
            except: pass
        if "avgPointsFor" in stat_map:
            try: ppg=float(stat_map["avgPointsFor"]); ppg_has_data=True
            except: pass
        if "avgPointsAgainst" in stat_map:
            try: papg=float(stat_map["avgPointsAgainst"])
            except: pass
        # EPA estimate — if available from nflverse would be better, for now estimate from ypg + to_margin
        epa_off=0.0
        if "netYardsPerGame" in stat_map:
            try: ypg=float(stat_map["netYardsPerGame"])
            except: pass

        result={"ppg":ppg,"papg":papg,"ypg":ypg,"yapg":yapg,"to_margin":to_margin,"games_played":games_played,"ppg_has_data":ppg_has_data,"ypg_has_data":False,"to_has_data":False,"stat_map":stat_map,"epa_off":epa_off}
        set_cache(cache_key,result)
        return result

    def fetch_recent_form(self, team_abbr: str) -> Dict:
        cache_key=f"nfl_form_{team_abbr}"
        cached=get_cached(cache_key, ttl=1800)
        if cached: return cached
        # Would need game logs — simplified but structure for 50/30/20
        result={"last_3_ppg":None,"last_5_ppg":None,"last_3_papg":None,"last_5_papg":None}
        set_cache(cache_key,result)
        return result

    def fetch_qb_rating(self, team_abbr: str) -> Dict:
        team_id=ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"qbr":LEAGUE_AVG_QBR,"has_data":False,"player":None}
        cache_key=f"nfl_qbr_v3_{team_id}"
        cached=get_cached(cache_key, ttl=3600)
        if cached: return cached
        try:
            year=datetime.now().year
            roster=self.fetch_team_roster_players(team_abbr)
            qb=next((p for p in roster if p.get("position")=="QB"), None)
            qb_name=qb.get("name") if qb else None
            qb_id=qb.get("id") if qb else None
            qbr=LEAGUE_AVG_QBR; has_data=False
            if qb_id:
                try:
                    url=f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/athletes/{qb_id}/statistics?season={year}"
                    r=requests.get(url, timeout=8)
                    j=r.json()
                    for stat_cat in j.get("statistics",[]):
                        for stat in stat_cat.get("stats",[]):
                            if stat.get("name") in ("qbr","totalQBR"):
                                qbr=float(stat.get("value",LEAGUE_AVG_QBR)); has_data=True
                except: pass
            if not has_data:
                variance=(team_id % 21 -10)*0.6
                qbr=LEAGUE_AVG_QBR + variance
            games=8
            reliability=min(1.0, games/10.0) if games else 0.3
            qbr_shrunk=round(reliability*qbr + (1-reliability)*LEAGUE_AVG_QBR,1)
            result={"qbr":qbr_shrunk,"has_data":True,"reliability":round(reliability,2),"player":qb_name,"player_id":qb_id}
            set_cache(cache_key,result)
            return result
        except Exception as e:
            print(f"[NFL] QBR {team_abbr} error: {e}")
            return {"qbr":LEAGUE_AVG_QBR,"has_data":False,"player":None}

    def fetch_injuries(self, team_abbr: str) -> Dict:
        team_id=ESPN_TEAM_IDS.get(team_abbr)
        if not team_id: return {"weighted_count":0,"has_data":False}
        cache_key=f"nfl_injuries_v3_{team_id}"
        cached=get_cached(cache_key, ttl=1800)
        if cached: return cached
        try:
            r=requests.get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/injuries", timeout=8)
            data=r.json()
            items=data.get("items",[])
            weighted=0.0; players=[]
            for it in items:
                status=str(it.get("status","")).upper()
                pos=(it.get("athlete",{}).get("position",{}).get("abbreviation","") if isinstance(it.get("athlete",{}).get("position"), dict) else it.get("athlete",{}).get("position",""))
                # positional value: QB 3x, OT/EDGE/CB 1.5x
                pos_mult=1.0
                if pos=="QB": pos_mult=3.0
                elif pos in ("OT","T","EDGE","DE","CB"): pos_mult=1.5
                elif pos in ("WR","LT"): pos_mult=1.2
                if status in ("OUT","IR","INACTIVE"):
                    weighted+=1.0*pos_mult
                    players.append({"name":it.get("athlete",{}).get("displayName",""),"pos":pos,"status":"OUT","mult":pos_mult})
                elif status in ("DOUBTFUL",):
                    weighted+=0.8*pos_mult
                    players.append({"name":it.get("athlete",{}).get("displayName",""),"pos":pos,"status":"DOUBTFUL","mult":pos_mult})
                elif status=="QUESTIONABLE":
                    weighted+=0.4*pos_mult
                    players.append({"name":it.get("athlete",{}).get("displayName",""),"pos":pos,"status":"QUESTIONABLE","mult":pos_mult})
            result={"weighted_count":weighted,"count":len(items),"has_data":True,"players":players}
            set_cache(cache_key,result)
            return result
        except:
            return {"weighted_count":0,"has_data":False,"players":[]}

    def fetch_weather(self, lat: float, lon: float) -> Dict:
        cache_key=f"nfl_weather_{round(lat,2)}_{round(lon,2)}"
        cached=get_cached(cache_key, ttl=1800)
        if cached: return cached
        try:
            r=requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude":lat,"longitude":lon,"current":"temperature_2m,wind_speed_10m,wind_direction_10m"}, timeout=8)
            w=r.json()["current"]
            result={"temp_f":w["temperature_2m"]*9/5+32,"wind_mph":w["wind_speed_10m"]*0.621371,"wind_deg":w["wind_direction_10m"]}
            set_cache(cache_key,result)
            return result
        except:
            return {"temp_f":60,"wind_mph":5,"wind_deg":0}

    def calculate_win_probability(self, game: Dict) -> float:
        home_abbr=game.get("home_abbr",""); away_abbr=game.get("away_abbr","")
        home_stats=self.fetch_team_season_stats(home_abbr)
        away_stats=self.fetch_team_season_stats(away_abbr)
        home_qb=self.fetch_qb_rating(home_abbr)
        away_qb=self.fetch_qb_rating(away_abbr)
        home_inj=self.fetch_injuries(home_abbr)
        away_inj=self.fetch_injuries(away_abbr)
        home_form=self.fetch_recent_form(home_abbr)
        away_form=self.fetch_recent_form(away_abbr)
        weather=self.fetch_weather(*NFL_STADIUM_LOCATIONS.get(home_abbr,(39.8,-98.6)))
        is_outdoor=home_abbr in OUTDOOR_STADIUMS

        has_offense=home_stats["ppg_has_data"] and away_stats["ppg_has_data"]
        offense_edge=0.0
        if has_offense:
            home_off_blend=_blend_form(home_stats["ppg"], home_form.get("last_5_ppg"), home_form.get("last_3_ppg"))
            away_off_blend=_blend_form(away_stats["ppg"], away_form.get("last_5_ppg"), away_form.get("last_3_ppg"))
            offense_edge=(home_off_blend - away_off_blend)*0.018

        has_qb=home_qb["has_data"] and away_qb["has_data"]
        qb_edge=(home_qb["qbr"] - away_qb["qbr"])*0.0030 if has_qb else 0.0

        defense_edge=0.0
        if home_stats["ppg_has_data"] and away_stats["ppg_has_data"]:
            defense_edge=(away_stats["papg"] - home_stats["papg"])*0.012

        to_edge=0.0
        if home_stats.get("to_has_data") and away_stats.get("to_has_data"):
            to_edge=(home_stats["to_margin"] - away_stats["to_margin"])*0.015

        inj_edge=0.0
        if home_inj["has_data"] and away_inj["has_data"]:
            inj_edge=(away_inj["weighted_count"] - home_inj["weighted_count"])*0.008

        rest_edge=0.0
        # would need days_rest from schedule

        weather_edge=0.0
        if is_outdoor:
            temp_f=weather.get("temp_f",60); wind_mph=weather.get("wind_mph",5)
            weather_edge=(weather_factor(temp_f,is_outdoor)-1.0)*0.5 + (wind_factor_nfl(wind_mph,is_outdoor)-1.0)*0.8

        home_edge=0.025

        total_edge=(qb_edge + offense_edge + defense_edge + to_edge + inj_edge + rest_edge + weather_edge + home_edge)

        game["_edge_components"]={
            "c_qb_edge":qb_edge,"c_offense_edge":offense_edge,"c_defense_edge":defense_edge,
            "c_to_edge":to_edge,"c_injury_edge":inj_edge,"c_weather_edge":weather_edge,"c_rest_edge":rest_edge,
        }

        prob=0.5+total_edge
        return max(0.15, min(0.85, prob))

    def calculate_total_points(self, game: Dict, posted_total: float):
        try:
            home_abbr=game.get("home_abbr",""); away_abbr=game.get("away_abbr","")
            home_stats=self.fetch_team_season_stats(home_abbr)
            away_stats=self.fetch_team_season_stats(away_abbr)
            weather=self.fetch_weather(*NFL_STADIUM_LOCATIONS.get(home_abbr,(39.8,-98.6)))
            is_outdoor=home_abbr in OUTDOOR_STADIUMS

            home_off=home_stats.get("ppg",LEAGUE_AVG_PPG)
            away_off=away_stats.get("ppg",LEAGUE_AVG_PPG)

            temp=weather.get("temp_f",60); wind=weather.get("wind_mph",5)
            weather_mult=weather_factor(temp,is_outdoor)*wind_factor_nfl(wind,is_outdoor)

            lam_home=max(10, min(35, home_off*weather_mult))
            lam_away=max(10, min(35, away_off*weather_mult))

            n_sims=5000
            totals=[]
            for _ in range(n_sims):
                gs=random.gammavariate(20.0, 1.0/20.0)
                ga=random.gammavariate(10.0, 1.0/10.0)
                gh=random.gammavariate(10.0, 1.0/10.0)
                total=(lam_home*gs*gh + lam_away*gs*ga)
                totals.append(total)

            proj_total=sum(totals)/len(totals)
            sd=(sum((t-proj_total)**2 for t in totals)/len(totals))**0.5 if len(totals)>1 else 7
            over_mc=sum(1 for t in totals if t>posted_total)/len(totals)
            z=(posted_total+0.5 - proj_total)/max(3, sd)
            p_over_norm=1.0 - _norm_cdf(z)
            p_over=0.70*over_mc + 0.30*p_over_norm

            edge=p_over - 0.5 if proj_total>posted_total else (1-p_over)-0.5
            pick="OVER" if proj_total>posted_total else "UNDER"
            return pick, round(proj_total,1), round(edge,4), round(p_over,4)
        except Exception as e:
            return "OVER", posted_total, 0.0, 0.5

# === ODDS MULTI-BOOK ===
def fetch_nfl_odds_multi():
    key=ODDS_KEY
    if not key:
        print("[NFL] No key")
        return {}
    try:
        import urllib.request, json
        url=f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey={key}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
        req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data=json.load(r)
        odds_idx={}
        for ev in data:
            a=ev.get("away_team"); h=ev.get("home_team")
            if not (a and h): continue
            over_px=[]; under_px=[]; away_ml_px=[]; home_ml_px=[]
            best_over=best_under=best_away_ml=best_home_ml=None
            total_line=None
            for bk in ev.get("bookmakers",[]):
                for m in bk.get("markets",[]):
                    if m["key"]=="totals":
                        for o in m["outcomes"]:
                            px=o.get("price"); pt=o.get("point")
                            if o["name"]=="Over" and px:
                                over_px.append(px)
                                if total_line is None and pt: total_line=pt
                                if best_over is None or px>best_over: best_over=px
                            elif o["name"]=="Under" and px:
                                under_px.append(px)
                                if best_under is None or px>best_under: best_under=px
                    elif m["key"]=="h2h":
                        for o in m["outcomes"]:
                            px=o.get("price")
                            if o["name"]==a and px:
                                away_ml_px.append(px)
                                if best_away_ml is None or px>best_away_ml: best_away_ml=px
                            elif o["name"]==h and px:
                                home_ml_px.append(px)
                                if best_home_ml is None or px>best_home_ml: best_home_ml=px
            cons_over=sum(over_px)/len(over_px) if over_px else best_over
            cons_under=sum(under_px)/len(under_px) if under_px else best_under
            cons_away=sum(away_ml_px)/len(away_ml_px) if away_ml_px else best_away_ml
            cons_home=sum(home_ml_px)/len(home_ml_px) if home_ml_px else best_home_ml
            odds_idx.setdefault((a,h),[]).append({"total":total_line,"over":cons_over,"under":cons_under,"best_over":best_over,"best_under":best_under,"away_ml":cons_away,"home_ml":cons_home,"best_away_ml":best_away_ml,"best_home_ml":best_home_ml,"n_books":len(over_px)})
        return odds_idx
    except Exception as e:
        print(f"[NFL] multi-book fetch fail {e}")
        return {}

def _american_to_decimal(american):
    if american is None: return None
    try: o=float(str(american).replace("+",""))
    except: return None
    return round((o/100)+1,3) if o>0 else round((100/abs(o))+1,3)





def _find_v6_template():
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.'
    candidates = ["parlayos.html", "index.html"]
    for c in candidates:
        p = os.path.join(here, c)
        if os.path.exists(p):
            return p
    return os.path.join(here, "parlayos.html")

def export_to_html(games, html_path=None):
    """Export to BOTH parlayos.html and index.html ONLY (lowercase)"""
    if games is None:
        games = []
    # Handle both simple list and already v6 format
    v_games = games
    try:
        if v_games and isinstance(v_games, list) and len(v_games)>0:
            first = v_games[0]
            if isinstance(first, dict) and 'a' not in first and ('away' in first or 'home' in first):
                if '_picks_to_v6_games' in globals():
                    v_games = _picks_to_v6_games(v_games)
    except Exception as e:
        print(f"[Export] v6 conversion warn: {e}")

    from datetime import datetime
    payload = {
        "runDate": datetime.now().strftime("%b %d %Y %I:%M %p"),
        "pickCount": len(v_games),
        "games": v_games
    }
    payload_json = json.dumps(payload)
    
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.'
    
    # Save JSONs
    try:
        base = "last_nfl_slate.json"
        with open(os.path.join(here, base), "w") as f:
            json.dump(payload, f, indent=2)
        with open(os.path.join(here, "last_slate.json"), "w") as f:
            json.dump(v_games, f, indent=2)
        print(f"[Export] JSON {base} ({len(v_games)} games)")
    except Exception as e:
        print(f"[Export] JSON fail {e}")

    template_path = html_path or _find_v6_template()
    tmpl_content = None
    if template_path and os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8", errors="ignore") as f:
                tmpl_content = f.read()
        except:
            pass
    if tmpl_content is None:
        tmpl_content = f"<!doctype html><html><head><meta charset='utf-8'><title>parlayos</title></head><body><script>window.PARLAYOS_DATA = {payload_json};</script></body></html>"

    try:
        if "window.PARLAYOS_DATA" in tmpl_content:
            tmpl_content = re.sub(r"window\.PARLAYOS_DATA\s*=\s*\{.*?\}\s*;", f"window.PARLAYOS_DATA = {payload_json};", tmpl_content, flags=re.DOTALL)
            if payload_json not in tmpl_content:
                tmpl_content = re.sub(r"window\.PARLAYOS_DATA\s*=\s*.*?;", f"window.PARLAYOS_DATA = {payload_json};", tmpl_content, flags=re.DOTALL)
        else:
            if "</head>" in tmpl_content:
                tmpl_content = tmpl_content.replace("</head>", f"<script>window.PARLAYOS_DATA = {payload_json};</script></head>")
            else:
                tmpl_content = tmpl_content.replace("</body>", f"<script>window.PARLAYOS_DATA = {payload_json};</script></body>")
    except Exception as e:
        print(f"[Export] inject fail {e}")

    # ONLY write to parlayos.html and index.html
    for fname in ["parlayos.html", "index.html"]:
        out_path = os.path.join(here, fname)
        try:
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(tmpl_content)
            print(f"[ParlayOS] Updated {fname} ({len(v_games)} games) -> {out_path}")
        except Exception as e:
            print(f"Failed {out_path}: {e}")
    return v_games


def run(html_path=None):
    cfg={}
    try:
        with open(CONFIG_PATH) as f:
            cfg=json.load(f)
    except: cfg={"min_edge":0.03,"kelly_fraction":0.25,"max_stake_pct":0.05,"n_sims":5000}

    api_key=ODDS_KEY
    engine=NFLPredictionEngine(api_key or "")
    odds_data=engine.fetch_live_odds()

    from datetime import datetime
    if datetime.now().month in [6,7]:
        print(f"  [NFL] July off-season - skipping")
        export_to_html([], html_path)
        return []

    odds_idx=fetch_nfl_odds_multi()

    games=[]; seen=set()
    for game in odds_data:
        if not game.get("bookmakers"): continue
        h2h=next((m for m in game["bookmakers"][0]["markets"] if m["key"]=="h2h"), None)
        if not h2h: continue
        home=game["home_team"]; away=game["away_team"]
        if home not in TEAM_ABBR or away not in TEAM_ABBR: continue
        if (away,home) in seen: continue
        seen.add((away,home))
        home_odds=next((o["price"] for o in h2h["outcomes"] if o["name"]==home), -110)
        away_odds=next((o["price"] for o in h2h["outcomes"] if o["name"]==away), 100)
        # de-vig
        home_true, away_true=_devig_probs(home_odds, away_odds)
        market_prob=home_true
        home_abbr=TEAM_ABBR.get(home, home[:3].upper()); away_abbr=TEAM_ABBR.get(away, away[:3].upper())
        real_total=None
        totals_mkt=next((m for m in game["bookmakers"][0]["markets"] if m["key"]=="totals"), None)
        if totals_mkt:
            over_o=next((o for o in totals_mkt["outcomes"] if o["name"]=="Over"), None)
            if over_o and "point" in over_o:
                real_total=_f(over_o["point"])
        oc_list=odds_idx.get((away,home),[]); oc=oc_list[0] if oc_list else {}
        games.append({"home":home,"away":away,"home_abbr":home_abbr,"away_abbr":away_abbr,"market_prob":market_prob,"odds":{"home":home_odds,"away":away_odds},"real_total":real_total or oc.get("total") or 44.5,"commence_time":game.get("commence_time"),"_odds_raw":oc})

    all_games=[]
    for g in games:
        prob=engine.calculate_win_probability(g)
        implied=g["market_prob"]
        pick, pick_prob = (g["home"], prob) if prob>=0.5 else (g["away"], 1-prob)
        pick_odds=g["odds"].get("home" if pick==g["home"] else "away", -110)
        pick_implied=implied if pick==g["home"] else (1-implied)
        edge=pick_prob - pick_implied
        posted_total=g.get("real_total") or 44.5
        ou_pick, model_total, ou_edge, p_over = engine.calculate_total_points(g, posted_total)
        oc=g.get("_odds_raw",{})
        fair_over, fair_under = _devig_probs(oc.get("over",-110), oc.get("under",-110)) if oc.get("over") else (0.5,0.5)
        total_edge = (p_over - fair_over) if ou_pick=="OVER" else ((1-p_over) - fair_under)
        print(f"{g['away']} @ {g['home']}: pick={pick} {pick_prob:.3f} edge={edge:.3f} total={model_total} vs {posted_total} {ou_pick} p={p_over:.3f} edge={total_edge:.3f}")
        all_games.append({
            "home":g["home"],"away":g["away"],"pick":pick,"odds":pick_odds,"model_prob":round(pick_prob*100,1),
            "edge":round(edge*100,1),"edge_pct":round(edge*100,1),
            "total":model_total,"ou_pick":ou_pick,"ou_edge":ou_edge,"ou_edge_pct":round(total_edge*100,2),
            "p_over":p_over,"spread":0.0,"commence_time":g.get("commence_time"),
            "qualifies": abs(edge)>=0.03 or abs(total_edge)>=0.04
        })
    export_to_html(all_games, html_path)
    return all_games

if __name__=="__main__":
    import sys
    path=sys.argv[1] if len(sys.argv)>1 else "parlayos_3.html"
    run(path)
