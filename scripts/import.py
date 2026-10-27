#!/usr/bin/env python3
"""yfbb's data → data/yahoo/: the league as Yahoo has it, only what the site shows (Python 3.11+, stdlib only).

Run by hand after `yfbb data sync` and `yfbb sim`, then build and commit what it writes. Reads <dir>/curated/current/
and <dir>/sim/, dir: --data, else [data] dir in ~/.config/yfbb/config.toml, else ~/.local/share/yfbb (yfbb's own
default). Takes no team names (the site's are data/league/teams.csv; Yahoo's are only compared with them, to warn)
and nothing below team level from the sims.

Writes, each file whole (don't edit them by hand):
    players.csv       player_id, name, nba_team, positions, status: every player drafted or in a transaction;
                      status: Yahoo's injury flag (O, Q, NA, ...; empty: none)
    draft.csv         pick, player_id, team_id, price
    transactions.csv  time, team_id, action, player_id, fab: oldest first
    matchups.csv      week, first_day, last_day, team1, team2, score1, score2: a week without pairings yet has its
                      teams empty; score: the categories each has won on Yahoo, as of the newest fetch (the result
                      once the week is over; a category tied is neither's)
    standings.csv     team_id, rank, w, l, t: Yahoo's
    fetched.csv       table, fetched: when each of the tables above was last fetched from Yahoo (UTC)
    sims.csv          source, week, version, as_of, projections, state, played, projected: the sims each week's
                      odds come from; version: live, or the lock it's frozen at; state (live): open (before the
                      lock), locked (its games being played), finished (the result); played, projected: its
                      starter games so far (empty when the sim doesn't say)
    odds.csv          source, week, version, team1, team2, win1, tie, win2, cats1, cats2, games1, games2,
                      played1, played2, <cat>_win1, <cat>_tie, <cat>_win2: each pairing; games: starter games (a
                      game a starter sat out isn't one), played: of them with a box score
    power.csv         source, week, version, rank, team_id, win, tie, loss, cats, games, <cat>, <cat>_rank: each
                      team against all others; week season: the season's power ranking (no games)
    h2h.csv           source, week, team1, team2, win1, tie, win2, cats1, cats2: every pair of teams (the power
                      ranking's round robin), of the live sims only; week season: the season's
    totals.csv        source, week, team_id, kind, games, fgm, fga, ftm, fta, tpm, pts, reb, ast, stl, blk, to: each
                      team's starter stats in a live sim with pairings, summed from its player games; kind: week
                      (played and projected: the projected totals, with makes and attempts) or, once games are
                      played, played (the box scores so far)

Each week has its live sim (what is known now: the games played so far actual, the rest projected; the result once
it's over) and, once a lock has passed, the newest frozen one (week-NN, or week-NN-2 in a two-week week: what was
expected at the lock). The locked lineups (those that locked, the best where none has yet)."""
import argparse
import csv
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'yahoo'
YFBB_CONFIG = Path('~/.config/yfbb/config.toml').expanduser()
YFBB_DIR = '~/.local/share/yfbb'
LINEUP = 'locked'
STATS = ['fgm', 'fga', 'ftm', 'fta', 'tpm', 'pts', 'reb', 'ast', 'stl', 'blk', 'to']
COLUMNS = {
    'players': ['player_id', 'name', 'nba_team', 'positions', 'status'],
    'draft': ['pick', 'player_id', 'team_id', 'price'],
    'transactions': ['time', 'team_id', 'action', 'player_id', 'fab'],
    'matchups': ['week', 'first_day', 'last_day', 'team1', 'team2', 'score1', 'score2'],
    'standings': ['team_id', 'rank', 'w', 'l', 't'],
    'sims': ['source', 'week', 'version', 'as_of', 'projections', 'state', 'played', 'projected'],
    'fetched': ['table', 'fetched'],
}


