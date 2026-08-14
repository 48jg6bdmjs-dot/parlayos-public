import json, os, sys, traceback, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHD_FILES = {
    "combined": "parlayos_chd_data.json",
    "mlb": "parlayos_mlb_chd.json",
    "nfl": "parlayos_nfl_chd.json",
    "nba": "parlayos_nba_chd.json",
}


def _run_one(name, module_path, html_path):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    try:
        import importlib.util
        module_path = os.path.join(BASE_DIR, module_path)
        unique_name = f"{name.replace(' ','_').replace('(','').replace(')','').replace('.','_')}_{int(time.time()*1000000)}_{os.getpid()}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            print(f"X {name}: Could not load spec for {module_path}")
            return False, 0, 0
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(unique_name, None)
        if hasattr(module, 'run'):
            try:
                picks = module.run(html_path)
            except TypeError:
                picks = module.run()
        elif hasattr(module, 'main'):
            module.main()
            picks = []
        else:
            print(f"X {name}: no run() or main()")
            return False, 0, 0
        qualify = sum(1 for p in (picks or []) if isinstance(p, dict) and p.get('qualifies', True))
        print(f"OK {name}: {len(picks or [])} games, {qualify} qualify")
        return True, len(picks or []), qualify
    except Exception as e:
        print(f"X {name}: FAILED - {e}")
        traceback.print_exc()
        return False, 0, 0


def _load_json(name):
    path = os.path.join(BASE_DIR, CHD_FILES[name])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing CHD output: {CHD_FILES[name]}")
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid CHD JSON object: {CHD_FILES[name]}")
    return data


def _validate_chd_payloads():
    payloads = {name: _load_json(name) for name in CHD_FILES}
    for sport in ("mlb", "nfl", "nba"):
        data = payloads[sport]
        if not isinstance(data.get("games"), list):
            raise ValueError(f"{CHD_FILES[sport]} is missing its games array")
        schedules = data.get("schedules", {})
        if schedules is not None and not isinstance(schedules, (dict, list)):
            raise ValueError(f"{CHD_FILES[sport]} has invalid schedules")
    combined = payloads["combined"]
    for sport in ("mlb", "nfl", "nba"):
        if not isinstance(combined.get(sport), dict):
            raise ValueError(f"{CHD_FILES['combined']} is missing {sport} data")
        combined_games = combined[sport].get("games")
        if not isinstance(combined_games, list):
            raise ValueError(f"{CHD_FILES['combined']} is missing {sport}.games")
        if combined_games != payloads[sport].get("games"):
            raise ValueError(f"{CHD_FILES['combined']} does not match {CHD_FILES[sport]}")
    print("OK CHD JSON validation: combined + MLB + NFL + NBA are present and consistent")
    return payloads


def _install_runtime_chd_loader(html):
    import re
    for script_id in ("parlayos-unified-injection", "CHD_DATA_INJECTION", "CHD_WIRING", "parlayos-live-scores-injected"):
        html = re.sub(rf'<script\b[^>]*\bid=["\']{re.escape(script_id)}["\'][^>]*>.*?</script>\s*', '', html, flags=re.S|re.I)
    html = re.sub(r'\s*window\.PARLAYOS_GAMES\s*=\s*\[.*?\];\s*', '\n', html, flags=re.S)
    html = re.sub(r'\s*window\.PARLAYOS_LIVE_SCORES\s*=\s*\{.*?\};\s*', '\n', html, flags=re.S)
    html = re.sub(r'\s*window\.LIVE_SCORES_DATA\s*=\s*\{.*?\};\s*', '\n', html, flags=re.S)
    html = re.sub(r'\s*window\.PARLAYOS_SPORTS_CONFIG\s*=\s*\{.*?\};\s*', '\n', html, flags=re.S)

    loader = r'''<script id="CHD_DATA_INJECTION">
(function(){
  'use strict';
  const SRC={mlb:'./parlayos_mlb_chd.json',nfl:'./parlayos_nfl_chd.json',nba:'./parlayos_nba_chd.json',combined:'./parlayos_chd_data.json'};
  window.PARLAYOS_CHD_SOURCES=SRC;
  const bust=u=>u+(u.includes('?')?'&':'?')+'ts='+Date.now();
  async function get(u){const r=await fetch(bust(u),{cache:'no-store'});if(!r.ok)throw new Error(u+' HTTP '+r.status);return r.json();}
  const normalize=d=>Object.assign({games:[],schedules:{},teamStats:{},standings:{}},d||{});
  async function load(){
    const [mlb,nfl,nba,combined]=await Promise.all([get(SRC.mlb),get(SRC.nfl),get(SRC.nba),get(SRC.combined)]);
    window.CHD_DATA=combined;
    window.PARLAYOS_DATA=normalize(mlb);
    window.PARLAYOS_NFL_DATA=normalize(nfl);
    window.PARLAYOS_NBA_DATA=normalize(nba);
    window.PARLAYOS_GAMES=window.PARLAYOS_DATA.games||[];
    window.gamesNFL=window.PARLAYOS_NFL_DATA.games||[];
    window.gamesNBA=window.PARLAYOS_NBA_DATA.games||[];
    const detail={mlb:window.PARLAYOS_DATA,nfl:window.PARLAYOS_NFL_DATA,nba:window.PARLAYOS_NBA_DATA,combined:combined};
    try{window.dispatchEvent(new CustomEvent('chd:ready',{detail:combined}));}catch(_){}
    try{document.dispatchEvent(new CustomEvent('parlayos:chd-data-ready',{detail:detail}));}catch(_){}
    try{if(typeof window.loadRealData==='function')window.loadRealData();}catch(_){}
    try{if(typeof window.renderDashboard==='function')window.renderDashboard();}catch(_){}
    try{if(typeof window.chdWireSportHubs==='function')window.chdWireSportHubs();}catch(_){}
    return combined;
  }
  window.loadParlayOSCHDData=load;
  const boot=()=>load().catch(e=>console.error('[CHD] Runtime JSON load failed',e));
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
</script>'''
    if '</body>' in html:
        html=html.replace('</body>',loader+'\n</body>',1)
    else:
        html += '\n'+loader
    return html


