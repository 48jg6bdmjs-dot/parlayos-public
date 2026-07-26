#!/usr/bin/env python3
"""
================================================================================
 backtest_core.py â€” Shared Core for ACE (with YouTube Vision)
================================================================================
 Used by mlb_backtest.py, nfl_backtest.py, nba_backtest.py

 What it adds:
 - YT Vision performance: high conf vs low conf, with clips vs no clips
 - Auto-tunes youtube.weight_* per sport
 - Sport-aware line bands

 Run via wrappers, not directly:
   python mlb_backtest.py --dry-run
   python nfl_backtest.py --dry-run
   python nba_backtest.py --dry-run
================================================================================
"""
import csv, json, os, sys, uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

def _f(x):
    try:
        return float(str(x).strip().replace('+','').replace('%',''))
    except:
        return None

def _pct(x):
    if x is None: return "n/a"
    return f"{100*x:.1f}%"

def _roi(x):
    if x is None: return "n/a"
    return f"{100*x:+.1f}%"

def _american_to_implied(o):
    o = _f(o)
    if o is None: return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)

def _clv_pts(open_odds, close_odds):
    op = _american_to_implied(open_odds)
    cl = _american_to_implied(close_odds)
    if op is None or cl is None: return None
    return round((cl - op) * 100, 2)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# LIVE TRADE TRACKING (shared)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _parse_bet_string(s):
    parts = s.strip().split()
    odds = None
    for i, p in enumerate(parts):
        try:
            v = int(p.replace('+',''))
            if abs(v) >= 100:
                odds = int(p); parts.pop(i); break
        except ValueError:
            pass
    market = 'Moneyline'
    for keyword in ('OVER','UNDER','K','SPREAD','RL'):
        if any(keyword.lower() in x.lower() for x in parts):
            market = 'Total' if keyword in ('OVER','UNDER') else keyword; break
    pick = ' '.join(parts)
    return {'pick': pick, 'market': market, 'odds': odds}

def track_live_bet(csv_path, description, stake=1.0, tag='live'):
    parsed = _parse_bet_string(description)
    bet_id = str(uuid.uuid4())[:8].upper()
    row = {
        'date': date.today().isoformat(),
        'timestamp': datetime.now().isoformat(),
        'tag': tag,
        'team': parsed['pick'],
        'pick': parsed['pick'],
        'market': parsed['market'],
        'odds': parsed['odds'],
        'open_ml': parsed['odds'],
        'model_prob': '',
        'edge_pct': '',
        'qualifies': True,
        'won': '',
        'profit_1u': '',
        'close_ml': '',
        'clv_pts': '',
        'slip_id': bet_id,
        'kind': 'live_trade',
        'yt_confidence': '',
        'yt_momentum': '',
        'yt_gameplay_pct': '',
        'yt_videos': '',
    }
    exists = os.path.exists(csv_path)
    if exists:
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or list(row.keys())
            for col in row:
                if col not in fieldnames:
                    fieldnames.append(col)
    else:
        fieldnames = list(row.keys())
    with open(csv_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not exists: writer.writeheader()
        writer.writerow(row)
    print(f"âœ“ Tracked bet [{bet_id}]: {description}")
    print(f"  Use --bet-id {bet_id} with --close or --grade")
    return bet_id

def close_live_bet(csv_path, bet_id, close_description):
    parsed = _parse_bet_string(close_description)
    close_odds = parsed['odds']
    rows = []
    updated = False
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            if row.get('slip_id','').upper() == bet_id.upper() and row.get('kind') == 'live_trade':
                open_odds = _f(row.get('open_ml'))
                row['close_ml'] = close_odds
                row['clv_pts'] = _clv_pts(open_odds, close_odds) if open_odds else ''
                updated = True
            rows.append(row)
    if not updated:
        print(f"Bet {bet_id} not found"); return
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"âœ“ Closed [{bet_id}] at {close_odds}, CLV {rows[-1].get('clv_pts')} pts")