def main():
    parser = argparse.ArgumentParser(description="yfbb's data → data/yahoo/ (what the site shows)")
    parser.add_argument('--data', type=Path, help=f'yfbb\'s data dir (default: [data] dir in {YFBB_CONFIG})')
    root = (parser.parse_args().data or _yfbb_dir()).expanduser()
    current = root / 'curated' / 'current'
    yahoo = {name: _read(current / f'{name}.csv')
             for name in ('teams', 'players', 'draft', 'transactions', 'matchups', 'standings')}
    _check_teams(yahoo['teams'])

    wanted = {r['player_id'] for table in ('draft', 'transactions') for r in yahoo[table]}
    players = sorted((r for r in yahoo['players'] if r['player_id'] in wanted), key=lambda r: int(r['player_id']))
    if missing := wanted - {r['player_id'] for r in players}:
        _die(f'curated players has no {sorted(missing, key=int)}, who are drafted or in a transaction')
    tables = {'players': players} | {name: yahoo[name] for name in ('draft', 'transactions', 'matchups', 'standings')}
    tables['fetched'] = fetched(current, list(tables))
    tables['sims'], odds, power, h2h, totals = sims(root)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        _write(OUT / f'{name}.csv', COLUMNS[name], rows)
    _write(OUT / 'odds.csv', list(max(odds, key=len)), odds)   # older sims have no played1, played2
    _write(OUT / 'power.csv', list(next(r for r in power if r['week'] != 'season')), power)
    _write(OUT / 'h2h.csv', list(h2h[0]), h2h)
    _write(OUT / 'totals.csv', ['source', 'week', 'team_id', 'kind', 'games', *STATS], totals)
    frozen = {r['week'] for r in tables['sims'] if r['version'] != 'live'}
    print(f'{len(players)} players, {len(yahoo["draft"])} picks, {len(yahoo["transactions"])} transactions; odds of '
          f'{len({r["week"] for r in tables["sims"]}) - 1} weeks ({len(frozen)} also frozen) by '
          f'{", ".join(dict.fromkeys(r["source"] for r in tables["sims"]))} -> {OUT.relative_to(ROOT)}/')


def fetched(current, names):
    """[{table, fetched}] of the tables names, from the curated version's manifest: each one's newest fetch."""
    found = {}
    for line in (current / 'manifest.txt').read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in names and parts[1].isdigit():
            found[parts[0]] = parts[2]
    if missing := [n for n in names if n not in found]:
        _die(f'{current / "manifest.txt"} has no newest fetch of {missing}')
    return [{'table': n, 'fetched': found[n]} for n in names]


def sims(root):
    """(sims, odds, power, h2h, totals) rows of every source's sims: each week's live one and its newest frozen one (a
    lock passed); and the season's power ranking. h2h: the live ones' only; totals: the live ones' with pairings."""
    live, frozen = root / 'sim' / 'live', root / 'sim' / 'frozen'
    if not (live / 'season').is_dir():
        _die(f'no {live / "season"}; run `yfbb sim`')
    sources = sorted((d.name for d in (live / 'season').iterdir() if d.is_dir()), key=lambda s: (s != 'blend', s))
    weeks = sorted(int(d.name.removeprefix('week-')) for d in live.glob('week-*'))
    rows, odds, power, h2h, totals = [], [], [], [], []
    for source in sources:
        for week in weeks:
            locks = sorted(d.name for d in frozen.glob(f'week-{week:02d}*') if (d / source / LINEUP).is_dir())
            folders = {'live': live / f'week-{week:02d}' / source / LINEUP}
            if locks:
                folders[locks[-1]] = frozen / locks[-1] / source / LINEUP
            for version, folder in folders.items():
                rows.append(_sim(source, week, version, folder))
                odds += [{'source': source, 'version': version} | r for r in _read(folder / 'odds.csv')]
                power += [{'source': source, 'week': week, 'version': version} | r
                          for r in _read(folder / 'power.csv')]
            h2h += [{'source': source, 'week': week} | r for r in _read(folders['live'] / 'h2h.csv')]
            if (folders['live'] / 'player_games.csv').exists():
                totals += _totals(source, week, _read(folders['live'] / 'player_games.csv'))
        rows.append(_sim(source, 'season', 'live', live / 'season' / source))
        power += [{'source': source, 'week': 'season', 'version': 'live'} | r
                  for r in _read(live / 'season' / source / 'power.csv')]
        h2h += [{'source': source, 'week': 'season'} | r for r in _read(live / 'season' / source / 'h2h.csv')]
    return rows, odds, power, h2h, totals


