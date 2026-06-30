#!/usr/bin/env python3
"""
update_data.py — refresh data/tournament.json from worldcup26.ir (FREE, NO API KEY).

This pulls live FIFA World Cup 2026 data from the open, key-less worldcup26.ir API
and rewrites the values the site reads:
  - group standings  (computed from finished group matches -> real W/D/L/GF/GA/GD/Pts)
  - knockout bracket (rebuilt straight from the API every run: real matchups, scores,
                      status, venues, UTC kickoffs, and the bracket wiring itself)

The knockout section is rebuilt from scratch rather than patched, because the API is the
source of truth for the whole bracket. Each knockout match carries:
  - home_team_label / away_team_label  -> "Winner Group E", "Runner-up Group A",
    "3rd Group A/B/C/D/F", "Winner Match 74", "Loser Match 101" — i.e. the bracket wiring.
We DFS that wiring from the final down so slots come out in clean top-to-bottom bracket
order, which keeps index.html's layout tidy (sibling matches stay adjacent, no crossing
connectors). No secret/token is required, so the GitHub Action runs with nothing to set up.

Endpoints used (see https://github.com/rezarahiminia/worldcup2026):
  GET https://worldcup26.ir/get/teams     -> id, fifa_code, ...
  GET https://worldcup26.ir/get/games     -> 104 matches (group + knockout, with labels)
  GET https://worldcup26.ir/get/stadiums  -> id, city, region (for venue + timezone)
"""
import os, re, json, sys, datetime, urllib.request

BASE = os.environ.get("WC_API_BASE", "https://worldcup26.ir")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "tournament.json")

# API knockout "type" -> (our round key in tournament.json, slot-id prefix, is-single-match)
KO_ROUNDS = [("r32", "R32", "r32", False), ("r16", "R16", "r16", False),
             ("qf", "QF", "qf", False),   ("sf", "SF", "sf", False),
             ("final", "F", "final", True), ("third", "TP", "third", True)]

# stadium id -> IANA timezone, to convert the API's venue-local kickoff to a real UTC instant
# (zoneinfo handles 2026 DST correctly; Mexican venues stay on standard time year-round).
STADIUM_TZ = {
    "1": "America/Mexico_City", "2": "America/Mexico_City", "3": "America/Monterrey",
    "4": "America/Chicago", "5": "America/Chicago", "6": "America/Chicago",
    "7": "America/New_York", "8": "America/New_York", "9": "America/New_York",
    "10": "America/New_York", "11": "America/New_York", "12": "America/Toronto",
    "13": "America/Vancouver", "14": "America/Los_Angeles", "15": "America/Los_Angeles",
    "16": "America/Los_Angeles",
}
# fallback fixed summer (DST) offsets by the API's region, used only if zoneinfo is unavailable
REGION_OFFSET = {"Eastern": -4, "Central": -5, "Western": -7}


