#!/usr/bin/env python3
"""The site from the data files (Python 3, stdlib only) → _site/: index.html (the week: matchup odds), standings.html,
keepers.html (keeper rights), vaimanieki.html (injured players' dollars), rights.csv; odds.html sends old links to
index.html. Not
committed: GitHub Actions builds and deploys it on every push to main.

    data/league/            the league's own facts, kept by hand
      teams.csv             team_id, name, manager, own_name: the names the site shows (never Yahoo's); own_name 1:
                            the name differs from Yahoo's on purpose (import.py warns about any other difference)
      budget_trades.csv     date, from_team, to_team, amount, note: next season's draft dollars traded (team ids)
      draft_corrections.csv player_id, price, note: draft prices where Yahoo's record is wrong
    data/yahoo/             the league as Yahoo has it, written by scripts/import.py from yfbb's data; never edited

Keeper rights: every drafted player's are with the team that drafted him, then move with each transaction (a drop
frees them, an add takes them). A player's keeper base is the most paid for him this season (draft price or FAB, 0
if neither) and stays with him through drops and trades; keeping him costs ceil(max(base × 1.15, base + 5)) the next
season, and so on. Next season's budget: $200 ± draft dollars traded, at most $215.

Vaimanieki: the players whose rights a team holds and whom Yahoo flags injured (INJURED) now; a player's dollars are
his keeper base.

Any inconsistency in the data stops the build with an error (nothing is written).

Usage: python3 scripts/build.py"""
import csv
import io
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
SITE = ROOT / '_site'
TEMPLATES = ROOT / 'templates'

BUDGET = 200
BUDGET_CAP = 215
ROSTER_SPOTS = 13
KEEPER_SEASONS = 3   # keeper prices shown for this many seasons ahead
CATEGORIES = [   # id (as in the sims), label, lower wins
    ('fg', 'FG%', False), ('ft', 'FT%', False), ('tpm', '3PM', False), ('pts', 'PTS', False), ('reb', 'REB', False),
    ('ast', 'AST', False), ('stl', 'ST', False), ('blk', 'BLK', False), ('to', 'TO', True)]
STATS = ['fgm', 'fga', 'ftm', 'fta', 'tpm', 'pts', 'reb', 'ast', 'stl', 'blk', 'to']   # totals.csv's
SOURCES = {'yahoo': 'Yahoo (Rotowire)', 'blend': 'Average (Yahoo + ESPN)', 'espn': 'ESPN'}   # the first: the default
INJURED = {'O'}   # Yahoo's injury flags that count as injured on the Vaimanieki page
MIN_INJURED = 1   # injured players listed there: worth at least this many dollars
# the league's examples of the keeper price rule, checked on every build
EXAMPLES = [[1, 6, 11, 16, 21, 26, 31, 36, 42], [100, 115]]