def grade_live_bet(csv_path, bet_id, result):
    result = result.lower()
    if result not in ('won','win','loss','lost','push'):
        print("Use won/loss/push"); return
    won_map = {'won':1,'win':1,'loss':0,'lost':0,'push':0.5}
    won = won_map[result]
    rows = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            if row.get('slip_id','').upper() == bet_id.upper():
                row['won'] = won
                # Simple profit calc
                odds = _f(row.get('odds'))
                if odds is not None:
                    if won==1:
                        row['profit_1u'] = (odds/100) if odds>0 else (100/abs(odds))
                    elif won==0:
                        row['profit_1u'] = -1
                    else:
                        row['profit_1u'] = 0
            rows.append(row)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"âœ“ Graded [{bet_id}] as {result}")

def list_live_bets(csv_path):
    if not os.path.exists(csv_path):
        print("No picks_log.csv"); return
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('kind')=='live_trade':
                status = "OPEN" if row.get('won')=='' else row.get('won')
                print(f"{row.get('slip_id')} | {row.get('date')} | {row.get('pick')} {row.get('odds')} | {status} | CLV {row.get('clv_pts','')}")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CORE ANALYSIS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def analyse(csv_path, sport_cfg):
    """
    sport_cfg = {
      "sport": "mlb",
      "line_floor": 6.0, "line_ceil": 13.5,
      "min_bets": 15
    }
    """
    if not os.path.exists(csv_path):
        return {"error": f"{csv_path} not found"}

    rows = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    graded = [r for r in rows if str(r.get('won','')).strip() != '']
    if not graded:
        return {"error": "No graded bets yet", "total_rows": len(rows)}

    # Basic aggregates
    def calc_stats(sub_rows):
        if not sub_rows: return None
        bets = len(sub_rows)
        wins = sum(1 for r in sub_rows if _f(r.get('won'))==1)
        pushes = sum(1 for r in sub_rows if _f(r.get('won'))==0.5)
        profit = sum(_f(r.get('profit_1u')) or 0 for r in sub_rows)
        win_rate = wins / (bets - pushes) if (bets-pushes)>0 else 0
        roi = profit / bets if bets>0 else 0
        return {"bets": bets, "wins": wins, "pushes": pushes, "profit": profit, "win_rate": win_rate, "roi": roi}

    overall = calc_stats(graded)
    totals = calc_stats([r for r in graded if 'OVER' in str(r.get('pick','')).upper() or 'UNDER' in str(r.get('pick','')).upper()])
    moneylines = calc_stats([r for r in graded if r.get('market','').lower()=='moneyline'])
    live_trades = calc_stats([r for r in graded if r.get('kind')=='live_trade'])

    # Edge buckets
    by_edge = {}
    for bucket, filt in [
        ("tight (<5%)", lambda r: (_f(r.get('edge_pct')) or 0) < 5),
        ("mid (5-10%)", lambda r: 5 <= (_f(r.get('edge_pct')) or 0) < 10),
        ("wide (>10%)", lambda r: (_f(r.get('edge_pct')) or 0) >= 10),
        ("unknown", lambda r: _f(r.get('edge_pct')) is None),
    ]:
        by_edge[bucket] = calc_stats([r for r in graded if filt(r)])

    # Line bands - sport specific
    sport = sport_cfg.get("sport","mlb")
    if sport=="mlb":
        line_bands = [
            ("low (<7.5)", lambda r: (_f(r.get('total')) or _f(r.get('line')) or 0) < 7.5),
            ("mid (7.5-9)", lambda r: 7.5 <= (_f(r.get('total')) or _f(r.get('line')) or 99) <= 9),
            ("high (>9)", lambda r: (_f(r.get('total')) or _f(r.get('line')) or 0) > 9),
        ]
    elif sport=="nfl":
        line_bands = [
            ("low (<42)", lambda r: (_f(r.get('total')) or 0) < 42),
            ("mid (42-48)", lambda r: 42 <= (_f(r.get('total')) or 0) <= 48),
            ("high (>48)", lambda r: (_f(r.get('total')) or 0) > 48),
        ]
    else: # nba
        line_bands = [
            ("low (<220)", lambda r: (_f(r.get('total')) or 0) < 220),
            ("mid (220-230)", lambda r: 220 <= (_f(r.get('total')) or 0) <= 230),
            ("high (>230)", lambda r: (_f(r.get('total')) or 0) > 230),
        ]
    by_line = {name: calc_stats([r for r in graded if filt(r)]) for name,filt in line_bands}

    # CLV
    clv_rows = [r for r in graded if _f(r.get('clv_pts')) is not None]
    clv = None
    if clv_rows:
        clvs = [_f(r.get('clv_pts')) for r in clv_rows]
        clv = {
            "n": len(clvs),
            "avg": sum(clvs)/len(clvs) if clvs else 0,
            "pct_positive": sum(1 for c in clvs if c>0)/len(clvs) if clvs else 0
        }

    # YOUTUBE VISION ANALYSIS â€” NEW
    yt_stats = {}
    yt_rows = [r for r in graded if _f(r.get('yt_confidence')) is not None and _f(r.get('yt_confidence'))>0]
    if yt_rows:
        # High vs low confidence
        high_conf = [r for r in yt_rows if (_f(r.get('yt_confidence')) or 0) >= 0.7]
        mid_conf = [r for r in yt_rows if 0.3 <= (_f(r.get('yt_confidence')) or 0) < 0.7]
        low_conf = [r for r in yt_rows if (_f(r.get('yt_confidence')) or 0) < 0.3]
        with_clips = [r for r in graded if (_f(r.get('yt_videos')) or 0) > 0]
        no_clips = [r for r in graded if (_f(r.get('yt_videos')) or 0) == 0 and r in graded]  # graded but no YT

        yt_stats = {
            "n_yt": len(yt_rows),
            "high_conf": calc_stats(high_conf),
            "mid_conf": calc_stats(mid_conf),
            "low_conf": calc_stats(low_conf),
            "with_clips": calc_stats(with_clips),
            "no_clips": calc_stats(no_clips),
            # Gameplay filter effectiveness
            "high_gameplay": calc_stats([r for r in yt_rows if (_f(r.get('yt_gameplay_pct')) or 0) >= 0.8]),
            "low_gameplay": calc_stats([r for r in yt_rows if (_f(r.get('yt_gameplay_pct')) or 0) < 0.6]),
        }

    # Calibration
    prob_rows = [r for r in graded if _f(r.get('model_prob')) is not None]
    calibration = None
    if len(prob_rows) >= 10:
        buckets = defaultdict(list)
        for r in prob_rows:
            p = _f(r.get('model_prob'))
            if p is None: continue
            if p<0.5: band="40-50%"
            elif p<0.6: band="50-60%"
            elif p<0.7: band="60-70%"
            else: band="70%+"
            buckets[band].append(r)
        cal_buckets = []
        brier = 0
        for band, br in buckets.items():
            pred = sum(_f(x.get('model_prob')) or 0 for x in br)/len(br) if br else 0
            actual = sum(_f(x.get('won')) or 0 for x in br)/len(br) if br else 0
            brier += sum(((_f(x.get('model_prob')) or 0)-(_f(x.get('won')) or 0))**2 for x in br)
            cal_buckets.append({"band": band, "n": len(br), "predicted_wr": pred, "actual_wr": actual, "gap": actual-pred})
        brier = brier/len(prob_rows) if prob_rows else 0
        calibration = {"n": len(prob_rows), "brier_score": brier, "buckets": cal_buckets, "n_missing_prob": len(graded)-len(prob_rows)}
    else:
        calibration = {"insufficient": True, "n": len(prob_rows), "n_missing_prob": len(graded)-len(prob_rows)}

    return {
        "total_rows": len(rows),
        "graded": overall,
        "totals": totals,
        "moneylines": moneylines,
        "live_trades": live_trades,
        "by_edge": by_edge,
        "by_line": by_line,
        "clv": clv,
        "yt": yt_stats,
        "calibration": calibration,
        "_totals_rows": graded,
    }

