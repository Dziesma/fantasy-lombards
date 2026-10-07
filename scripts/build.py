#!/usr/bin/env python3
"""Build the keeper-rights tables from the raw league data (Python 3 stdlib only).

Inputs (hand-edited):
  data/teams.csv          id (Yahoo team id), team, manager
  data/draft_2026.csv     pick, player, nba_team, pos, team, price (Yahoo draft results)
  data/transactions.csv   date, type, player, from_team, to_team, fab, note
  data/budget_trades.csv  date, from_team, to_team, amount, note
  data/weeks_<season>.csv     week, start, end (fantasy weeks, from Yahoo)
  data/matchups_<season>.csv  week, team1, team2 (Yahoo team ids)
  data/results_<season>.csv   week, team1, team2, cats1, cats2, ties (finished weeks, team ids)
  data/odds/<season>/         week-NN.json + outlook.json: team-level matchup odds and power ranking,
                              exported by the maintainer's h2hcats run (not hand-edited; no player values)

Outputs (generated, don't edit by hand):
  rights.csv              one row per player with keeper rights info
  KEEPERS.md              per-team and A-Z tables
  _site/                  website: index.html (keeper rights), odds.html (standings, matchup odds);
                          not committed, deployed by GitHub Actions

Usage:  python3 scripts/build.py           # rebuild
        python3 scripts/build.py --check   # fail if rights.csv/KEEPERS.md are stale (still builds _site/)
"""
import csv
import io
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "_site"

SEASON = "2026-27"
NEXT = ["2027-28", "2028-29", "2029-30"]
BUDGET = 200
BUDGET_CAP = 215
ROSTER_SPOTS = 13
TRANSACTION_TYPES = {"trade", "drop", "add"}


def escalate(price):
    """League rule: +max(15%, $5) per season, rounded up."""
    return math.ceil(max(price * 1.15, price + 5) - 1e-9)


def chain(base, years):
    out, p = [], base
    for _ in range(years):
        p = escalate(p)
        out.append(p)
    return out


def read(name):
    path = DATA / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def die(msg):
    sys.exit(f"error: {msg}")