def main():
    for chain in EXAMPLES:
        if [escalate(p) for p in chain[:-1]] != chain[1:]:
            die(f'the keeper price rule doesn\'t give the league\'s example {chain}')
    league = {name: read(f'league/{name}.csv') for name in ('teams', 'budget_trades', 'draft_corrections')}
    yahoo = {name: read(f'yahoo/{name}.csv') for name in
             ('players', 'draft', 'transactions', 'matchups', 'standings', 'fetched', 'sims', 'odds', 'power', 'h2h',
              'totals')}
    teams = {r['team_id']: r for r in league['teams']}
    season = season_of(yahoo['matchups'])
    seasons = [season_after(season, i + 1) for i in range(KEEPER_SEASONS)]

    check_teams(teams, yahoo)
    weeks, pairs = schedule(teams, yahoo['matchups'])
    rows = rights(teams, yahoo, league['draft_corrections'], seasons)
    budgets = next_budgets(teams, league['budget_trades'])
    odds = sims(teams, yahoo, pairs)
    hurt = injuries(teams, rows, yahoo)

    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    keepers = {'season': season, 'next': seasons, 'slots': len(teams) * ROSTER_SPOTS,
               'drafted': len(yahoo['draft']), 'teams': [{'team': t['name'], 'manager': t['manager'],
                                                          'budget': budgets[i]} for i, t in teams.items()],
               'rows': rows}
    page('keepers.html', 'keepers.html', keepers)
    page('vaimanieki.html', 'vaimanieki.html', hurt)
    page('redirect.html', 'odds.html', {})
    page('standings.html', 'standings.html', {
        'teams': [{'id': int(i), 'team': t['name'], 'manager': t['manager']} for i, t in teams.items()],
        'standings': standings(yahoo['standings']),
    })
    page('odds.html', 'index.html', {
        'season': season,
        'teams': [{'id': int(i), 'team': t['name'], 'manager': t['manager']} for i, t in teams.items()],
        'weeks': weeks,
        'categories': [{'id': c, 'label': label, 'lower': lower} for c, label, lower in CATEGORIES],
        'sources': [{'id': s, 'label': SOURCES.get(s, s)} for s in odds],
        'sims': odds,
    })
    (SITE / 'rights.csv').write_text(rights_csv(rows), encoding='utf-8')
    print(f'{len(rows)} players with keeper rights, {len(yahoo["draft"])} picks, {len(yahoo["transactions"])} '
          f'transactions, {sum(t["injured"] for t in hurt["teams"])} injured; odds of {len({w for w, _, _ in pairs})} weeks by {", ".join(odds)} -> {SITE.relative_to(ROOT)}/')


def season_of(matchups):
    """The season of the schedule's first day (a season starts in July): 2026-27."""
    first = min(r['first_day'] for r in matchups if r['first_day'])
    start = int(first[:4]) - (int(first[5:7]) < 7)
    return f'{start}-{(start + 1) % 100:02d}'


def season_after(season, n):
    """The season n after season: 2026-27, 1 → 2027-28."""
    start = int(season[:4]) + n
    return f'{start}-{(start + 1) % 100:02d}'


def check_teams(teams, yahoo):
    """Every team id in Yahoo's data is one of data/league/teams.csv's."""
    for name, rows in yahoo.items():
        for r in rows:
            for k in ('team_id', 'team1', 'team2'):
                if r.get(k) and r[k] not in teams:
                    die(f'data/yahoo/{name}.csv: team {r[k]} is not in data/league/teams.csv')


def schedule(teams, matchups):
    """[{week, start, end, scores}] of every week, and {(week, team1, team2)} of its pairings: lower id first, every
    team once a week (or the week has no pairings yet). scores: Yahoo's, [team1, team2, score1, score2] of each pairing
    that has one (categories won)."""
    weeks, pairs, played = {}, set(), {}
    for r in matchups:
        week = int(r['week'])
        weeks.setdefault(week, {'week': week, 'start': r['first_day'], 'end': r['last_day'], 'scores': []})
        if r['score1'] and r['score2']:
            weeks[week]['scores'].append([int(r['team1']), int(r['team2']), int(r['score1']), int(r['score2'])])
        if r['team1']:
            if int(r['team1']) >= int(r['team2']):
                die(f'data/yahoo/matchups.csv: week {week}: {r["team1"]}-{r["team2"]} isn\'t lower id first')
            pairs.add((week, r['team1'], r['team2']))
            played.setdefault(week, []).extend((r['team1'], r['team2']))
    for week, ids in played.items():
        if sorted(ids, key=int) != sorted(teams, key=int):
            die(f'data/yahoo/matchups.csv: week {week} doesn\'t have every team exactly once')
    weeks = [weeks[w] for w in sorted(weeks)]
    for a, b in zip(weeks, weeks[1:]):
        if b['week'] != a['week'] + 1 or not a['end'] < b['start']:
            die(f'data/yahoo/matchups.csv: week {b["week"]} doesn\'t follow week {a["week"]}')
    return weeks, pairs