def tune_config(analysis, sport_cfg):
    """
    Returns tuned config + notes
    sport_cfg includes: sport, edge_min/max, line_floor/ceil, min_bets
    """
    sport = sport_cfg.get("sport","mlb")
    edge_min = sport_cfg.get("edge_min",0.02)
    edge_max = sport_cfg.get("edge_max",0.10)
    line_floor = sport_cfg.get("line_floor",6.0)
    line_ceil = sport_cfg.get("line_ceil",13.5)
    min_bets = sport_cfg.get("min_bets",15)

    # Load current config
    config_path = sport_cfg.get("config_path")
    try:
        with open(config_path) as f:
            current = json.load(f)
    except:
        current = {"edge_threshold": 0.045, "min_total_line": line_floor, "max_total_line": line_ceil}

    edge_thresh = current.get("edge_threshold", 0.045)
    min_line = current.get("min_total_line", line_floor)
    max_line = current.get("max_total_line", line_ceil)

    notes = []
    totals = analysis.get("totals")
    by_edge = analysis.get("by_edge", {})
    by_line = analysis.get("by_line", {})

    # Tune edge
    if totals and totals["bets"] >= min_bets:
        tight = by_edge.get("tight (<5%)")
        wide = by_edge.get("wide (>10%)")
        if tight and tight["roi"] is not None and tight["roi"] < -0.05:
            edge_thresh = min(edge_max, edge_thresh+0.01)
            notes.append(f"Raised edge_threshold to {edge_thresh:.3f} (tight edge losing)")
        elif wide and wide["roi"] is not None and wide["roi"] > 0.05 and totals["roi"]>0:
            edge_thresh = max(edge_min, edge_thresh-0.005)
            notes.append(f"Lowered edge_threshold to {edge_thresh:.3f} (wide edge profitable)")

    # Tune line bands
    best_band = None
    best_roi = -999
    for band_name, stats in by_line.items():
        if stats and stats["bets"]>=5 and stats["roi"]>best_roi:
            best_roi = stats["roi"]
            best_band = band_name
    if best_band and best_roi>0.03:
        notes.append(f"Best line band is {best_band} ROI {best_roi:+.1%} - consider narrowing")

    # YT weight tuning
    yt = analysis.get("yt", {})
    yt_weight_notes = []
    if yt and yt.get("n_yt",0) >= 10:
        high = yt.get("high_conf")
        low = yt.get("low_conf")
        if high and low and high["roi"] is not None and low["roi"] is not None:
            if high["roi"] - low["roi"] > 0.05:
                # High conf YT is helping
                notes.append(f"YT high conf ROI {high['roi']:+.1%} vs low {low['roi']:+.1%} - YT is predictive, keep weight")
            elif low["roi"] > high["roi"] + 0.05:
                notes.append(f"YT low conf beating high conf - consider lowering youtube.weight_{sport}")

        with_clips = yt.get("with_clips")
        no_clips = yt.get("no_clips")
        if with_clips and no_clips and with_clips["bets"]>=5 and no_clips["bets"]>=5:
            if with_clips["roi"] > no_clips["roi"] + 0.03:
                notes.append(f"Games WITH YT clips ROI {with_clips['roi']:+.1%} vs no clips {no_clips['roi']:+.1%} - YT helps")

    tuned = {
        "edge_threshold": edge_thresh,
        "min_total_line": min_line,
        "max_total_line": max_line,
        "n_sims": current.get("n_sims",20000),
        "kelly_fraction": current.get("kelly_fraction",0.25),
        "max_stake_pct": current.get("max_stake_pct",0.05),
    }
    # Preserve YT weights
    for k in list(current.keys()):
        if k.startswith("youtube") or k.startswith("yt") or "youtube" in k.lower():
            tuned[k]=current[k]

    return tuned, notes

