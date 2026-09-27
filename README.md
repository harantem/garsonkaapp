# Garsónka app

A single-file apartment tracker for Bratislava listings scraped from
[nehnutelnosti.sk](https://www.nehnutelnosti.sk) and [bezrealitky.sk](https://www.bezrealitky.sk).
Browse, save, reject with a reason, and let it learn which locations to auto-reject. Decisions sync to Supabase so the
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
| Area | any | ≥ 70 m² (≥ 65 m² on bezrealitky) |
| Locations | Staré Mesto (15-min walkable set) | Devínska Nová Ves, Vajnory, Záhorská Bystrica |
| Prices | €/month | full asking price |
| Sources | nehnutelnosti.sk | nehnutelnosti.sk + bezrealitky.sk (`br-` id prefix) |

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

**`scrape.py`** turns a nehnutelnosti.sk or bezrealitky.sk search into ready-to-run SQL.
Plain `python3`, stdlib only — nothing to install.

```bash
python3 scrape.py                        # both categories, both sites, with detail pages
python3 scrape.py --category sale3i      # just the sale listings
python3 scrape.py --source bezrealitky   # just the owner-direct listings
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
| `--source` | `all` | `nehnutelnosti`, `bezrealitky`, or `all` — crawl one site's searches only |
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
tracked. Each URL is dispatched to a parser by host, so the two sites can sit in the same
category list.

- **`garsonka`** — two nehnutelnosti searches (garsónky + 1-izbové, Staré Mesto,
  prenájom), merged and de-duped by id.
- **`sale3i`** — four searches over the same three districts:
  - nehnutelnosti: DNV / Vajnory / Záhorská Bystrica, 3-izbové + domy, from 70 m².
  - bezrealitky: one per district (`regionOsmIds=R2190578` Vajnory, `R2208779` DNV,
    `R2208773` Záhorská Bystrica), `DISP_3_IZB` + `estateType=BYT` + `PRODEJ`, from
    **65 m²** — deliberately below the other source's 70, because owner-direct stock
    here is thin enough that a flat missing the cut by one square metre is worth
    seeing. Owner-direct means these are flats the nehnutelnosti search cannot see
    at all.

Copying a bezrealitky search out of the browser gets you two extras that the script
**drops on purpose**: a `boundaryPoints` polygon and a `#lat/lng/zoom` fragment. Both are
map-viewport state — the region ids already fix the search area, each district returns the
same listings without the polygon, and a fragment would end up after the `&page=N` the
crawler appends. `osm_value` is decorative too; `regionOsmIds` is what the site filters on.

Pagination is automatic (`&page=N` on both sites), stopping when a page returns no new ids
or the site's own reported total is reached.

These three districts are small and owner-direct sale ads are rare, so expect a handful of
rows or none at all — the last run returned **2**, both in DNV. That is the search being
honest, not the parser failing: at the time of writing bezrealitky had *zero* sale listings
of any kind in Vajnory, and one non-3-izbový flat in Záhorská Bystrica. `--source
bezrealitky --no-detail` takes seconds if you want to re-check.

### How it parses

Both sites are Next.js apps, and neither is scraped by regexing markup — the script reads
the real JSON the page shipped, so an unrelated markup change won't quietly corrupt a
field.

**nehnutelnosti.sk** is the App Router: listing data arrives as flight chunks in
`self.__next_f.push([1,"…"])`, which the script concatenates and then slices balanced JSON
objects out of.

**bezrealitky.sk** is the Pages Router: everything sits in one
`<script id="__NEXT_DATA__">` blob. Search pages give an Apollo cache of thin `Advert`
objects — `br_parse_search` matches the `listAdverts(…)` cache key exactly, because the
same cache also holds `listSimilarAdverts` (near-misses from *other* districts, shown as
suggestions) and a `discountedOnly` teaser; taking either would smuggle in listings the
search never matched. Detail pages carry the whole listing as `pageProps.origAdvert`.

- **Search pages** carry id, title, address, street, price, area, €/m², image and rooms.
- **Detail pages** add floor / `floor_num` / `floor_total`, lift, `build_type`,
  `deposit`, `rk_fee`, `has_ac` — plus the three parity fields below.

Three bezrealitky quirks worth knowing, all handled in `br_*`:

- There is no title field; `imageAltText` ("Predaj bytu 3-izbový 70 m², Eisnerova, …") is
  what the site itself puts in the card heading, so that becomes `title`.
- `floor` is an **enum** (`GROUND` / `MIDDLE` / …). The number is `etage`, and
  `totalFloors` completes the `7/8` text.
- No €/m² is published, so `br_ppm2` divides and formats it the same way the
  nehnutelnosti column reads (Slovak decimal comma, no thousands separator).

`disposition` and `construction` are mapped to the wording already in the table
(`DISP_3_IZB` → `3 izbový byt`, `PANEL`/`BRICK`/`MIXED`/`SKELET` →
`Panelová`/`Tehlová`/`Zmiešaná`/`Skeletová`). Only values actually seen in the data are
mapped; anything new passes through raw, so an unknown enum shows up in the column rather
than silently becoming null.

**`listed_at` is null for every bezrealitky row, and cannot be fixed by parsing harder** —
the site publishes no post date anywhere, on the search page or the detail page. The only
date on the page is `availableFrom`, which is a different thing and would misreport market
age. Null reads as "unknown" in the app; day zero would have read as "listed today".

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

bezrealitky ids are plain numbers (`1062799`), so they get a **`br-`** prefix —
`br-1062799`. Nothing in the app parses an id, but the prefix keeps the two sites from ever
colliding on the primary key and makes the source of a row obvious in the table. De-duping
happens on the prefixed id, so it is per-site by construction.

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

The webhook fires on every insert whatever site the row's `url` points at, so the same
three ports also run over bezrealitky pages. There they normally match nothing — no
`createdAt`, no `powerCosts`, no `img.nehnutelnosti.sk` URL — but `findUtilities` also
tests free text, and a description saying "vrátane energií" **does** trip it. So the ports
run rather than being assumed away; only when they come back empty does the bezrealitky
parser use the structured `charges` (0 there means "not stated", not "free").

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

**bezrealitky rows get no photo from the webhook at all.** `findImageUrl` only matches
`img.nehnutelnosti.sk`, so the bucket stays empty for them and the card renders with no
image — and the app never falls back to the `image` column. `--photos` mirrors the site's
own cover instead and marks it `local-only`; those bytes only reach the app once
`upload_photos.command` has pushed `photos/` into the bucket:

```
[1/1] br-1062799 ok  photo: saved 147kB local-only
   1 covers are local-only (bezrealitky): the insert webhook cannot fetch them, so run
   upload_photos.command to get them into the bucket
```

The file keeps the `.webp` name the app asks for even though bezrealitky serves JPEG —
`<img>` sniffs the bytes, so it renders either way. To make the webhook handle these too,
widen `findImageUrl` to accept `api.bezrealitky.cz/media/cache/…` (those URLs are neither
signed nor hot-link protected, so it is a one-line change) and redeploy.

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