def rights(teams, yahoo, corrections, seasons):
    """Every player's keeper rights: drafted, then moved by each transaction in order (drops before adds of the same
    minute). One row per player, highest keeper base first."""
    players = {r['player_id']: r for r in yahoo['players']}
    fixed = {r['player_id']: r for r in corrections}
    people = {}
    for r in yahoo['draft']:
        pid = r['player_id']
        if pid in people:
            die(f'data/yahoo/draft.csv: {name(players, pid)} drafted twice')
        price = int(r['price'])
        if pid in fixed:
            if int(fixed[pid]['price']) == price:
                warn(f'data/league/draft_corrections.csv: Yahoo now has ${price} for {name(players, pid)} too; the '
                     'correction can go')
            price = int(fixed[pid]['price'])
        people[pid] = {'pick': int(r['pick']), 'drafted_by': r['team_id'], 'draft_price': price, 'fab': None,
                       'team': r['team_id'], 'moves': []}
    if unknown := fixed.keys() - people.keys():
        die(f'data/league/draft_corrections.csv: players not drafted {sorted(unknown, key=int)}')

    for r in sorted(yahoo['transactions'], key=lambda r: (r['time'], r['action'] != 'drop')):
        pid, team, action = r['player_id'], r['team_id'], r['action']
        who = f'{name(players, pid)} ({r["time"]})'
        p = people.setdefault(pid, {'pick': None, 'drafted_by': None, 'draft_price': None, 'fab': None, 'team': None,
                                    'moves': []})
        if action == 'drop':
            if p['team'] != team:
                die(f'data/yahoo/transactions.csv: team {team} drops {who}, whose rights are with '
                    f'{p["team"] or "nobody"}')
            p['team'] = None
        elif action == 'add':
            if p['team']:
                die(f'data/yahoo/transactions.csv: team {team} adds {who}, whose rights are still with {p["team"]}')
            p['team'] = team
            p['fab'] = max(p['fab'] or 0, int(r['fab'] or 0))
        elif action == 'trade':
            if not p['team'] or p['team'] == team:
                die(f'data/yahoo/transactions.csv: team {team} gets {who} in a trade, whose rights are with '
                    f'{p["team"] or "nobody"}')
            p['team'] = team
        else:
            die(f'data/yahoo/transactions.csv: {who}: no rule for a {action!r} yet')
        p['moves'].append(f'{r["time"][:10]} {action}')

    rows = []
    for pid, p in people.items():
        if pid not in players:
            die(f'data/yahoo/players.csv: no player {pid}')
        base = max(p['draft_price'] or 0, p['fab'] or 0)
        keep = base
        prices = []
        for _ in seasons:
            keep = escalate(keep)
            prices.append(keep)
        rows.append({'player_id': pid, 'player': players[pid]['name'], 'nba_team': players[pid]['nba_team'],
                     'pos': players[pid]['positions'].replace(',', '/'), 'rights': team_name(teams, p['team']),
                     'pick': p['pick'] or '', 'drafted_by': team_name(teams, p['drafted_by']),
                     'draft_price': '' if p['draft_price'] is None else p['draft_price'],
                     'fab_paid': '' if p['fab'] is None else p['fab'], 'keeper_base': base,
                     **{f'keeper_{s}': k for s, k in zip(seasons, prices)}, 'moves': '; '.join(p['moves'])})

    spent = {}
    for p in people.values():
        if p['drafted_by']:
            spent[p['drafted_by']] = spent.get(p['drafted_by'], 0) + p['draft_price']
    for team, total in sorted(spent.items(), key=lambda kv: int(kv[0])):
        if total > BUDGET:
            warn(f'{team_name(teams, team)} drafted for ${total}, over the ${BUDGET} budget')
    return sorted(rows, key=lambda r: (-r['keeper_base'], r['player']))