def _reject_mock_dashboard_content(html):
    forbidden=["Sample Team A","Sample Team B","SAMPLE_LIVE_GAMES","Using sample","Using demo","SAMPLE DATA","DEMO DATA"]
    found=[token for token in forbidden if token in html]
    if found: raise RuntimeError("Dashboard contains mock/demo data markers: "+", ".join(found))


def main():
    has_key=bool(os.getenv("ODDS_API_KEY"))
    print(f"ODDS_API_KEY env set: {has_key}")
    print("Backend - Real CHD JSON only")
    payloads=_validate_chd_payloads()

    parlayos_html=os.path.join(BASE_DIR,"parlayos.html")
    index_html=os.path.join(BASE_DIR,"index.html")
    if not os.path.exists(parlayos_html) and os.path.exists(index_html): shutil.copyfile(index_html,parlayos_html)
    if not os.path.exists(parlayos_html) or not os.path.getsize(parlayos_html):
        raise RuntimeError("No non-empty dashboard HTML source is available")

    engines=[("MLB (mlb_ace.py)","mlb_ace.py",parlayos_html),("NBA (nba_ace.py)","nba_ace.py",parlayos_html),("NFL (nfl_ace.py)","nfl_ace.py",parlayos_html)]
    existing_engines=[e for e in engines if os.path.exists(os.path.join(BASE_DIR,e[1]))]
    for name,mod_path,_ in engines:
        if not os.path.exists(os.path.join(BASE_DIR,mod_path)): print(f"Skipping {name}: {mod_path} not found")

    results=[]; start=time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_engine={executor.submit(_run_one,name,mod_path,html_p):(name,mod_path) for name,mod_path,html_p in existing_engines}
        for future in as_completed(future_to_engine):
            name,mod_path=future_to_engine[future]
            try: results.append(future.result())
            except Exception as e:
                print(f"X {name}: Executor failed - {e}"); traceback.print_exc(); results.append((False,name,0,0))
    for ok,name,total,qual in results: print(f"  {'OK' if ok else 'X'} {name}: {total} games, {qual} qualify")

    content=open(parlayos_html,'r',encoding='utf-8',errors='ignore').read()
    _reject_mock_dashboard_content(content)
    content=_install_runtime_chd_loader(content)
    required=['parlayos_mlb_chd.json','parlayos_nfl_chd.json','parlayos_nba_chd.json','parlayos_chd_data.json','loadParlayOSCHDData','CHD_DATA_INJECTION']
    missing=[token for token in required if token not in content]
    if missing: raise RuntimeError('HTML CHD validation failed: '+', '.join(missing))
    forbidden=[(r"window\.PARLAYOS_DATA\s*=\s*\{\s*[\"']runDate[\"']",'inline MLB CHD snapshot'),(r"window\.PARLAYOS_NFL_DATA\s*=\s*\{\s*[\"']runDate[\"']",'inline NFL CHD snapshot'),(r"window\.PARLAYOS_NBA_DATA\s*=\s*\{\s*[\"']runDate[\"']",'inline NBA CHD snapshot'),(r"window\.PARLAYOS_LIVE_SCORES\s*=\s*\{",'embedded live-score snapshot'),(r"window\.PARLAYOS_SPORTS_CONFIG\s*=\s*\{",'embedded sports configuration')]
    for pattern,label in forbidden:
        if re.search(pattern,content,flags=re.S): raise RuntimeError(f'HTML still contains {label}')
    if '16b0a233c6bbe7492dc168a1a46ec469' in content: raise RuntimeError('Browser artifact contains an exposed ODDS_API_KEY')

    with open(parlayos_html,'w',encoding='utf-8') as f: f.write(content)
    shutil.copyfile(parlayos_html,index_html)
    if not os.path.getsize(index_html): raise RuntimeError('index.html is empty after publish')
    if open(parlayos_html,'r',encoding='utf-8').read()!=open(index_html,'r',encoding='utf-8').read(): raise RuntimeError('parlayos.html and index.html diverged')
    print(f"CHD DATA ONLY: MLB/NFL/NBA + combined JSON wired into both dashboards ({len(content)} bytes)")

if __name__=="__main__": main()