def load():
    teams = read("teams.csv")
    team_names = {t["team"] for t in teams}

    players = {}
    for r in read("draft_2026.csv"):
        name = r["player"].strip()
        if name in players:
            die(f"{name} drafted twice")
        if r["team"] not in team_names:
            die(f"unknown team {r['team']!r} for {name} in draft_2026.csv")
        price = int(r["price"])
        players[name] = {
            "player": name,
            "nba_team": r.get("nba_team", ""),
            "pos": r["pos"],
            "pick": int(r["pick"]),
            "drafted_by": r["team"],
            "draft_price": price,
            "fab_max": None,
            "team": r["team"],
            "history": [],
        }

    for t in sorted(read("transactions.csv"), key=lambda r: r["date"]):
        kind = t["type"].strip().lower()
        name = t["player"].strip()
        if kind not in TRANSACTION_TYPES:
            die(f"bad transaction type {kind!r} ({name}, {t['date']})")
        for col in ("from_team", "to_team"):
            if t[col] and t[col] not in team_names:
                die(f"unknown team {t[col]!r} in transactions.csv ({name}, {t['date']})")
        p = players.get(name)
        if p is None:
            if kind != "add":
                die(f"{name} is not drafted or added yet but has a {kind} on {t['date']}")
            p = players[name] = {
                "player": name, "nba_team": "", "pos": "", "pick": None, "drafted_by": None,
                "draft_price": None, "fab_max": None, "team": None, "history": [],
            }
        if kind in ("trade", "drop") and p["team"] != t["from_team"]:
            die(f"{name} {kind} on {t['date']}: from_team is {t['from_team']!r} "
                f"but rights are with {p['team']!r}")
        if kind == "add" and p["team"]:
            die(f"{name} added on {t['date']} but still owned by {p['team']!r} (log the drop first)")
        if kind == "drop":
            p["team"] = None
        else:
            p["team"] = t["to_team"]
        if kind == "add":
            fab = int(t["fab"] or 0)
            p["fab_max"] = fab if p["fab_max"] is None else max(p["fab_max"], fab)
        p["history"].append(f"{t['date']} {kind}")

    budgets = {t["team"]: BUDGET for t in teams}
    for b in read("budget_trades.csv"):
        amt = int(b["amount"])
        for col in ("from_team", "to_team"):
            if b[col] not in team_names:
                die(f"unknown team {b[col]!r} in budget_trades.csv")
        budgets[b["from_team"]] -= amt
        budgets[b["to_team"]] += amt
    for team, total in budgets.items():
        if total > BUDGET_CAP:
            die(f"{team} has ${total} next-season budget, over the ${BUDGET_CAP} cap")

    spent = {}
    for p in players.values():
        if p["drafted_by"]:
            spent[p["drafted_by"]] = spent.get(p["drafted_by"], 0) + p["draft_price"]
    for team, total in sorted(spent.items()):
        if total > BUDGET:
            print(f"warning: {team} drafted ${total}, over the ${BUDGET} budget "
                  "(check data/draft_2026.csv against Yahoo)", file=sys.stderr)

    rows = []
    for p in players.values():
        # Keeper base = max(draft price this season, FAB paid). Undrafted $0 pickups
        # get base $0 (-> $5 keeper); that case is still to be confirmed by the league.
        base = max(x for x in (p["draft_price"], p["fab_max"], 0) if x is not None)
        k = chain(base, len(NEXT))
        rows.append({
            "player": p["player"],
            "nba_team": p["nba_team"],
            "pos": p["pos"],
            "rights": p["team"] or "",
            "pick": p["pick"] or "",
            "drafted_by": p["drafted_by"] or "",
            "draft_price": "" if p["draft_price"] is None else p["draft_price"],
            "fab_paid": "" if p["fab_max"] is None else p["fab_max"],
            "keeper_base": base,
            **{f"keeper_{s}": v for s, v in zip(NEXT, k)},
            "moves": "; ".join(p["history"]),
        })
    rows.sort(key=lambda r: (-r["keeper_base"], r["player"]))
    return teams, rows, budgets


def write_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["player"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def money(v):
    return "" if v == "" else f"${v}"


def md_table(rows, show_team):
    k1, k2, k3 = (f"keeper_{s}" for s in NEXT)
    head = ["Player", "NBA", "Pos"] + (["Rights"] if show_team else []) + \
        [f"Paid {SEASON}", f"Keeper {NEXT[0]}", NEXT[1], NEXT[2], "Notes"]
    lines = ["| " + " | ".join(head) + " |",
             "|" + "|".join("---:" if h.startswith(("Paid", "Keeper", "20")) else "---" for h in head) + "|"]
    for r in rows:
        notes = []
        if r["fab_paid"] != "":
            notes.append(f"FAB ${r['fab_paid']}")
        if r["drafted_by"] and r["drafted_by"] != r["rights"]:
            notes.append(f"drafted by {r['drafted_by']}")
        if r["moves"]:
            notes.append(r["moves"])
        paid = money(r["draft_price"]) if r["draft_price"] != "" else "undrafted"
        cells = [r["player"], r["nba_team"], r["pos"]] + ([r["rights"] or "*free agent*"] if show_team else []) + \
            [paid, f"**${r[k1]}**", f"${r[k2]}", f"${r[k3]}", ", ".join(notes)]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines)


