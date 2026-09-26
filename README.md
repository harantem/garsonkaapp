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
python3 scrape.py --photos --audit       # mirror photos, report parity losses
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
| `--photos` | off | mirror cover photos into `--photo-dir`, like the Edge Function |
| `--photo-dir` | `photos` | where `--photos` writes |
| `--audit` | off | report where server-parity logic loses data (output unchanged) |
| `--limit N` | — | cap listings per category, for testing |
| `--pause` | `1.5` | seconds between requests |
| `--out` | `out` | output directory |

`out/` is gitignored, along with `photos/` — both are regenerated output, never the source
of truth.

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
`self.__next_f.push([1,"…"])`. For most columns the script concatenates those chunks and
reads the real JSON out of them rather than regexing markup — so an unrelated markup
change won't quietly corrupt a field.

- **Search pages** carry id, title, address, street, price, area, €/m², image and rooms.
- **Detail pages** add floor / `floor_num` / `floor_total`, lift, `build_type`,
  `deposit`, `rk_fee`, `has_ac` — plus the three parity fields below.

`--no-detail` skips that second pass. Much faster, but those fields come back null and
`listed_at` falls back to the search page's `createdAt`.

`deposit` and `rk_fee` come back mostly null, and that is the site's doing, not a parsing
bug: listings print a bare `Depozit` / `Provízia RK` label with no figure next to it. Last
full run: `deposit` 0 of 230, `rk_fee` 4 of 230. Treat both as hand-filled fields, the way
`supabase_extras.sql` does.

Each category ends with a coverage line — `price 163/181  floor 48/181  lift 181/181 …`.
Worth a glance: a sudden drop usually means the site changed shape. (`floor` really is
sparse on houses; `lift` is always stated.)

The listing **id** is the path segment in the detail URL and the table's primary key:
`nehnutelnosti.sk/detail/`**`JuRgfzENSJF`**`/prenajom-samostatnej-…`

### Server parity — three fields are deliberately not parsed the clean way

`listing-photo` fires on every insert and **overwrites** three fields. So for those, the
script reproduces that function's logic byte-for-byte instead of doing something better —
which makes what lands in `out/` what the table will actually hold:

| Field | In `scrape.py` | Ported from `index.ts` |
|---|---|---|
| `listed_at` | `edge_find_listed_date` | `findListedDate` |
| `energie`, `energies_included` | `edge_find_utilities` | `findUtilities` |
| cover photo bytes (`--photos`) | `edge_find_image_url` | `findImageUrl` |

They sit in a fenced `SERVER PARITY` block and run on the **raw HTML**, exactly as the
Edge Function does — same regexes, same precedence, same un-escaping. **Change one side
and you must change the other**, or inserts start mutating rows again.

**That precedence is the function's, and it is not the safe one.** `findUtilities` tests
free text across the whole page *before* reading the structured `powerCosts`, so it can
match a neighbouring listing's image `alt` text in the recommended-listings carousel:

```html
<img alt="PRENÁJOM ZARIADENEJ GARSÓNKY … za 600 EUR/mes. vrátane energií">
```

It then writes `energies_included = true, energie = null` for flats that *do* state a
monthly amount. On the last full run that was **6 of 49 rentals**, charging 100–250 €/mo
on top of rent — and those feed `totalPrice()` and the 🔥 deal badge, so the flat reads
as cheaper than it is. Sale listings are barely affected; utilities rarely appear on a
sale ad.

`--audit` shows you exactly where. It re-reads the same pages with the structured fields
and reports every divergence **without changing the output**:

```
[1/49] JuVMcU2QNyi ok  ~ audit: server={'energie': None, 'energies_included': True} structured={'energie': 200, 'energies_included': False}
audit: 10/49 utilities differ from structured; 6 where the server says 'included' but the listing states a monthly amount
```

To fix it for real: invert the precedence in `findUtilities` (read `powerCosts.areIncluded`
and `value` first, and scope the text fallback to `noteToPrice` instead of the whole page),
redeploy, then mirror the change in `scrape.py` so the two stay in step.

### What still fills itself in

The **`listing-photo`** Edge Function fires on every insert and fetches the cover photo
**server-side** into the `apartment-photos/<id>.webp` bucket. That can't be replaced by a
URL in the insert: nehnutelnosti images are CORS-locked and hot-link protected, and the
signed URLs in the `image` column carry a `ts=` and expire. Setup lives in
[DEPLOY-photos.md](DEPLOY-photos.md).

On each insert it also re-reads `listed_at` and utilities and writes them back — always,
not only when they are missing. Thanks to the parity above those writes are no-ops, so the
rows you inserted stay as you inserted them.

`--photos` mirrors the same bytes locally into `photos/`: the URL the function's own regex
finds, fetched with a User-Agent and **no Referer** (a Referer trips the hot-link 403).
Handy for seeing what the bucket will get, and `index.html` falls back to
`photos/<id>.webp` whenever Storage has no image.

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
