"""Checks that the live bot computes exactly the features the model was trained on.

Converts real games from a season parquet file into NHL-API-shaped JSON, runs them through
metrics.analyze_game, and compares every feature of every shot with tools/fit_xg.py.

  python tools/check_parity.py play_by_play_2026.parquet [--games 50]
"""
import argparse
import sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import fit_xg as F, xg_model, metrics
ap = argparse.ArgumentParser(); ap.add_argument("parquet"); ap.add_argument("--games", type=int, default=50)
args = ap.parse_args(); P = args.parquet
cols=list(dict.fromkeys(F.COLS+["event_player_1_id","home_skaters","away_skaters"]))
df=pd.read_parquet(P,columns=cols)
all_games=sorted(df.game_id.unique()); games=all_games[::max(1, len(all_games)//args.games)][:args.games]; df=df[df.game_id.isin(games)]
KIND={"GOAL":"goal","SHOT":"shot-on-goal","MISSED_SHOT":"missed-shot","BLOCKED_SHOT":"blocked-shot","FACEOFF":"faceoff","HIT":"hit","GIVEAWAY":"giveaway","TAKEAWAY":"takeaway"}
HOME,AWAY=1,2
def train_feats(g):
    f=tempfile.NamedTemporaryFile(suffix=".parquet",delete=False); g.to_parquet(f.name)
    s=F.load_shots(f.name); return s, F.design(s)
def to_api(g):
    g=g[(g.period_type!="SHOOTOUT")&(g.event_type!="CHANGE")].sort_values(["period","period_seconds","event_idx"])
    plays=[]; roster={}
    for i,r in enumerate(g.itertuples()):
        owner=HOME if r.event_team_type=="home" else AWAY if r.event_team_type=="away" else None
        d={"eventOwnerTeamId":owner}
        if pd.notna(r.x): d.update(xCoord=float(r.x), yCoord=float(r.y))
        if r.event_type in F.ATTEMPTS and pd.notna(r.event_player_1_id):
            pid=int(r.event_player_1_id)
            roster[pid]=(AWAY if owner==HOME else HOME) if r.event_type=="BLOCKED_SHOT" else owner
            d["scoringPlayerId" if r.event_type=="GOAL" else "shootingPlayerId"]=pid
            if isinstance(r.secondary_type,str): d["shotType"]=r.secondary_type
        side=None
        if pd.notna(r.x) and pd.notna(r.x_fixed) and r.x!=0: side="left" if np.sign(r.x)==np.sign(r.x_fixed) else "right"
        en=bool(r.empty_net) if pd.notna(r.empty_net) else False
        hs=int(r.home_skaters) if pd.notna(r.home_skaters) else 5; as_=int(r.away_skaters) if pd.notna(r.away_skaters) else 5
        sit=f"{'0' if en and r.event_team_type=='home' else '1'}{as_}{hs}{'0' if en and r.event_team_type=='away' else '1'}"
        sec=int(r.period_seconds)
        plays.append({"sortOrder":i,"typeDescKey":KIND.get(r.event_type,r.event_type.lower()),"details":d,
            "periodDescriptor":{"number":int(r.period),"periodType":"REG"},"timeInPeriod":f"{sec//60:02d}:{sec%60:02d}",
            "situationCode":sit,"homeTeamDefendingSide":side})
    return {"pbp":{"homeTeam":{"id":HOME},"awayTeam":{"id":AWAY},"rosterSpots":[{"playerId":k,"teamId":v} for k,v in roster.items()],"plays":plays},
            "boxscore":{"homeTeam":{"id":HOME,"abbrev":"H"},"awayTeam":{"id":AWAY,"abbrev":"A"},"playerByGameStats":{}},"shifts":[],"score":{"id":0}}
orig=xg_model.features; mism={}; shown=0; n_live=n_train=0; tot=[]
for gid in games:
    g=df[df.game_id==gid]; s,T=train_feats(g)
    rec=[]; metrics.xg_model.features=lambda *a,**k: (rec.append(orig(*a,**k)), rec[-1])[1]
    a=metrics.analyze_game(to_api(g)); metrics.xg_model.features=orig
    L=pd.DataFrame(rec,columns=xg_model.FEATURE_NAMES); n_live+=len(L); n_train+=len(T)
    if len(L)!=len(T): print(gid,"count",len(L),len(T)); continue
    bad=(L.values-T.values)!=0; bad=np.abs(L.values-T.values)>1e-6
    for j,c in enumerate(xg_model.FEATURE_NAMES): mism[c]=mism.get(c,0)+int(bad[:,j].sum())
    if bad.any() and shown<4:
        i=bad.any(axis=1).nonzero()[0][0]; cs=[c for j,c in enumerate(xg_model.FEATURE_NAMES) if bad[i,j]]
        print(gid,"live",L.iloc[i][cs].round(3).to_dict(),"train",T.iloc[i][cs].round(3).to_dict(), s.iloc[i][["period","period_seconds","event_type","prev_type","dt","strength_state"]].to_dict()); shown+=1
bad_feats = {k: v for k, v in mism.items() if v}
print(f"{len(games)} games, {n_live} live shots vs {n_train} training shots; mismatched features: {bad_feats or 'none'}")
sys.exit(1 if bad_feats or n_live != n_train else 0)