def injuries(teams, rows, yahoo):
    """The Vaimanieki page: per team, its players flagged injured now and their dollars (keeper bases), most first,
    against all its players' dollars; and every injured player worth at least $MIN_INJURED, most expensive first. Only
    players whose rights a team holds."""
    status = {r['player_id']: r['status'] for r in yahoo['players']}
    hurt = [r for r in rows if r['rights'] and status[r['player_id']] in INJURED]
    table = []
    for t in teams.values():
        mine = [r for r in rows if r['rights'] == t['name']]
        out = [r for r in hurt if r['rights'] == t['name']]
        table.append({'team': t['name'], 'manager': t['manager'], 'injured': len(out),
                      'value': sum(r['keeper_base'] for r in out), 'total': sum(r['keeper_base'] for r in mine)})
    table.sort(key=lambda r: (-r['value'], -r['injured'], r['team'].lower()))
    top = sorted((r for r in hurt if r['keeper_base'] >= MIN_INJURED), key=lambda r: (-r['keeper_base'], r['player']))
    fetched = {r['table']: r['fetched'] for r in yahoo['fetched']}
    return {'as_of': fetched.get('players', ''), 'flags': sorted(INJURED), 'teams': table,
            'players': [{'player': r['player'], 'nba_team': r['nba_team'], 'team': r['rights'],
                         'value': r['keeper_base'], 'status': status[r['player_id']]} for r in top]}


def escalate(price):
    """The league's keeper price rule: + max(15%, $5) a season, rounded up."""
    return math.ceil(max(price * 1.15, price + 5) - 1e-9)


def next_budgets(teams, trades):
    """Each team's draft budget next season, before keepers: $200 ± the dollars traded; at most $215."""
    budgets = dict.fromkeys(teams, BUDGET)
    for r in trades:
        for k in ('from_team', 'to_team'):
            if r[k] not in teams:
                die(f'data/league/budget_trades.csv: unknown team {r[k]!r} ({r["date"]})')
        budgets[r['from_team']] -= int(r['amount'])
        budgets[r['to_team']] += int(r['amount'])
    for team, total in budgets.items():
        if total > BUDGET_CAP:
            die(f'data/league/budget_trades.csv: {team_name(teams, team)} would have ${total}, over the '
                f'${BUDGET_CAP} cap')
    return budgets


def standings(rows):
    """Yahoo's standings, by rank (then team id)."""
    return [{'id': int(r['team_id']), 'rank': r['rank'], 'w': int(r['w']), 'l': int(r['l']), 't': int(r['t'])}
            for r in sorted(rows, key=lambda r: (int(r['rank'] or 99), int(r['team_id'])))]


