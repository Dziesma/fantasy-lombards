# Fantasy Lombards

The site of our 16-team Yahoo NBA keeper league, at **https://dziesma.github.io/fantasy-lombards/**:

- **Keeper rights** (`index.html`): think of it as a pawnshop: every player bought can be bought back next season,
  with interest. For every player drafted or picked up: what was paid for him this season, what keeping him costs
  the next three seasons, and which team holds his rights now. Searchable, sortable, filterable by team; also as
  `rights.csv`.
- **Standings & odds** (`odds.html`): Yahoo's One-Win standings, every week's projected matchup odds and power
  ranking, and the season's power ranking (roster strength), by Yahoo's projections (Rotowire's), ESPN's or their
  average. Team-level only.

## Keeper rules

| Rule | Here |
|---|---|
| Price per kept season | `next = ceil(max(price × 1.15, price + 5))`: +$5 below ~$33, +15% above |
| Example chain | $1 → 6 → 11 → 16 → 21 → 26 → 31 → 36 → 42 · $100 → 115 (checked on every build) |
| Keeper base | the most paid for the player this season: draft price or FAB, whichever is higher (0 if neither) |
| Drops and trades | rights go with the player; the base stays |
| Undrafted player added for $0 FAB | base $0, so keeper $5 (**not yet confirmed by the league**) |
| Next season's budget | $200 ± traded draft dollars − keeper costs; hard cap **$215** including keepers |

## Data

Everything on the site is built from the files in `data/`, nothing else:

| Files | What | Kept by |
|---|---|---|
| `data/yahoo/*.csv` | the league as Yahoo has it: players, draft, transactions, schedule, standings, and the team-level odds and power rankings of the sims | `scripts/import.py`, from the maintainer's yfbb data (a private tool); never edited by hand |
| `data/league/teams.csv` | `team_id, name, manager, own_name`: the names the site shows (Yahoo's are never used) and the managers. `own_name` 1: the name differs from Yahoo's on purpose | hand |
| `data/league/budget_trades.csv` | `date, from_team, to_team, amount, note`: next season's draft dollars traded, by team id (Yahoo doesn't know about them) | hand |
| `data/league/draft_corrections.csv` | `player_id, price, note`: draft prices where Yahoo's draft results are wrong | hand |

`data/yahoo/` has only what the site shows: the players drafted or in a transaction (name, NBA team, positions),
picks and transactions by ids, the weeks and pairings, Yahoo's W-L-T, and per sim (each projection source, each
week) the pairings' odds and each team's projected category totals. No player projections.

A week's odds are frozen at its lineup lock (Monday; weeks 7 and 17 have a second, on their middle Monday): the
lineups that locked, the projections of then. Until then they're live, with each team's best lineup.

## Updating

The maintainer, after `yfbb data sync` and `yfbb sim`:

```sh
python3 scripts/import.py   # yfbb's data -> data/yahoo/ (reads yfbb's config for where it is; --data DIR otherwise)
python3 scripts/build.py    # validates everything, builds the site in _site/ (open _site/index.html to preview)
git add data && git commit && git push
```

`import.py` warns when a team's Yahoo name isn't its name in `data/league/teams.csv` (a rename to take over, or to
mark `own_name`). `build.py` (Python 3, standard library only) stops with an error on anything inconsistent: unknown
team ids, a player drafted twice, a drop by a team without his rights or an add of a player still owned, a week
without every team exactly once, odds of a pairing not in the schedule, a budget over the cap, a correction for an
undrafted player, a keeper price rule that doesn't give the league's examples. It warns about a correction Yahoo no
longer needs.

## Hosting

GitHub Actions (`.github/workflows/pages.yml`) builds the site on every push and pull request, and deploys it on
`main` (Settings → Pages → Source: **GitHub Actions**). The site itself isn't committed. If a deploy fails, re-run it
from Actions → *build-and-deploy* → *Run workflow*.