def build_md(teams, rows, budgets, n_drafted):
    total_slots = len(teams) * ROSTER_SPOTS
    by_team = {t["team"]: [] for t in teams}
    free = []
    for r in rows:
        (by_team[r["rights"]] if r["rights"] else free).append(r)

    out = [
        "# Fantasy Lombards: keeper rights 2026-27",
        "",
        "<!-- Generated by scripts/build.py from data/*.csv. Do not edit by hand. -->",
        "",
        f"Keeper price = `ceil(max(base × 1.15, base + 5))` per season. Base = max(draft price, FAB paid).",
        f"Draft picks recorded: **{n_drafted} / {total_slots}**"
        + (" (draft log is still incomplete)." if n_drafted < total_slots else "."),
        "",
        "## Teams",
        "",
        f"| Team | Manager | Players with rights | Drafted $ | {NEXT[0]} budget (before keepers) |",
        "|---|---|---:|---:|---:|",
    ]
    for t in sorted(teams, key=lambda t: t["team"].lower()):
        tr = by_team[t["team"]]
        spent = sum(r["draft_price"] for r in rows if r["drafted_by"] == t["team"])
        anchor = slug(t["team"])
        out.append(f"| [{t['team']}](#{anchor}) | {t['manager']} | {len(tr)} | ${spent} | ${budgets[t['team']]} |")
    out.append("")

    for t in sorted(teams, key=lambda t: t["team"].lower()):
        tr = by_team[t["team"]]
        cost = sum(r[f"keeper_{NEXT[0]}"] for r in tr)
        out += [f"## {t['team']}", "", f"Manager: {t['manager']} · {len(tr)} players · "
                f"total {NEXT[0]} keeper cost if all kept: ${cost} (budget ${budgets[t['team']]})", ""]
        out += [md_table(tr, show_team=False) if tr else "_No players recorded yet._", ""]

    if free:
        out += ["## Free agents with a keeper base", "",
                "Drafted players who were dropped. Whoever picks them up inherits at least this base.", "",
                md_table(free, show_team=False), ""]

    out += ["## All players A–Z", "", md_table(sorted(rows, key=lambda r: r["player"]), show_team=True), ""]
    return "\n".join(out)


def slug(s):
    # GitHub heading anchors: lowercase, drop punctuation, spaces -> '-'
    keep = []
    for ch in s.lower():
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch == " ":
            keep.append("-")
    return "".join(keep)


