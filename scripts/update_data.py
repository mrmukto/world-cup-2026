#!/usr/bin/env python3
"""
update_data.py — refresh data/tournament.json from worldcup26.ir (FREE, NO API KEY).

This pulls live FIFA World Cup 2026 data from the open, key-less worldcup26.ir API
and rewrites the values the site reads:
  - group standings  (computed from finished group matches -> real W/D/L/GF/GA/GD/Pts)
  - knockout matches (team names + scores + status, with winners propagated through the
                      bracket as rounds finish)

The bracket *skeleton* in tournament.json (ids, venues, kickoff times, feed wiring) is
kept; only live values are patched. No secret/token is required, so the GitHub Action
runs with nothing to configure.

Endpoints used (see https://github.com/rezarahiminia/worldcup2026):
  GET https://worldcup26.ir/get/teams   -> id, fifa_code, ...
  GET https://worldcup26.ir/get/games   -> 104 matches (group + knockout)
"""
import os, json, sys, datetime, urllib.request

BASE = os.environ.get("WC_API_BASE", "https://worldcup26.ir")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "tournament.json")

# API "type" -> our knockout round key, processed in bracket order so winners propagate.
KO_ROUNDS = [("R32", "r32"), ("R16", "r16"), ("QF", "qf"), ("SF", "sf"),
             ("F", "final"), ("TP", "third")]


def api(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "wc2026-tracker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def listify(d):
    """The endpoints may return a bare list or wrap it; normalise to a list."""
    if isinstance(d, list):
        return d
    for k in ("data", "games", "teams", "result", "results"):
        if isinstance(d, dict) and isinstance(d.get(k), list):
            return d[k]
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                return v
    return []


def load_local():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def is_finished(m):
    return str(m.get("finished", "")).strip().upper() == "TRUE"


def status_of(m):
    if is_finished(m):
        return "FT"
    te = str(m.get("time_elapsed", "")).strip().lower()
    if te and te not in ("notstarted", "not started", "null", ""):
        return "LIVE"
    return "SCHEDULED"


def build_id2code(teams):
    out = {}
    for t in teams:
        code = (t.get("fifa_code") or "").strip()
        tid = t.get("id")
        if code and tid is not None:
            out[str(tid)] = code
    return out


def side_code(m, side, id2code):
    tid = m.get(side + "_team_id")
    if tid is not None and str(tid) in id2code:
        return id2code[str(tid)]
    return None


def update_standings(data, games, id2code):
    """Compute group tables from finished group matches (gives accurate GF/GA)."""
    tally = {L: {} for L in data["groups"]}
    for m in games:
        if m.get("type") != "group" or not is_finished(m):
            continue
        grp = (m.get("group") or "").strip()
        if grp not in tally:
            continue
        h, a = side_code(m, "home", id2code), side_code(m, "away", id2code)
        hs, as_ = to_int(m.get("home_score")), to_int(m.get("away_score"))
        if not (h and a) or hs is None or as_ is None:
            continue
        for c in (h, a):
            tally[grp].setdefault(c, {"team": c, "p": 0, "w": 0, "d": 0, "l": 0,
                                     "gf": 0, "ga": 0, "gd": 0, "pts": 0})
        th, ta = tally[grp][h], tally[grp][a]
        th["p"] += 1; ta["p"] += 1
        th["gf"] += hs; th["ga"] += as_; ta["gf"] += as_; ta["ga"] += hs
        if hs > as_:   th["w"] += 1; th["pts"] += 3; ta["l"] += 1
        elif hs < as_: ta["w"] += 1; ta["pts"] += 3; th["l"] += 1
        else:          th["d"] += 1; ta["d"] += 1; th["pts"] += 1; ta["pts"] += 1

    updated = 0
    for L, rowmap in tally.items():
        if not rowmap:        # no finished matches yet -> leave existing data untouched
            continue
        rows = []
        for r in rowmap.values():
            r["gd"] = r["gf"] - r["ga"]
            rows.append(r)
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"]))
        data["groups"][L] = rows
        updated += 1
    print("standings updated for groups:", updated)


def resolve_placeholder(val, teams, results):
    """Turn 'W r32-1' / 'L sf-1' into a real code once that match has a result."""
    if val in teams:
        return val
    parts = str(val).split(" ", 1)
    if len(parts) == 2 and parts[0] in ("W", "L"):
        return results.get((parts[0], parts[1]), val)
    return val


def update_knockout(data, games, id2code):
    teams = data["teams"]
    api_by_round = {}
    for m in games:
        t = m.get("type")
        api_by_round.setdefault(t, []).append(m)

    def find_api_match(api_type, known):
        for m in api_by_round.get(api_type, []):
            mt = {side_code(m, "home", id2code), side_code(m, "away", id2code)} - {None}
            if known and known <= mt:
                return m
        return None

    results = {}   # ('W'|'L', slot_id) -> winning/losing code
    patched = 0
    for round_key, api_type in KO_ROUNDS:
        for slot in data["knockout"].get(round_key, []):
            # 1) resolve feed placeholders from earlier rounds' results
            slot["home"] = resolve_placeholder(slot["home"], teams, results)
            slot["away"] = resolve_placeholder(slot["away"], teams, results)

            known = {c for c in (slot["home"], slot["away"]) if c in teams}
            am = find_api_match(api_type, known) if known else None
            if am:
                ah, aa = side_code(am, "home", id2code), side_code(am, "away", id2code)
                # fill an unknown opponent only when the API actually knows it
                if slot["home"] in teams and slot["away"] not in teams:
                    other = aa if ah == slot["home"] else ah
                    if other:
                        slot["away"] = other
                elif slot["away"] in teams and slot["home"] not in teams:
                    other = ah if aa == slot["away"] else aa
                    if other:
                        slot["home"] = other
                # scores: only when both sides are real and the game has a score
                hs, as_ = to_int(am.get("home_score")), to_int(am.get("away_score"))
                st = status_of(am)
                if slot["home"] in teams and slot["away"] in teams and hs is not None \
                        and st in ("FT", "LIVE"):
                    if slot["home"] == ah:
                        slot["homeScore"], slot["awayScore"] = hs, as_
                    else:
                        slot["homeScore"], slot["awayScore"] = as_, hs
                    slot["status"] = st
                    patched += 1

            # 2) record winner/loser so later rounds can resolve their placeholders
            if slot.get("status") in ("FT", "FINISHED") and slot.get("homeScore") is not None:
                hsv, asv = slot["homeScore"], slot["awayScore"]
                if hsv > asv:
                    results[("W", slot["id"])] = slot["home"]; results[("L", slot["id"])] = slot["away"]
                elif asv > hsv:
                    results[("W", slot["id"])] = slot["away"]; results[("L", slot["id"])] = slot["home"]
                # exact draws (penalty shootouts) can't be resolved from score alone
    print("knockout matches patched:", patched)


def main():
    try:
        teams = listify(api("/get/teams"))
        games = listify(api("/get/games"))
    except Exception as e:
        print("fetch failed, leaving data unchanged:", e)
        sys.exit(0)
    if not teams or not games:
        print("empty API response, leaving data unchanged.")
        sys.exit(0)

    data = load_local()
    id2code = build_id2code(teams)
    update_standings(data, games, id2code)
    update_knockout(data, games, id2code)

    data["meta"]["lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    data["meta"]["source"] = "worldcup26.ir (live, no key)"
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote", DATA_PATH)


if __name__ == "__main__":
    main()