def print_report(analysis, cfg, notes, wrote, sport):
    W=72
    print("="*W)
    print(f"  ACE BACKTEST â€” {sport.upper()} â€” {date.today().isoformat()}")
    print("="*W)
    o = analysis.get("graded")
    if not o:
        print("No graded bets")
        return
    print(f"  Graded bets : {o['bets']}   (win {_pct(o['win_rate'])})")
    print(f"  Total P&L   : {o['profit']:+.2f} u")
    print(f"  Overall ROI : {_roi(o['roi'])}")
    if analysis.get("totals"):
        t=analysis["totals"]
        print(f"  Totals only : {t['bets']} bets, win {_pct(t['win_rate'])}, ROI {_roi(t['roi'])}")
    if analysis.get("moneylines"):
        m=analysis["moneylines"]
        print(f"  Moneyline   : {m['bets']} bets, win {_pct(m['win_rate'])}, ROI {_roi(m['roi'])}")
    if analysis.get("live_trades"):
        lt=analysis["live_trades"]
        print(f"  Live trades : {lt['bets']} bets, win {_pct(lt['win_rate'])}, ROI {_roi(lt['roi'])}")

    print(f"\n-- TOTALS BY EDGE BUCKET " + "-"*(W-25))
    for k in ("tight (<5%)","mid (5-10%)","wide (>10%)","unknown"):
        b=analysis["by_edge"].get(k)
        if b: print(f"  {k:<13} {b['bets']:3d} bets  win {_pct(b['win_rate'])}  ROI {_roi(b['roi'])}")

    print(f"\n-- TOTALS BY LINE BAND " + "-"*(W-23))
    for k, b in analysis["by_line"].items():
        if b: print(f"  {k:<15} {b['bets']:3d} bets  win {_pct(b['win_rate'])}  ROI {_roi(b['roi'])}")

    # YT REPORT
    yt = analysis.get("yt", {})
    if yt and yt.get("n_yt",0)>0:
        print(f"\n-- YOUTUBE VISION " + "-"*(W-23))
        print(f"  n={yt['n_yt']} graded bets with YT data")
        if yt.get("high_conf"):
            hc=yt["high_conf"]
            print(f"  high conf (â‰¥70%) {hc['bets']:3d} bets  win {_pct(hc['win_rate'])}  ROI {_roi(hc['roi'])}")
        if yt.get("mid_conf"):
            mc=yt["mid_conf"]
            print(f"  mid conf (30-70%) {mc['bets']:3d} bets  win {_pct(mc['win_rate'])}  ROI {_roi(mc['roi'])}")
        if yt.get("low_conf"):
            lc=yt["low_conf"]
            print(f"  low conf (<30%)  {lc['bets']:3d} bets  win {_pct(lc['win_rate'])}  ROI {_roi(lc['roi'])}")
        if yt.get("with_clips"):
            wc=yt["with_clips"]
            print(f"  WITH YT clips    {wc['bets']:3d} bets  win {_pct(wc['win_rate'])}  ROI {_roi(wc['roi'])}")
        if yt.get("no_clips"):
            nc=yt["no_clips"]
            print(f"  NO YT clips      {nc['bets']:3d} bets  win {_pct(nc['win_rate'])}  ROI {_roi(nc['roi'])}")
        if yt.get("high_gameplay"):
            hg=yt["high_gameplay"]
            if hg: print(f"  high gameplayâ‰¥80% {hg['bets']:3d} bets  win {_pct(hg['win_rate'])}  ROI {_roi(hg['roi'])}  (ad filter working)")
    else:
        print(f"\n-- YOUTUBE VISION " + "-"*(W-23))
        print(f"  No graded bets with YT data yet â€” need to log yt_confidence in picks_log.csv")

    if analysis.get("clv"):
        c=analysis["clv"]
        print(f"\n-- CLV " + "-"*(W-7))
        print(f"  n={c['n']}  avg {c['avg']:+.2f} pts  positive {_pct(c['pct_positive'])}")

    cal=analysis.get("calibration")
    if cal and not cal.get("insufficient"):
        print(f"\n-- MODEL CALIBRATION " + "-"*(W-21))
        print(f"  n={cal['n']} picks, Brier {cal['brier_score']:.3f} (0.25=coin flip)")
        for b in cal["buckets"]:
            flag = "  <- overconfident" if b["gap"]<-0.08 else ("  <- underconfident" if b["gap"]>0.08 else "")
            print(f"  {b['band']:<10} {b['n']:6d} {_pct(b['predicted_wr']):>11} {_pct(b['actual_wr']):>11} {100*b['gap']:+7.1f}%{flag}")

    print(f"\n-- TUNED THRESHOLDS " + "-"*(W-20))
    print(f"  edge_threshold : {100*cfg['edge_threshold']:.1f}%")
    print(f"  total line band: {cfg['min_total_line']:.1f} - {cfg['max_total_line']:.1f}")
    for n in notes: print(f"    - {n}")
    print(f"  {'WROTE config' if wrote else 'dry-run (config not written)'}")
    print("="*W)
