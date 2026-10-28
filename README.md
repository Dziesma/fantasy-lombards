# Fantasy Lombards

The site of our 16-team Yahoo NBA keeper league, at **https://dziesma.github.io/fantasy-lombards/**:

- **Week** (`index.html`, the front page): every week's projected matchup odds and power ranking, a head-to-head
  matrix of every team against every other (the odds; a finished week's, who'd have won with the final totals), and
  the season's power ranking (roster strength), by Yahoo's projections (Rotowire's, the default), ESPN's or their
  average. Each matchup is a head to head: the lock's favourite on the left in orange, its underdog on the right in
  slate, the tie between, then the lock's odds, the expected categories and the starter games; a finished week shows
  Yahoo's result (categories won–lost–tied) and outlines an upset (the lock's underdog won) in slate, a tie in grey.
  Its details: every category's stats so far and projected (FG% and FT% with makes and attempts) and odds, mirrored.
  Once the week has locked (live or finished), each category opens to both teams' starters, mirrored, a bar each on
  one scale: so far (solid), projected now (light, to the bar's end) and projected at the lock (a tick); FG% and FT%
  as makes above the matchup's combined percentage, so a team's starters add up to above 0 exactly when it's ahead. (`odds.html`, its old address, sends you there.)
- **Standings** (`standings.html`): Yahoo's One-Win standings.
- **Keeper rights** (`keepers.html`): think of it as a pawnshop: every player bought can be bought back next season,
  with interest. For every player drafted or picked up: what was paid for him this season, what keeping him costs
  the next three seasons, and which team holds his rights now. Searchable, sortable, filterable by team; also as
  `rights.csv`.
- **Vaimanieki** (`vaimanieki.html`): who has the most to wail about. The dollars each team has on players Yahoo
  flags as out (`O`) right now, against all its players' dollars, and every injured player worth at least $1 (25 a page). A
  player's dollars are his keeper base; only players whose rights a team holds count.

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

`data/yahoo/` has only what the site shows: the players drafted or in a transaction (name, NBA team, positions,
Yahoo's injury flag), when each table was last fetched,
picks and transactions by ids, the weeks and pairings with Yahoo's scores (categories won), Yahoo's W-L-T, and per sim (each projection source, each
week) the pairings' odds and each team's projected category totals, and of the live sims every pair of teams' odds
(`h2h.csv`; yfbb's sim writes it since it was added there), and once a week's games are being played each team's
starter stats so far and its projected week totals, makes and attempts included (`totals.csv`, summed from the live
sim's player games), and of each locked week every starter's: projected at the lock, so far and projected now
(`players_week.csv`, from the frozen and live sims' player games).

Each week has two sims. Live: what is known now; before the week's lineup lock (Monday; weeks 7 and 17 have a
second, on their middle Monday) each team's best lineup, projected; after it the lineups that locked, the games played
so far as played and only the rest projected, so once the week is over it's the result. Frozen: the odds at the lock,
the lineups that locked and the projections of then. The odds page shows live, each bar marked with the shift since
the lock and each team's lock line (per matchup and per category).

## Updating

The maintainer updates the site by hand, from yfbb's data (yfbb fetches from Yahoo as the maintainer, so it can't
run on GitHub). Everything happens on `main`.

**When.** At least twice a week, around the Monday lineup lock:

| When | Why |
|---|---|
| Sunday or Monday, before the first game | fresh projections, injuries and rosters for the coming week's live odds |
| Monday night or Tuesday, after the lock | records the lineups that locked; the week's odds freeze at the lock |
| any other time (after a waiver run: Thursday, Sunday) | new transactions on the keeper rights, new injuries on Vaimanieki |

**Steps.**

```sh
# 1. yfbb: fetch from Yahoo, ESPN and the NBA; rebuild the curated data and the sims
cd ~/workspace/yfbb
uv run yfbb data sync
uv run yfbb sim

# 2. this repo: take what the site shows, validate and build
cd ~/workspace/fantasy-lombards
python3 scripts/import.py   # yfbb's data -> data/yahoo/ (finds it through yfbb's config; --data DIR otherwise)
python3 scripts/build.py    # validates everything, builds the site in _site/

# 3. check the preview: _site/index.html, standings.html, keepers.html, vaimanieki.html (e.g. xdg-open _site/index.html)

# 4. publish: the push makes GitHub Actions build and deploy the site (about a minute)
git add data && git commit -m "Update $(date +%F)" && git push
```

**Warnings and errors.**

- `yfbb data sync` failing (Yahoo session expired, a page that changed): fix it in yfbb first; don't import half a
  sync.
- `import.py` warns when a team's Yahoo name isn't its name in `data/league/teams.csv`: a GM renamed their team. Take
  the new name into `teams.csv`, or set that team's `own_name` to 1 to keep the site's.
- `build.py` (Python 3, standard library only) stops with an error on anything inconsistent: unknown team ids, a
  player drafted twice, a drop by a team without his rights or an add of a player still owned, a transaction it has
  no rule for yet (trades), a week without every team exactly once, odds of a pairing not in the schedule, a budget
  over the cap, a correction for an undrafted player, a keeper price rule that doesn't give the league's examples.
  Nothing is published until it passes. It warns about a correction Yahoo no longer needs (delete that row).

**The hand-kept files**, edited whenever the league agrees on something Yahoo doesn't record, then built and pushed
like any update:

- `data/league/budget_trades.csv`: a trade of next season's draft dollars (team ids, amount)
- `data/league/draft_corrections.csv`: a draft price Yahoo has wrong
- `data/league/teams.csv`: a new manager, or a team's name on the site

## Hosting

GitHub Actions (`.github/workflows/pages.yml`) builds the site on every push and pull request, and deploys it on
`main` (Settings → Pages → Source: **GitHub Actions**). The site itself isn't committed. If a deploy fails, re-run it
from Actions → *build-and-deploy* → *Run workflow*.