def api(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "wc2026-tracker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def listify(d):
    """The endpoints may return a bare list or wrap it; normalise to a list."""
    if isinstance(d, list):
        return d
    for k in ("data", "games", "teams", "stadiums", "result", "results"):
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


def build_stadiums(stadiums):
    """id -> {venue, region}. Prefer the specific locality in parens, e.g.
    'Boston (Foxborough)' -> 'Foxborough', matching the site's short venue names."""
    out = {}
    for s in stadiums:
        sid = str(s.get("id"))
        city = (s.get("city_en") or "").strip()
        m = re.search(r"\(([^)]+)\)", city)
        if m:
            venue = m.group(1).split(",")[0].strip()
        else:
            venue = city.split("(")[0].strip() or (s.get("fifa_name") or "").strip()
        out[sid] = {"venue": venue, "region": (s.get("region") or "").strip()}
    return out


def parse_kickoff_utc(local_date, stadium_id, region):
    """'MM/DD/YYYY HH:MM' in the venue's local time -> 'YYYY-MM-DDTHH:MM:SSZ' UTC."""
    try:
        dt = datetime.datetime.strptime(str(local_date).strip(), "%m/%d/%Y %H:%M")
    except (ValueError, AttributeError):
        return None
    tzname = STADIUM_TZ.get(str(stadium_id))
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            aware = dt.replace(tzinfo=ZoneInfo(tzname))
            return aware.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    off = REGION_OFFSET.get(region)
    if off is None:
        return None
    return (dt - datetime.timedelta(hours=off)).strftime("%Y-%m-%dT%H:%M:%SZ")


def placeholder_from_label(label, id2slot):
    """Turn an API bracket label into a compact placeholder matching the site's style:
       'Winner Group E' -> '1E', 'Runner-up Group B' -> '2B',
       '3rd Group A/B/C/D/F' -> '3rd A/B/C/D/F',
       'Winner Match 74' -> 'W r32-2', 'Loser Match 101' -> 'L sf-1'."""
    s = (label or "").strip()
    for pat, fmt in (
        (r"Winner Group (.+)", lambda g: "1" + g.strip()),
        (r"Runner-?up Group (.+)", lambda g: "2" + g.strip()),
        (r"3rd Group (.+)", lambda g: "3rd " + g.strip()),
        (r"Winner Match (\d+)", lambda g: "W " + id2slot.get(g, "?")),
        (r"Loser Match (\d+)", lambda g: "L " + id2slot.get(g, "?")),
    ):
        m = re.fullmatch(pat, s)
        if m:
            return fmt(m.group(1))
    return s or "TBD"


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


def _winner_feeders(games):
    """api match id -> {'home': feeder_id, 'away': feeder_id} from 'Winner Match N' labels."""
    feeders = {}
    for m in games:
        if m.get("type") not in ("r32", "r16", "qf", "sf", "final", "third"):
            continue
        mid = str(m.get("id"))
        for side in ("home", "away"):
            wm = re.fullmatch(r"Winner Match (\d+)", (m.get(side + "_team_label") or "").strip())
            if wm:
                feeders.setdefault(mid, {})[side] = wm.group(1)
    return feeders


def _bracket_order(games, feeders):
    """DFS the winners' bracket from the final so each round's matches come out in
    top-to-bottom order with siblings adjacent. Returns {api_id: order_index}, or {}
    if the wiring can't be resolved (caller falls back to numeric id order)."""
    finals = [m for m in games if m.get("type") == "final"]
    if not finals:
        return {}
    order, seen = [], set()

    def dfs(mid):
        if mid is None or mid in seen:
            return
        seen.add(mid)
        order.append(mid)
        kids = feeders.get(mid)
        if kids:
            dfs(kids.get("home"))
            dfs(kids.get("away"))

    dfs(str(finals[0].get("id")))
    return {mid: i for i, mid in enumerate(order)}


def group_positions(groups):
    """From the computed standings, return per-position lookups for COMPLETE groups only.
       winners{X:code}, runners{X:code}, thirds[(code, group, pts, gd, gf)]."""
    winners, runners, thirds = {}, {}, []
    for L, rows in groups.items():
        if not rows or not all(r.get("p", 0) >= 3 for r in rows):
            continue  # group not finished yet -> don't resolve from it
        if len(rows) >= 1: winners[L] = rows[0]["team"]
        if len(rows) >= 2: runners[L] = rows[1]["team"]
        if len(rows) >= 3:
            r = rows[2]
            thirds.append((r["team"], L, r["pts"], r["gd"], r["gf"]))
    return winners, runners, thirds


def assign_best_thirds(third_slots, thirds):
    """Resolve the best-third-place slots. third_slots: list of (label, allowed_groups_set)
    taken from the API labels (e.g. '3rd Group A/B/C/D/F'). Returns {label: team_code}.
    Ranks the third-placed teams, takes the top N, then finds a perfect matching of slots
    to qualifying groups respecting each slot's allowed set (this is exactly FIFA's
    best-thirds assignment, with the constraints supplied by the labels)."""
    n = len(third_slots)
    if n == 0 or len(thirds) < n:
        return {}   # not every group is complete yet -> can't assign reliably
    ranked = sorted(thirds, key=lambda t: (-t[2], -t[3], -t[4]))[:n]
    group_of_code = {g: code for code, g, *_ in ranked}
    qualified = set(group_of_code)
    slots = sorted(third_slots, key=lambda s: len(s[1] & qualified))  # fewest options first
    assigned, used = {}, set()

    def backtrack(i):
        if i == len(slots):
            return True
        label, allowed = slots[i]
        for g in sorted(allowed & qualified):
            if g in used:
                continue
            used.add(g); assigned[label] = g
            if backtrack(i + 1):
                return True
            used.discard(g); del assigned[label]
        return False

    if not backtrack(0):
        return {}
    return {label: group_of_code[g] for label, g in assigned.items()}


def resolve_group_label(label, winners, runners, thirds_assignment):
    """A 'Winner/Runner-up/3rd Group ...' label -> real team code, or None if unresolved."""
    s = (label or "").strip()
    m = re.fullmatch(r"Winner Group (.+)", s)
    if m:
        return winners.get(m.group(1).strip())
    m = re.fullmatch(r"Runner-?up Group (.+)", s)
    if m:
        return runners.get(m.group(1).strip())
    if s.startswith("3rd Group "):
        return thirds_assignment.get(s)
    return None


def rebuild_knockout(data, games, id2code, stadiums):
    """Replace data['knockout'] entirely with the API's bracket (matchups, scores,
    status, venue, UTC, wiring). Teams come from the API when it has filled them, and
    are otherwise resolved from our own computed standings + bracket labels, so the
    bracket fills in as soon as the groups finish even while the API lags behind."""
    by_type = {}
    for m in games:
        by_type.setdefault(m.get("type"), []).append(m)

    feeders = _winner_feeders(games)
    order = _bracket_order(games, feeders)

    # resolve teams from our standings where the API hasn't filled them in yet
    winners, runners, thirds = group_positions(data["groups"])
    third_slots = []
    for m in games:
        if m.get("type") != "r32":
            continue
        for side in ("home", "away"):
            lab = (m.get(side + "_team_label") or "").strip()
            if lab.startswith("3rd Group "):
                allowed = set(re.split(r"/", lab[len("3rd Group "):].strip()))
                third_slots.append((lab, allowed))
    thirds_assignment = assign_best_thirds(third_slots, thirds)

    def sort_key(m):
        mid = str(m.get("id"))
        return (order.get(mid, 10 ** 6), to_int(mid) or 0)

    # assign a stable slot id to every knockout match, in bracket order
    id2slot = {}
    round_slots = {}
    for api_type, round_key, prefix, single in KO_ROUNDS:
        ms = sorted(by_type.get(api_type, []), key=sort_key)
        slots = []
        for i, m in enumerate(ms, 1):
            slot_id = prefix if single else f"{prefix}-{i}"
            id2slot[str(m.get("id"))] = slot_id
            slots.append((slot_id, m))
        round_slots[round_key] = slots

    # who-feeds-where, as our slot ids. Follow WINNER references only: the bracket
    # connector tracks the winners' path (a semifinal feeds the final, not third place;
    # the third-place game is drawn separately and its losers show as 'L sf-1' placeholders).
    feeds_to = {}   # feeder api id -> (target slot id, 'home'|'away')
    for m in games:
        tgt = id2slot.get(str(m.get("id")))
        if not tgt:
            continue
        for side in ("home", "away"):
            ref = re.fullmatch(r"Winner Match (\d+)", (m.get(side + "_team_label") or "").strip())
            if ref:
                feeds_to[ref.group(1)] = (tgt, side)

    new_ko = {}
    scored = 0
    for api_type, round_key, prefix, single in KO_ROUNDS:
        rows = []
        for slot_id, m in round_slots[round_key]:
            hlab, alab = m.get("home_team_label"), m.get("away_team_label")
            # Use the API's ACTUAL assigned team FIRST — it is the real fixture (who truly
            # plays this match). Only when the API hasn't filled a slot yet do we resolve it
            # predictively from our own standings + bracket labels (so the bracket fills in
            # as soon as the groups finish, even while the API lags), then a placeholder.
            home = (side_code(m, "home", id2code)
                    or resolve_group_label(hlab, winners, runners, thirds_assignment)
                    or placeholder_from_label(hlab, id2slot))
            away = (side_code(m, "away", id2code)
                    or resolve_group_label(alab, winners, runners, thirds_assignment)
                    or placeholder_from_label(alab, id2slot))
            st = status_of(m)
            hs, as_ = to_int(m.get("home_score")), to_int(m.get("away_score"))
            if st in ("FT", "LIVE") and hs is not None and as_ is not None:
                home_score, away_score = hs, as_
                scored += 1
            else:
                home_score = away_score = None
            sid = str(m.get("stadium_id"))
            sinfo = stadiums.get(sid, {})
            fd = feeds_to.get(str(m.get("id")))
            rows.append({
                "id": slot_id,
                "utc": parse_kickoff_utc(m.get("local_date"), sid, sinfo.get("region")),
                "home": home, "away": away,
                "homeScore": home_score, "awayScore": away_score,
                "venue": sinfo.get("venue", ""),
                "status": st,
                "feeds": fd[0] if fd else None,
                "slot": fd[1] if fd else None,
            })
        new_ko[round_key] = rows

    # propagate winners/losers through the bracket as matches finish, in case the API
    # is slow to fill later rounds' teams (mirrors how it lags on the R32 best-thirds).
    teamcodes = set(data["teams"])
    results = {}   # slot id -> {'W': code, 'L': code}
    for _, round_key, _, _ in KO_ROUNDS:
        for s in new_ko[round_key]:
            for side in ("home", "away"):
                ref = re.fullmatch(r"([WL]) (\S+)", str(s[side]))
                if ref and ref.group(2) in results:
                    code = results[ref.group(2)].get(ref.group(1))
                    if code:
                        s[side] = code
            if (s["status"] == "FT" and s["homeScore"] is not None and s["awayScore"] is not None
                    and s["home"] in teamcodes and s["away"] in teamcodes):
                if s["homeScore"] > s["awayScore"]:
                    results[s["id"]] = {"W": s["home"], "L": s["away"]}
                elif s["awayScore"] > s["homeScore"]:
                    results[s["id"]] = {"W": s["away"], "L": s["home"]}

    data["knockout"] = new_ko
    resolved = sum(1 for rk in new_ko for s in new_ko[rk]
                   if s["home"] in teamcodes) + sum(1 for rk in new_ko for s in new_ko[rk]
                   if s["away"] in teamcodes)
    print(f"knockout rebuilt; matches with scores: {scored}; team slots filled: {resolved}/64")


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
    try:
        stadiums = build_stadiums(listify(api("/get/stadiums")))
    except Exception as e:
        print("stadiums fetch failed, venues/times may be blank:", e)
        stadiums = {}

    data = load_local()
    id2code = build_id2code(teams)
    update_standings(data, games, id2code)
    rebuild_knockout(data, games, id2code, stadiums)

    data["meta"]["lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    data["meta"]["source"] = "worldcup26.ir (live, no key)"
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote", DATA_PATH)


if __name__ == "__main__":
    main()
