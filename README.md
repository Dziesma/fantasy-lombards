# Fantasy Lombards

The keeper-rights tracker for our 16-team Yahoo NBA keeper league. Think of it as a pawnshop: every player
bought at the auction can be bought back next season, with interest. For every player drafted (or picked
up), it shows:

- what was paid for them in the 2026-27 auction (or FAB),
- what keeping them costs in 2027-28, 2028-29 and 2029-30,
- which team holds their keeper rights right now.

**Where to look**

- **[KEEPERS.md](KEEPERS.md)**: tables per team plus an A–Z list (renders on GitHub).
- **Website**: searchable and sortable, with a team filter. GitHub Actions rebuilds and deploys it on every
  push to `main`, at `https://<user>.github.io/fantasy-lombards/`.
- **[rights.csv](rights.csv)**: the same data for spreadsheets.

> **Status:** the 2026 draft log is still incomplete (130 of 208 picks). The remaining picks will be added.

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
| `data/teams.csv` | team name ↔ manager |
| `data/draft_2026.csv` | one row per auction pick: `pick,player,pos,team,price` |
| `data/transactions.csv` | in-season moves that change rights (see below) |
| `data/budget_trades.csv` | traded draft dollars: `date,from_team,to_team,amount,note` |

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
teams, double-drafted players, or a trade/drop from a team that doesn't hold the player. Commit the
regenerated `rights.csv` and `KEEPERS.md` together with your data change. The website itself isn't
committed. The workflow `.github/workflows/pages.yml` runs `build.py --check` on every push and pull
request: it fails if the data is invalid or the committed files are stale, and otherwise deploys the site
(on `main` only). To preview the site locally, open `_site/index.html`.

## Hosting on GitHub

1. Create an empty repo named `fantasy-lombards` on GitHub, then:
   `git remote add origin git@github.com:<user>/fantasy-lombards.git && git push -u origin main`
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**. Then re-run the workflow
   (Actions tab → *build-and-deploy* → *Run workflow*) if the first push ran before Pages was enabled.
3. Optionally, add league members as collaborators so they can open PRs with corrections.
