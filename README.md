# Garsónka app

A single-file apartment tracker for Bratislava listings scraped from
[nehnutelnosti.sk](https://www.nehnutelnosti.sk). Browse, save, reject with a reason,
and let it learn which locations to auto-reject. Decisions sync to Supabase so the
phone and the laptop stay in step.

Everything lives in **`index.html`** — no build step, no framework, no `package.json`.
Leaflet, the Supabase client and Inter are pulled from CDNs at runtime.

---

## Run it locally

```bash
python3 -m http.server 8000
```

Open **http://localhost:8000**. Edit `index.html`, refresh — that's the whole loop.
`npx serve .` or `php -S localhost:8000` work just as well.

**Serve it over HTTP; don't double-click the file.** Opening `index.html` directly gives
the page a `null` origin, which blocks the Supabase connection and silently drops you
into local-only mode.

### Offline / safe mode

Running it locally connects to the **production** Supabase. That's read-mostly, but
`applyLearned()` can auto-reject matching listings and opening the Stats tab writes a
daily snapshot — real writes to the real table.

To poke at the UI without touching production, blank the URL near the top of the script:

```js
const SUPABASE_URL      = "";
```

The app falls back to the 20 listings embedded in the file and saves only to
`localStorage`. Don't commit that line.

---

## The category toggle

The header has a segmented switch between two listing sets:

| | **Garsónky** | **3-izbové + domy** |
|---|---|---|
| `category` | `garsonka` | `sale3i` |
| Deal | Prenájom (rent) | Predaj (sale) |
| Type | Garsónka / 1-izbový | 3-izbový byt + Rodinný dom |
| Area | any | ≥ 70 m² |
| Locations | Staré Mesto (15-min walkable set) | Devínska Nová Ves, Vajnory, Záhorská Bystrica |
| Prices | €/month | full asking price |

Both sets live in the same `apartments` table, told apart by the `category` column.
Selection persists in `localStorage`.

What's scoped per category, automatically: counts, €/m² benchmarks and 🔥 deal badges,
statistics, price-history snapshots, the street filter, saved filters and presets, the
archive, and the learned auto-reject rules. A 3-izbák is never benchmarked against
studio rents.

Sale listings skip the walkable-area filter (those districts are nowhere near the Staré
Mesto whitelist) and hide the sidebar isochrone map. Their cards show an asking price and
a building type instead of rent + utilities.

To add a third set, add an entry to the `CATEGORIES` object in `index.html` and insert
rows with that `category` value. Nothing else needs to change.

---

## Adding listings (scraping)

**`scrape.py`** turns a nehnutelnosti.sk search into ready-to-run SQL. Plain `python3`,
stdlib only — nothing to install.

```bash
python3 scrape.py                        # both categories, with detail pages
python3 scrape.py --category sale3i      # just the sale listings
python3 scrape.py --limit 5 --no-detail  # smoke test
```

It writes into `out/`:

| File | Contents |
|---|---|
| `listings_<category>.json` | the parsed rows, plus `source` / `scrapedAt` / `count` |
| `insert_<category>.sql` | `insert into public.apartments … on conflict (id) do nothing` |

Paste the `.sql` into the Supabase SQL editor. `do nothing` means a re-run never clobbers
your saved/rejected decisions. **Run `category_setup.sql` first** — the insert writes a
`category` column.

| Flag | Default | Effect |
|---|---|---|
| `--category` | `all` | `garsonka`, `sale3i`, or `all` |
| `--no-detail` | off | search pages only — fast, but fewer fields |
| `--limit N` | — | cap listings per category, for testing |
| `--pause` | `1.5` | seconds between requests |
| `--out` | `out` | output directory |

`out/` is not in `.gitignore` — it holds generated data, so don't commit it unless you
mean to.

### The search URLs

Baked into the `SEARCHES` dict at the top of the script; edit there to change what gets
tracked.

- **`garsonka`** — two searches (garsónky + 1-izbové, Staré Mesto, prenájom), merged and
  de-duped by id.
- **`sale3i`** — the sale search: DNV / Vajnory / Záhorská Bystrica, 3-izbové + domy,
  from 70 m².

Pagination is automatic (`&page=N`), stopping when a page returns no new ids or the
site's own reported total is reached.

### How it parses

The site is a Next.js App Router app: listing data arrives as flight chunks in
`self.__next_f.push([1,"…"])`. The script concatenates the chunks and reads real JSON out
of them rather than regexing the HTML — so an unrelated markup change won't quietly
corrupt a field.

- **Search pages** carry id, title, address, street, price, area, €/m², image,
  `listed_at` and rooms.
- **Detail pages** add floor / `floor_num` / `floor_total`, lift, `build_type`,
  `energie` + `energies_included`, `deposit`, `rk_fee` and `has_ac`.

`--no-detail` skips that second pass — much faster, but those fields come back null.

Structured fields win over prose: utilities come from `powerCosts`, with `noteToPrice`
only as a fallback, so a stated value never gets overwritten by a guess.

Each category ends with a coverage line — `price 181/181  floor 174/181  lift 168/181 …`.
Worth a glance: a sudden drop usually means the site changed shape.

The listing **id** is the path segment in the detail URL and the table's primary key:
`nehnutelnosti.sk/detail/`**`JuRgfzENSJF`**`/prenajom-samostatnej-…`

### What still fills itself in

The **`listing-photo`** Edge Function fires on every insert and fetches the cover photo
**server-side** into the `apartment-photos/<id>.webp` bucket. That part can't move into
`scrape.py`'s output: nehnutelnosti images are CORS-locked and hot-link protected, so the
browser can't load them directly. It also backfills `listed_at` and utilities for any row
that arrived without them. Setup lives in [DEPLOY-photos.md](DEPLOY-photos.md).

Backfill rows that predate the webhook:

```bash
curl -X POST https://nfqmwccfeahkpuznkbla.supabase.co/functions/v1/listing-photo \
  -H "Content-Type: application/json" -d '{"backfill":true}'
```

Safe to re-run — it skips rows that are already complete.

### Scrape politely

Requests are sequential, with a real User-Agent and a 1.5s pause. Raise `--pause` rather
than lowering it, and don't parallelise a few hundred detail-page fetches.

---

## SQL files

Run these in the Supabase SQL editor. All are safe to re-run.

| File | What it does |
|---|---|
| `supabase_setup.sql` | Creates `apartments`, RLS policies, seeds the original 20 rentals |
| `supabase_extras.sql` | Adds `deposit`, `rk_fee`, `has_ac`, `scraped_at` |
| `category_setup.sql` | **Adds `category` to `apartments` and `stats_snapshots`** — needed for the header toggle |
| `stats_setup.sql` | `stats_snapshots` table for the price-history chart |
| `storage_setup.sql` | Creates the public `apartment-photos` bucket |
| `storage_lockdown.sql` | Tightens the bucket to read-only for the anon key |
| `photo_webhook.sql` | Insert webhook that calls the `listing-photo` function |

Until `category_setup.sql` has run, every row reads as `garsonka` and the app behaves
exactly as it did before the toggle existed — the sale tab is just empty.

### Manual photo path (legacy)

`download_photos.command` and `upload_photos.command` predate the Edge Function.
They're a generated list of `curl` calls against signed image URLs, which expire —
regenerate them from `_photo_urls.json` if you ever need them. The webhook is the
supported path.

---

## Notes

- **Editing is locked by default.** The app is view-only until you enter the password
  (header button, or the Profile tab on mobile); it unlocks for an hour and re-locks on
  reload. Hash is in `index.html`; there's no account system.
- **The Supabase key in the repo is the publishable (anon) key.** Row-level security is
  what protects the data, not the key. Don't put the service-role key in this file.
- **Auto-reject learns from your reasons.** A word counts as a location only if it
  appears in both your rejection reason and the listing's own title/address — so
  "too far, Blumentál" teaches it `blumental`, while "too small" teaches it nothing.
  Auto-rejections are prefixed 🤖 and never learned from. Clear one via the × on its
  chip.
- `photos/` is the local fallback for cover images when Storage doesn't have them.
