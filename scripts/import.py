#!/usr/bin/env python3
"""yfbb's data → data/yahoo/: the league as Yahoo has it, only what the site shows (Python 3.11+, stdlib only).

Run by hand after `yfbb data sync` and `yfbb sim`, then build and commit what it writes. Reads <dir>/curated/current/
and <dir>/sim/, dir: --data, else [data] dir in ~/.config/yfbb/config.toml, else ~/.local/share/yfbb (yfbb's own
default). Takes no team names (the site's are data/league/teams.csv; Yahoo's are only compared with them, to warn)
and nothing below team level from the sims.

Writes, each file whole (don't edit them by hand):
    players.csv       player_id, name, nba_team, positions: every player drafted or in a transaction
    draft.csv         pick, player_id, team_id, price
    transactions.csv  time, team_id, action, player_id, fab: oldest first
    matchups.csv      week, first_day, last_day, team1, team2: a week without pairings yet has its teams empty
    standings.csv     team_id, rank, w, l, t: Yahoo's
    sims.csv          source, week, version, as_of, projections: which sim each week's odds come from
    odds.csv          source, week, team1, team2, win1, tie, win2, cats1, cats2, games1, games2, <cat>_win1,
                      <cat>_tie, <cat>_win2: each pairing
    power.csv         source, week, rank, team_id, win, tie, loss, cats, games, <cat>, <cat>_rank: each team
                      against all others; week season: the season's power ranking (no games)

A week's odds are frozen at its newest lock passed (week-NN, or week-NN-2 in a two-week week), else live; the locked
lineups (those that locked, the best where none has yet)."""
import argparse
import csv
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'yahoo'
YFBB_CONFIG = Path('~/.config/yfbb/config.toml').expanduser()
YFBB_DIR = '~/.local/share/yfbb'
LINEUP = 'locked'
COLUMNS = {
    'players': ['player_id', 'name', 'nba_team', 'positions'],
    'draft': ['pick', 'player_id', 'team_id', 'price'],
    'transactions': ['time', 'team_id', 'action', 'player_id', 'fab'],
    'matchups': ['week', 'first_day', 'last_day', 'team1', 'team2'],
    'standings': ['team_id', 'rank', 'w', 'l', 't'],
    'sims': ['source', 'week', 'version', 'as_of', 'projections'],
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
    tables['sims'], odds, power = sims(root)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        _write(OUT / f'{name}.csv', COLUMNS[name], rows)
    _write(OUT / 'odds.csv', list(odds[0]), odds)
    _write(OUT / 'power.csv', list(next(r for r in power if r['week'] != 'season')), power)
    print(f'{len(players)} players, {len(yahoo["draft"])} picks, {len(yahoo["transactions"])} transactions; odds of '
          f'{len({r["week"] for r in tables["sims"]}) - 1} weeks by {", ".join(dict.fromkeys(r["source"] for r in tables["sims"]))}'
          f' -> {OUT.relative_to(ROOT)}/')


def sims(root):
    """(sims, odds, power) rows of every source's sims: each week with pairings, from its newest frozen sim (a lock
    passed), else the live one; and the season's power ranking."""
    live, frozen = root / 'sim' / 'live', root / 'sim' / 'frozen'
    if not (live / 'season').is_dir():
        _die(f'no {live / "season"}; run `yfbb sim`')
    sources = sorted((d.name for d in (live / 'season').iterdir() if d.is_dir()), key=lambda s: (s != 'blend', s))
    weeks = sorted(int(d.name.removeprefix('week-')) for d in live.glob('week-*'))
    rows, odds, power = [], [], []
    for source in sources:
        for week in weeks:
            locks = sorted(d.name for d in frozen.glob(f'week-{week:02d}*') if (d / source / LINEUP).is_dir())
            folder = frozen / locks[-1] / source / LINEUP if locks else live / f'week-{week:02d}' / source / LINEUP
            rows.append(_sim(source, week, locks[-1] if locks else 'live', folder))
            odds += [{'source': source} | r for r in _read(folder / 'odds.csv')]
            power += [{'source': source, 'week': week} | r for r in _read(folder / 'power.csv')]
        rows.append(_sim(source, 'season', 'live', live / 'season' / source))
        power += [{'source': source, 'week': 'season'} | r for r in _read(live / 'season' / source / 'power.csv')]
    return rows, odds, power


def _sim(source, week, version, folder):
    """A sim's row in sims.csv, from its manifest."""
    lines = (folder / 'manifest.txt').read_text().splitlines()
    value = {key: line.removeprefix(f'{key}: ') for line in lines for key in ('as_of', 'projections')
             if line.startswith(f'{key}: ')}
    return {'source': source, 'week': week, 'version': version, 'as_of': value.get('as_of', ''),
            'projections': value.get('projections', '').replace(' as_of ', ' ')}


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
