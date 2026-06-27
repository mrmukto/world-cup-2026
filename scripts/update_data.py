#!/usr/bin/env python3
"""
update_data.py — refresh data/tournament.json from a live football API.

This template targets football-data.org (free tier: World Cup included, 10 req/min).
Get a free key at https://www.football-data.org/client/register and set it as the
FOOTBALL_DATA_TOKEN environment variable (the GitHub Action injects it as a secret).

It keeps the knockout *structure* from the existing tournament.json (the bracket
wiring, venues, kickoff times) and only overwrites live values: group standings,
group-stage scores/status, and knockout match results as they fill in.

Swap MAP_TEAM / parsing to API-Football or worldcup26.ir if you prefer — only the
fetch + mapping functions need to change; the JSON schema stays the same.
"""
import os, json, sys, datetime, urllib.request

TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
BASE  = "https://api.football-data.org/v4"
COMP  = os.environ.get("WC_COMPETITION", "WC")   # football-data competition code for the World Cup
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "tournament.json")

# Map the API's team names -> your 3-letter codes used in tournament.json.
# football-data uses full names; adjust any that differ from your codes.
NAME_TO_CODE = {
    "Mexico":"MEX","South Africa":"RSA","South Korea":"KOR","Korea Republic":"KOR","Czechia":"CZE",
    "Canada":"CAN","Bosnia and Herzegovina":"BIH","Qatar":"QAT","Switzerland":"SUI",
    "Brazil":"BRA","Morocco":"MAR","Haiti":"HAI","Scotland":"SCO",
    "United States":"USA","USA":"USA","Paraguay":"PAR","Australia":"AUS","Türkiye":"TUR","Turkey":"TUR",
    "Germany":"GER","Curaçao":"CUW","Ivory Coast":"CIV","Côte d'Ivoire":"CIV","Ecuador":"ECU",
    "Netherlands":"NED","Japan":"JPN","Sweden":"SWE","Tunisia":"TUN",
    "Belgium":"BEL","Egypt":"EGY","Iran":"IRN","New Zealand":"NZL",
    "Spain":"ESP","Cape Verde":"CPV","Saudi Arabia":"KSA","Uruguay":"URU",
    "France":"FRA","Senegal":"SEN","Iraq":"IRQ","Norway":"NOR",
    "Argentina":"ARG","Algeria":"ALG","Austria":"AUT","Jordan":"JOR",
    "Portugal":"POR","DR Congo":"COD","Congo DR":"COD","Uzbekistan":"UZB","Colombia":"COL",
    "England":"ENG","Croatia":"CRO","Ghana":"GHA","Panama":"PAN",
}

def code(name):
    return NAME_TO_CODE.get((name or "").strip())

def api(path):
    req = urllib.request.Request(BASE + path, headers={"X-Auth-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def load_local():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)

def update_standings(data):
    """Overwrite group tables from /competitions/{COMP}/standings."""
    try:
        res = api(f"/competitions/{COMP}/standings")
    except Exception as e:
        print("standings fetch failed:", e); return
    for tbl in res.get("standings", []):
        grp = (tbl.get("group") or "").replace("GROUP_", "").strip()  # e.g. "GROUP_A" -> "A"
        if grp not in data["groups"]:
            continue
        new_rows = []
        for row in tbl.get("table", []):
            c = code(row["team"]["name"])
            if not c:
                print("  unmapped team:", row["team"]["name"]); continue
            new_rows.append({
                "team":c,"p":row["playedGames"],"w":row["won"],"d":row["draw"],
                "l":row["lost"],"gf":row["goalsFor"],"ga":row["goalsAgainst"],
                "gd":row["goalDifference"],"pts":row["points"],
            })
        if new_rows:
            data["groups"][grp] = new_rows
    print("standings updated")

def update_matches(data):
    """Patch scores/status onto group fixtures and knockout matches by team-pair match."""
    try:
        res = api(f"/competitions/{COMP}/matches")
    except Exception as e:
        print("matches fetch failed:", e); return
    live = {}
    for m in res.get("matches", []):
        h = code(m["homeTeam"]["name"]); a = code(m["awayTeam"]["name"])
        if not (h and a): continue
        sc = m.get("score", {}).get("fullTime", {})
        live[(h,a)] = {"status":m["status"],"home":sc.get("home"),"away":sc.get("away")}

    # group fixtures
    for f in data["groupFixtures"]:
        key=(f["home"],f["away"])
        if key in live:
            f["status"]=live[key]["status"]; f["homeScore"]=live[key]["home"]; f["awayScore"]=live[key]["away"]

    # knockout: only matches whose slots are real team codes (after the draw fills them).
    # Match order-insensitively: the API may list our home team as its away team.
    for rnd in data["knockout"].values():
        for m in rnd:
            h,a=m.get("home"),m.get("away")
            if (h,a) in live:
                r=live[(h,a)]; m["status"]=r["status"]; m["homeScore"]=r["home"]; m["awayScore"]=r["away"]
            elif (a,h) in live:           # API has the teams the other way round; flip the scores
                r=live[(a,h)]; m["status"]=r["status"]; m["homeScore"]=r["away"]; m["awayScore"]=r["home"]
    print("match results updated")

def main():
    if not TOKEN:
        print("No FOOTBALL_DATA_TOKEN set — skipping live fetch (data unchanged).")
        sys.exit(0)
    data = load_local()
    update_standings(data)
    update_matches(data)
    data["meta"]["lastUpdated"]=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    data["meta"]["source"]="football-data.org"
    with open(DATA_PATH,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=1)
    print("wrote", DATA_PATH)

if __name__=="__main__":
    main()