def build_html(teams, rows, budgets, n_drafted):
    tpl = (ROOT / "scripts" / "page_template.html").read_text(encoding="utf-8")
    payload = {
        "season": SEASON,
        "next": NEXT,
        "slots": len(teams) * ROSTER_SPOTS,
        "drafted": n_drafted,
        "teams": [{"team": t["team"], "manager": t["manager"], "budget": budgets[t["team"]]} for t in teams],
        "rows": rows,
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__DATA__*/null", data)


def load_season(teams):
    """Schedule, results and exported odds for SEASON, validated against each other."""
    ids = {int(t["id"]): t["team"] for t in teams}
    weeks = [{"week": int(w["week"]), "start": w["start"], "end": w["end"]} for w in read(f"weeks_{SEASON}.csv")]
    for a, b in zip(weeks, weeks[1:]):
        if b["week"] != a["week"] + 1 or b["start"] <= a["end"]:
            die(f"weeks_{SEASON}.csv: week {b['week']} doesn't follow week {a['week']}")
    known = {w["week"] for w in weeks}

    matchups, per_week = [], {}
    for m in read(f"matchups_{SEASON}.csv"):
        w, a, b = int(m["week"]), int(m["team1"]), int(m["team2"])
        if w not in known or a not in ids or b not in ids:
            die(f"matchups_{SEASON}.csv: bad row week {w}: {a} vs {b}")
        if a >= b:   # one canonical order (Yahoo lists the viewer's own game first; don't copy that)
            die(f"matchups_{SEASON}.csv: week {w}: write the lower team id first ({b},{a})")
        per_week.setdefault(w, []).extend([a, b])
        matchups.append({"week": w, "team1": a, "team2": b})
    for w, played in per_week.items():
        if sorted(played) != sorted(ids):
            die(f"matchups_{SEASON}.csv: week {w} doesn't have every team exactly once")
    if matchups != sorted(matchups, key=lambda m: (m["week"], m["team1"])):
        die(f"matchups_{SEASON}.csv: sort rows by week, then team1")
    pairs = {(m["week"], frozenset((m["team1"], m["team2"]))) for m in matchups}

    results = []
    for r in read(f"results_{SEASON}.csv"):
        w, a, b = int(r["week"]), int(r["team1"]), int(r["team2"])
        c1, c2, ties = int(r["cats1"]), int(r["cats2"]), int(r["ties"])
        if a >= b:
            die(f"results_{SEASON}.csv: week {w}: write the lower team id first ({b},{a},{c2},{c1},{ties})")
        if (w, frozenset((a, b))) not in pairs:
            die(f"results_{SEASON}.csv: week {w} {a} vs {b} is not in the schedule")
        if c1 + c2 + ties != 9:
            die(f"results_{SEASON}.csv: week {w} {a} vs {b}: categories don't add up to 9")
        results.append({"week": w, "team1": a, "team2": b, "cats1": c1, "cats2": c2, "ties": ties})

    odds = {}
    folder = DATA / "odds" / SEASON
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        o = json.loads(path.read_text(encoding="utf-8"))   # teams are ids, so renames can't break old weeks
        bad = {r["team"] for r in o["power"]} - set(ids)
        if bad:
            die(f"{path.relative_to(ROOT)}: unknown team ids {sorted(bad)}")
        if o["week"] is not None:
            for m in o["matchups"]:
                if (o["week"], frozenset((m["team1"], m["team2"]))) not in pairs:
                    die(f"{path.relative_to(ROOT)}: {m['team1']} vs {m['team2']} is not in the schedule")
        odds["outlook" if o["week"] is None else str(o["week"])] = o
    return {"weeks": weeks, "matchups": matchups, "results": results, "odds": odds}


def standings(teams, results):
    """One-Win standings: W-L-T from each finished week, best first."""
    st = {int(t["id"]): {"id": int(t["id"]), "w": 0, "l": 0, "t": 0, "cats": 0} for t in teams}
    for r in results:
        for me, other, mine, theirs in ((r["team1"], r["team2"], r["cats1"], r["cats2"]),
                                        (r["team2"], r["team1"], r["cats2"], r["cats1"])):
            s = st[me]
            s["cats"] += mine
            s["w" if mine > theirs else "l" if mine < theirs else "t"] += 1
    return sorted(st.values(), key=lambda s: (-(s["w"] + s["t"] / 2), -s["cats"], s["id"]))   # ties: team id


def build_odds_html(teams, season):
    tpl = (ROOT / "scripts" / "odds_template.html").read_text(encoding="utf-8")
    payload = {
        "season": SEASON,
        "teams": [{"id": int(t["id"]), "team": t["team"], "manager": t["manager"]} for t in teams],
        **season,
        "standings": standings(teams, season["results"]),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__DATA__*/null", data)


def main():
    check = "--check" in sys.argv
    teams, rows, budgets = load()
    n_drafted = sum(1 for r in rows if r["pick"] != "")
    csv_text = write_csv(rows)
    committed = {
        ROOT / "rights.csv": csv_text,
        ROOT / "KEEPERS.md": build_md(teams, rows, budgets, n_drafted),
    }
    stale = []
    for path, text in committed.items():
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            stale.append(path.relative_to(ROOT))
            if not check:
                path.write_text(text, encoding="utf-8")
    if check and stale:
        die("generated files are stale, run scripts/build.py: " + ", ".join(map(str, stale)))

    # The website is not committed; it is always rebuilt (GitHub Actions deploys _site/).
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(build_html(teams, rows, budgets, n_drafted), encoding="utf-8")
    (SITE / "rights.csv").write_text(csv_text, encoding="utf-8")
    season = load_season(teams)
    (SITE / "odds.html").write_text(build_odds_html(teams, season), encoding="utf-8")

    print(f"{len(rows)} players, {n_drafted} drafted picks; "
          + ("updated " + ", ".join(map(str, stale)) if stale else "no changes")
          + f"; {len(season['results'])} results, odds for {len(season['odds'])} weeks"
          + f"; site written to {SITE.relative_to(ROOT)}/")

if __name__ == "__main__":
    main()