def _totals(source, week, games):
    """A live sim's totals rows: each team's player games summed, those played and all (played and projected)."""
    sums = {}
    for g in games:
        for kind in ('played', 'week') if g['played'] == '1' else ('week',):
            t = sums.setdefault((int(g['team_id']), kind), {'games': 0} | dict.fromkeys(STATS, 0.0))
            t['games'] += 1
            for k in STATS:
                t[k] += float(g[k])
    return [{'source': source, 'week': week, 'team_id': team, 'kind': kind, 'games': t['games']} |
            {k: f'{t[k]:.4f}'.rstrip('0').rstrip('.') for k in STATS} for (team, kind), t in sorted(sums.items())]


def _sim(source, week, version, folder):
    """A sim's row in sims.csv, from its manifest. state: of its segments (`segment <lock>: <days>, <state>, ...`),
    finished if all are, open if all are, else locked; played, projected: the starter games its segments count (yfbb
    writes them for locked and finished segments), summed."""
    lines = (folder / 'manifest.txt').read_text().splitlines()
    value = {key: line.removeprefix(f'{key}: ') for line in lines for key in ('as_of', 'projections')
             if line.startswith(f'{key}: ')}
    segments = [line.split(', ') for line in lines if line.startswith('segment ')]
    states = {parts[1] for parts in segments}
    counts = [re.fullmatch(r'starter games: (\d+) played', p) for parts in segments for p in parts]
    projected = [re.fullmatch(r'(\d+) projected', p) for parts in segments for p in parts]
    return {'source': source, 'week': week, 'version': version, 'as_of': value.get('as_of', ''),
            'projections': value.get('projections', '').replace(' as_of ', ' '),
            'state': '' if not states else next(iter(states)) if len(states) == 1 else 'locked',
            'played': sum(int(m[1]) for m in counts if m) if any(counts) else '',
            'projected': sum(int(m[1]) for m in projected if m) if any(projected) else ''}


def _check_teams(yahoo):
    """Yahoo's teams must be the site's (by id). Warn about a team whose Yahoo name isn't the site's, unless own_name
    says that's on purpose: a rename, to take over in data/league/teams.csv or mark own_name."""
    league = {r['team_id']: r for r in _read(ROOT / 'data' / 'league' / 'teams.csv')}
    if (ids := {r['team_id'] for r in yahoo}) != league.keys():
        _die(f'Yahoo\'s team ids {sorted(ids, key=int)} aren\'t those of data/league/teams.csv '
             f'{sorted(league, key=int)}')
    for r in yahoo:
        team = league[r['team_id']]
        if r['yahoo_name'] != team['name'] and team['own_name'] != '1':
            print(f'warning: team {r["team_id"]} is {r["yahoo_name"]!r} on Yahoo, {team["name"]!r} on the site; '
                  'update data/league/teams.csv, or set its own_name to 1 to keep the site\'s', file=sys.stderr)


def _yfbb_dir():
    config = tomllib.loads(YFBB_CONFIG.read_text()) if YFBB_CONFIG.exists() else {}
    return Path(config.get('data', {}).get('dir', YFBB_DIR))


def _read(path):
    if not path.exists():
        _die(f'no {path}; run `yfbb data sync` and `yfbb sim`')
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write(path, columns, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, columns, extrasaction='ignore', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def _die(message):
    sys.exit(f'import: {message}')


if __name__ == '__main__':
    main()
