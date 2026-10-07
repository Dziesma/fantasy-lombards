# Fantasy Lombards

The keeper-rights tracker for our 16-team Yahoo NBA keeper league. Think of it as a pawnshop: every player
bought at the auction can be bought back next season, with interest. For every player drafted (or picked
up), it shows:

- what was paid for them in the 2026-27 auction (or FAB),
- what keeping them costs in 2027-28, 2028-29 and 2029-30,
- which team holds their keeper rights right now.

It also hosts the season's One-Win **standings** and each week's projected **matchup odds** (team-level only).

**Where to look**

- **[KEEPERS.md](KEEPERS.md)**: tables per team plus an A–Z list (renders on GitHub).
- **Website**: searchable and sortable, with a team filter. GitHub Actions rebuilds and deploys it on every
  push to `main`, at **https://dziesma.github.io/fantasy-lombards/**.
- **[rights.csv](rights.csv)**: the same data for spreadsheets.
- **[Standings & odds](https://dziesma.github.io/fantasy-lombards/odds.html)**: standings from the results, plus every
  week's matchup odds and power ranking. Pick a week and whose projections to use (ESPN, Yahoo/Rotowire, or the
  average of both); open a matchup for the per-category breakdown.

## Keeper rules used here

| Rule | Implementation |
|---|---|
| Price escalation per kept season | `next = ceil(max(price × 1.15, price + 5))`, so +$5 below ~$33 and +15% above |
| Example chain | $1 → 6 → 11 → 16 → 21 → 26 → 31 → 36 → 42 · $100 → 115 |
| FA / waiver pickups | base = max(this season's draft price, FAB paid), then the normal escalation |
| Undrafted player added for $0 FAB | base $0, so keeper $5 (**not yet confirmed by the league**) |
| Next season's budget | $200 ± traded budget dollars − keeper costs; hard cap **$215** including keepers |

"Total keeper cost if all kept" is just the sum. Nobody is expected to keep everyone. It's there to compare against the budget.

## Updating the data

Only edit the files in `data/`. Everything else is generated.

| File | What goes in it |
|---|---|
| `data/teams.csv` | Yahoo team id ↔ team name ↔ manager (ids are stable; names can change) |
| `data/draft_2026.csv` | Yahoo draft results, one row per pick: `pick,player,nba_team,pos,team,price` |
| `data/transactions.csv` | in-season moves that change rights (see below) |
| `data/budget_trades.csv` | traded draft dollars: `date,from_team,to_team,amount,note` |
| `data/weeks_<season>.csv` | fantasy weeks from Yahoo: `week,start,end` |
| `data/matchups_<season>.csv` | the schedule: `week,team1,team2` with **Yahoo team ids** (see `teams.csv`), lower id first, sorted by week then team1 |
| `data/results_<season>.csv` | finished weeks: `week,team1,team2,cats1,cats2,ties` (team ids, lower id first; the three add up to 9) |
| `data/odds/<season>/<variant>/` | `week-NN.json`, `outlook.json`: team-level matchup odds and power rankings, one folder per projection variant (`blend` = average of ESPN and Yahoo, `espn`, `yahoo`), exported by the maintainer's h2hcats run (no player values). Don't edit by hand. A week's file is frozen once the week starts |

`transactions.csv` columns: `date,type,player,from_team,to_team,fab,note`, with `type` one of:

- `trade`: rights move `from_team` → `to_team`; keeper base unchanged
- `drop`: `from_team` releases the player (rights go back to the pool, base is kept)
- `add`: `to_team` picks the player up for `fab` dollars; base becomes max(draft price, FAB)

Examples:

```csv
date,type,player,from_team,to_team,fab,note
2026-11-02,trade,Dylan Harper,Gustava Soliņu Sildītāji,Hole of Fame,,for Mikal Bridges
2026-11-09,drop,LeBron James,Maris STOPIŅU TURTLES,,,
2026-11-12,add,LeBron James,,Dataigars,1,base stays $22 (draft price)
```

Team names must match `data/teams.csv` exactly, diacritics and quotes included. Then run:

```sh
python3 scripts/build.py        # regenerates rights.csv and KEEPERS.md; previews the site in _site/
```

It's Python 3, standard library only. The script checks the data and stops with an error on unknown
teams, double-drafted players, a trade/drop from a team that doesn't hold the player, a schedule where a team
plays twice (or not at all) in a week, rows not in lower-id-first order, a result that isn't in the schedule or
doesn't add up to 9 categories, or an odds file that doesn't match the schedule. Commit the
regenerated `rights.csv` and `KEEPERS.md` together with your data change. The website itself isn't
committed. The workflow `.github/workflows/pages.yml` runs `build.py --check` on every push and pull
request: it fails if the data is invalid or the committed files are stale, and otherwise deploys the site
(on `main` only). To preview the site locally, open `_site/index.html` (keeper rights) and `_site/odds.html`
(standings and odds).

## Hosting

The repo lives at https://github.com/Dziesma/fantasy-lombards. Pages is deployed by GitHub Actions
(Settings → Pages → Source: **GitHub Actions**). If a deploy ever fails, re-run it from Actions →
*build-and-deploy* → *Run workflow*. League members can be added as collaborators, or can open issues and
pull requests with corrections.