def sims(teams, yahoo, pairs):
    """{source: {week: {live, frozen}}}: each week's live sim (now: the games played so far actual, the rest projected;
    the result once over) and its frozen one (at the newest lock passed; None before the lock), each {version, as_of,
    projections, state, played, projected, matchups, power}: the odds (pairings in the schedule) and power ranking;
    the live one also h2h: every pair of teams, [team1, team2, win1, tie, win2, cats1, cats2], and totals: {team:
    {week, played: {games, fgm, fga, ...}}}, the week's stats (played and projected) and, once games are played, those
    so far; week season: the season's power ranking (live only)."""
    out = {}
    for r in yahoo['sims']:
        kind = 'live' if r['version'] == 'live' else 'frozen'
        week = out.setdefault(r['source'], {}).setdefault(r['week'], {'live': None, 'frozen': None})
        if week[kind]:
            die(f'data/yahoo/sims.csv: two {kind} {r["source"]} sims of week {r["week"]}')
        week[kind] = {'version': r['version'], 'as_of': r['as_of'], 'projections': r['projections'],
                      'state': r['state'], 'played': int(r['played']) if r['played'] else None,
                      'projected': int(r['projected']) if r['projected'] else None, 'matchups': [], 'power': []}
    for r in yahoo['odds']:
        if (int(r['week']), r['team1'], r['team2']) not in pairs:
            die(f'data/yahoo/odds.csv: week {r["week"]} {r["team1"]}-{r["team2"]} is not in the schedule')
        sim(out, r)['matchups'].append(
            {'team1': int(r['team1']), 'team2': int(r['team2']),
             **{k: float(r[k]) for k in ('win1', 'tie', 'win2', 'cats1', 'cats2')},
             'games1': int(r['games1']), 'games2': int(r['games2']),
             **{k: int(r[k]) if r.get(k) else None for k in ('played1', 'played2')},   # older sims: none
             'categories': {c: [float(r[f'{c}_{k}']) for k in ('win1', 'tie', 'win2')] for c, _, _ in CATEGORIES}})
    for r in yahoo['power']:
        sim(out, r)['power'].append(
            {'team': int(r['team_id']), 'rank': int(r['rank']),
             **{k: float(r[k]) for k in ('win', 'tie', 'loss', 'cats')},
             'games': int(r['games']) if r['games'] else None,
             'totals': {c: float(r[c]) for c, _, _ in CATEGORIES},
             'ranks': {c: int(r[f'{c}_rank']) for c, _, _ in CATEGORIES}})
    for r in yahoo['h2h']:
        live = out.get(r['source'], {}).get(r['week'], {}).get('live')
        if not live:
            die(f'data/yahoo/h2h.csv: no live {r["source"]} sim of week {r["week"]}')
        if r['team1'] not in teams or r['team2'] not in teams or r['team1'] == r['team2']:
            die(f'data/yahoo/h2h.csv: {r["source"]} week {r["week"]}: no pair {r["team1"]}-{r["team2"]}')
        live.setdefault('h2h', []).append([int(r['team1']), int(r['team2']), *(
            float(r[k]) for k in ('win1', 'tie', 'win2', 'cats1', 'cats2'))])
    for r in yahoo['totals']:
        live = out.get(r['source'], {}).get(r['week'], {}).get('live')
        if not live or r['team_id'] not in teams or r['kind'] not in ('played', 'week'):
            die(f'data/yahoo/totals.csv: {r["source"]} week {r["week"]} team {r["team_id"]} {r["kind"]}: no such live sim, '
                'team or kind')
        live.setdefault('totals', {}).setdefault(int(r['team_id']), {})[r['kind']] = \
            {'games': int(r['games'])} | {k: float(r[k]) for k in STATS}
    for source, weeks in out.items():
        for week, both in weeks.items():
            if not both['live']:
                die(f'data/yahoo/sims.csv: no live {source} sim of week {week}')
            for kind, s in both.items():
                if s and len(s['power']) != len(teams):
                    die(f'data/yahoo/power.csv: {source} week {week} {kind} has {len(s["power"])} teams, not '
                        f'{len(teams)}')
                if kind == 'live':
                    h2h = [frozenset(h[:2]) for h in s.get('h2h', [])]
                    if not len(h2h) == len(set(h2h)) == len(teams) * (len(teams) - 1) // 2:
                        die(f'data/yahoo/h2h.csv: {source} week {week} doesn\'t have every pair of teams exactly once')
                if s and both['frozen'] and len(s['matchups']) != len(both['live']['matchups']):
                    die(f'data/yahoo/odds.csv: {source} week {week}: live and frozen have different pairings')
    return dict(sorted(out.items(), key=lambda kv: list(SOURCES).index(kv[0]) if kv[0] in SOURCES else len(SOURCES)))


def sim(out, r):
    both = out.get(r['source'], {}).get(r['week'], {})
    s = both.get('live' if r['version'] == 'live' else 'frozen')
    if not s or s['version'] != r['version']:
        die(f'data/yahoo/sims.csv: no {r["source"]} sim {r["version"]} of week {r["week"]}')
    return s


def page(template, name, payload):
    """A page: its template with the payload as JSON in place of /*__DATA__*/null."""
    data = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    html = (TEMPLATES / template).read_text(encoding='utf-8').replace('/*__DATA__*/null', data)
    (SITE / name).write_text(html, encoding='utf-8')


def rights_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, list(rows[0]), lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def team_name(teams, team_id):
    return teams[team_id]['name'] if team_id else ''


def name(players, pid):
    return players[pid]['name'] if pid in players else pid


def read(name):
    path = DATA / name
    if not path.exists():
        die(f'no {path.relative_to(ROOT)}' + ('; run scripts/import.py' if name.startswith('yahoo/') else ''))
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def warn(message):
    print(f'warning: {message}', file=sys.stderr)


def die(message):
    sys.exit(f'error: {message}')


if __name__ == '__main__':
    main()
