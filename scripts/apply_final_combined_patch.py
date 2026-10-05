#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HELPER = """function getPublishedFinalCombined(game, market){
                                 const source = game?.ensemble?.markets?.[market] || game?.models?.final_combined?.markets?.[market];
                                 if(!source || source.status !== 'available') return null;
                                 const pA = Number(source.pA), pB = Number(source.pB), probability = Number(source.probability);
                                 if(![pA,pB,probability].every(v=>Number.isFinite(v)&&v>=0&&v<=1)) return null;
                                 if(Math.abs((pA+pB)-1)>1e-6 || Math.abs(Math.max(pA,pB)-probability)>1e-6) return null;
                                 return {
                                   pA, pB, probability,
                                   edge: Number.isFinite(Number(source.edge)) ? Number(source.edge) : null,
                                   confidence: Number.isFinite(Number(source.confidence)) ? Number(source.confidence) : Math.max(pA,pB),
                                   model: 'final_combined',
                                   model_version: source.model_version || source.ensemble_version || null,
                                   selection: source.selection || null,
                                   player_id: source.player_id == null ? null : String(source.player_id),
                                   player_name: source.player_name || null,
                                   line: source.line ?? null,
                                   odds: source.odds ?? null,
                                   agreement: source.agreement || null,
                                   inputs: source.inputs || null,
                                   methodology: source.methodology || null,
                                   calibration_status: source.calibration_status || 'unvalidated',
                                   serverBacked: true
                                 };
                               }

"""

ANCHOR = """                               function runFinalCombined(game, sport, market){
                                 const models = ['monte_carlo','zips','steamer','season_stats','my_chd','chd_master_predictor'];"""

REPLACEMENT = """                               function runFinalCombined(game, sport, market){
                                 const published = getPublishedFinalCombined(game, market);
                                 if(published) return published;
                                 const models = ['monte_carlo','zips','steamer','season_stats','my_chd','chd_master_predictor'];"""

def patch_html(source: str) -> tuple[str, bool]:
    if "function getPublishedFinalCombined(game, market)" in source and "const published = getPublishedFinalCombined(game, market);" in source:
        return source, False
    if ANCHOR not in source:
        raise RuntimeError("Final Combined source anchor not found")
    return source.replace(ANCHOR, HELPER + REPLACEMENT, 1), True

def refresh_release_hashes(root: Path) -> None:
    release_path = root / "data/release_status.json"
    if not release_path.is_file():
        return
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    hashes = payload.get("sha256")
    if not isinstance(hashes, dict):
        return
    for name in list(hashes):
        path = root / name
        if path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    release_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

def apply(root: Path = Path(".")) -> int:
    changed = 0
    for name in ("index.html", "parlayos.html"):
        path = root / name
        source = path.read_text(encoding="utf-8")
        patched, did_change = patch_html(source)
        if did_change:
            path.write_text(patched, encoding="utf-8")
            changed += 1
    left = (root / "index.html").read_text(encoding="utf-8")
    right = (root / "parlayos.html").read_text(encoding="utf-8")
    if left != right:
        raise RuntimeError("index.html and parlayos.html diverged after prediction patch")
    refresh_release_hashes(root)
    return changed

if __name__ == "__main__":
    changed = apply()
    print(f"Final Combined published-ensemble patch: {changed} file(s) changed")
