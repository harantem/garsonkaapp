#!/usr/bin/env python3
"""
scrape.py — local listing scraper for nehnutelnosti.sk (Garsonka app).

Finds listings from search URLs and produces the rows `apartments` expects.
Plain python3, stdlib only — nothing to install.

    python3 scrape.py                        # both categories, with detail pages
    python3 scrape.py --category garsonka    # just the rentals
    python3 scrape.py --photos               # also mirror the cover photos locally
    python3 scrape.py --audit                # report where server logic loses data
    python3 scrape.py --limit 5 --no-detail  # smoke test

Writes into ./out/ :
    listings_<category>.json   the parsed rows
    insert_<category>.sql      insert … on conflict (id) do nothing

------------------------------------------------------------------------------
SERVER PARITY — read this before changing anything
------------------------------------------------------------------------------
Three fields are ALSO written by `supabase/functions/listing-photo/index.ts`,
which fires on every insert into `apartments` and overwrites whatever we put
there. For those three we deliberately reproduce the Edge Function's logic
byte-for-byte (see the `edge_*` functions) so that what lands in ./out/ is what
the database will actually hold:

    listed_at                    <- edge_find_listed_date
    energie, energies_included   <- edge_find_utilities
    cover photo bytes            <- edge_find_image_url  (--photos)

Those ports run on the RAW html, exactly as the function does — not on the
decoded flight JSON. If you change one side, change the other.

Every other column has no server counterpart, so it is read from the page's
real JSON instead (floor, lift, build_type, price, area, deposit, …).

`--audit` re-reads the same pages with the structured fields and reports where
the two disagree. It never changes the output — it only tells you what parity
costs. As of the last check the server's `findUtilities` tests free text across
the whole page before reading the structured `powerCosts`, so it can pick up a
neighbouring listing's image alt text; --audit is how you see that happening.
"""

import argparse, json, os, re, sys, time, urllib.error, urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
BASE = "https://www.nehnutelnosti.sk"

# Each category is one or more search URLs; results are merged and de-duped by id.
SEARCHES = {
    "garsonka": [
        f"{BASE}/vysledky/garsonky/bratislava-stare-mesto/prenajom",
        f"{BASE}/vysledky/1-izbove-byty/bratislava-stare-mesto/prenajom",
    ],
    "sale3i": [
        f"{BASE}/vysledky/predaj?locations=100012516&locations=100012515"
        f"&locations=100012521&categories=300001&categories=200000&areaFrom=70",
    ],
}

# category.subValue -> the `rooms` text already used in the table
ROOMS = {
    "STUDIO_APARTMENT": "Garsónka",
    "ONE_ROOM_APARTMENT": "1-izbový byt",
    "TWO_ROOM_APARTMENT": "2-izbový byt",
    "THREE_ROOM_APARTMENT": "3 izbový byt",
    "FOUR_ROOM_APARTMENT": "4-izbový byt",
    "FAMILY_HOUSE": "Rodinný dom",
}


# ============================================================== SERVER PARITY ==
# Verbatim ports of supabase/functions/listing-photo/index.ts. Same regexes, same
# precedence, same un-escaping, same order of tests. Operate on the RAW html.
# Do not "improve" these — their whole job is to agree with the deployed function.

def edge_find_image_url(html):
    """index.ts findImageUrl — cover image, slashes/ampersands un-escaped first
    or the signed query (?st=…&ts=…&e=0) breaks and the image server 403s."""
    norm = re.sub(r"\\u002[fF]", "/", html)
    norm = (norm.replace("\\u0026", "&")
                .replace("&amp;", "&")
                .replace("\\/", "/"))
    m = re.search(r'''https://img\.nehnutelnosti\.sk/foto/[^\s"'\\<>]*_fss\?[^\s"'\\<>]+''',
                  norm)
    return m.group(0) if m else None


def edge_find_listed_date(html):
    """index.ts findListedDate — "createdAt":"YYYY-MM-DD…", quotes un-escaped."""
    m = re.search(r'"createdAt"\s*:\s*"(\d{4}-\d{2}-\d{2})', html.replace('\\"', '"'))
    return m.group(1) if m else None


def edge_find_utilities(html):
    """index.ts findUtilities — returns None when nothing is stated, so a good
    value is never overwritten with null. NOTE the precedence is the function's:
    free text over the whole page is tested BEFORE structured powerCosts."""
    h = html.replace('\\"', '"')
    mn = re.search(r'"noteToPrice"\s*:\s*"([^"]{0,120})"', h)
    note = mn.group(1) if mn else ""

    if re.search(r"vr[aá]tane energi|s energiami|energie v cene|v cene[^.]{0,20}energi",
                 h, re.I) or re.search(r"vr[aá]tane|v cene", note, re.I):
        return {"energie": None, "energies_included": True}

    mp = re.search(r'"powerCosts"\s*:\s*\{\s*"value"\s*:\s*"([^"]+)"', h)
    pc = mp.group(1) if mp else ""
    n = re.search(r"(\d+)", pc)
    if not n and re.search(r"energi|pripočítava|poplatk", note, re.I):
        n = re.search(r"(\d{2,4})", note)
    if n:
        return {"energie": int(n.group(1)), "energies_included": False}
    return None
# ========================================================== end SERVER PARITY ==


# ---------------------------------------------------------------- fetch / parse

def fetch(url, tries=3, pause=2.0, referer=True):
    """GET with a real UA. Returns text, or None on 404/give-up."""
    for attempt in range(1, tries + 1):
        headers = {"User-Agent": UA,
                   "Accept": "text/html,application/xhtml+xml",
                   "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8"}
        if not referer:
            # index.ts: image fetch sends User-Agent only — a Referer triggers
            # the hot-link 403.
            headers = {"User-Agent": UA}
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # past the last page
            if attempt == tries:
                print(f"    ! HTTP {e.code} {url[:90]}", file=sys.stderr)
                return None
        except Exception as e:
            if attempt == tries:
                print(f"    ! {type(e).__name__} {url[:90]}", file=sys.stderr)
                return None
        time.sleep(pause * attempt)              # back off and retry
    return None


def fetch_text(url, **kw):
    b = fetch(url, **kw)
    return b.decode("utf-8", "replace") if b is not None else None


def flight(html):
    """Concatenate the Next.js App Router flight chunks into one searchable string."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\s*\]\)', html)
    out = []
    for c in chunks:
        try:
            out.append(json.loads(c))
        except ValueError:
            pass
    return "".join(out)


def balanced(s, start):
    """Slice the complete {...} / [...] beginning at s[start]. String-aware."""
    open_c = s[start]
    close_c = "}" if open_c == "{" else "]"
    depth = 0
    in_str = esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:            esc = False
            elif ch == "\\":   esc = True
            elif ch == '"':    in_str = False
        elif ch == '"':        in_str = True
        elif ch == open_c:     depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def objects_at(fl, key):
    """Every JSON object following `key` in the flight string that actually parses."""
    found = []
    for m in re.finditer(re.escape(key), fl):
        raw = balanced(fl, m.end() - 1)
        if not raw:
            continue
        try:
            found.append(json.loads(raw))
        except ValueError:
            pass
    return found


def ppm2_text(unit):
    """'19,57 €/m²/mes.' -> '19,57'.  Sale prices carry a thousands separator
    ('1 605,50 €/m²', sometimes a non-breaking space), so strip spaces rather
    than stopping at the first one. Kept as text with the Slovak decimal comma,
    like the existing rows."""
    if not unit:
        return None
    m = re.match(r"[\d\s\u00a0\u202f.,]+", str(unit))
    if not m:
        return None
    return re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).strip(".,") or None


def num(x):
    """First number in x, as int/float. Handles '19,57 €/m²/mes.' and '23'."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return x
    m = re.search(r"\d+(?:[.,]\d+)?", str(x))
    if not m:
        return None
    f = float(m.group(0).replace(",", "."))
    return int(f) if f.is_integer() else f


# ---------------------------------------------------------------- search pages

def parse_search(html):
    """-> (rows, total_count). Reads the `advertisements` block."""
    fl = flight(html)
    for d in objects_at(fl, '"advertisements":{'):
        if isinstance(d, dict) and isinstance(d.get("results"), list):
            rows = [r["advertisement"] for r in d["results"]
                    if isinstance(r.get("advertisement"), dict)
                    and r["advertisement"].get("id")]
            return rows, d.get("totalCount")
    return [], None


def row_from_search(a, category):
    p    = a.get("price") or {}
    par  = a.get("parameters") or {}
    loc  = a.get("location") or {}
    cat  = par.get("category") or {}
    pics = a.get("photos") or []
    addr = loc.get("name") or ""
    sef  = a.get("sefName") or ""
    ppm2 = p.get("unitPrice")                     # "19,57 €/m²/mes."
    area = num(par.get("area"))
    return {
        "id": a["id"],
        "title": a.get("title"),
        "address": addr,
        "street": addr.split(",")[0].strip() or None,
        "price": num(p.get("priceNum") or p.get("priceValue")),
        # column is `area int` — the site sometimes gives 33.6
        "area": round(area) if area is not None else None,
        "price_per_m2": ppm2_text(ppm2),
        "rooms": ROOMS.get(cat.get("subValue")) or cat.get("subValue"),
        "image": (pics[0].get("url") if pics and isinstance(pics[0], dict) else None),
        "url": f"{BASE}/detail/{a['id']}/{sef}" if sef else f"{BASE}/detail/{a['id']}",
        "category": category,
        # server-parity fields — set by the detail pass; this is only the fallback
        # used with --no-detail, where there is no detail page to read.
        "listed_at": (a.get("createdAt") or "")[:10] or None,
        "energie": None, "energies_included": None,
        # structured-only fields, no server counterpart
        "floor": None, "floor_num": None, "floor_total": None,
        "lift": None, "build_type": None,
        "deposit": None, "rk_fee": None, "has_ac": None,
        # not a DB column: the URL the Edge Function would download
        "_photo_url": None,
    }


def crawl_search(url, category, page_cap=40, pause=1.5):
    rows, seen, total = [], set(), None
    for page in range(1, page_cap + 1):
        u = url if page == 1 else url + ("&" if "?" in url else "?") + f"page={page}"
        html = fetch_text(u)
        if html is None:
            break
        batch, tc = parse_search(html)
        if tc is not None:
            total = tc
        fresh = [a for a in batch if a["id"] not in seen]
        if not fresh:
            break                                  # no new ids -> done
        for a in fresh:
            seen.add(a["id"])
            rows.append(row_from_search(a, category))
        print(f"    page {page}: +{len(fresh)} (running {len(rows)}"
              + (f"/{total}" if total else "") + ")")
        if total and len(rows) >= total:
            break
        time.sleep(pause)
    return rows


# ---------------------------------------------------------------- detail pages

def structured_params(html):
    """The detail page's real `parameters` JSON, for the columns the server
    does not touch (and for --audit)."""
    for d in objects_at(flight(html), '"parameters":{'):
        if isinstance(d, dict) and ("construction" in d or "transaction" in d):
            return d
    return None


def structured_utilities(par):
    """What utilities WOULD be, read from the structured fields. Used only by
    --audit — never written, so parity with the server is preserved."""
    price = (par or {}).get("price") or {}
    pc    = price.get("powerCosts") or {}
    note  = price.get("noteToPrice") or ""
    if pc.get("areIncluded") is True:
        return {"energie": None, "energies_included": True}
    if pc.get("value"):                  # "" means not stated
        return {"energie": num(pc["value"]), "energies_included": False}
    if re.search(r"vr[aá]tane energi|energie v cene|s energiami", note, re.I):
        return {"energie": None, "energies_included": True}
    return None


def parse_detail(html):
    """Server-parity fields from the ported extractors; everything else from the
    page's structured JSON."""
    out = {}

    # --- parity: exactly what listing-photo/index.ts would write ---------------
    d = edge_find_listed_date(html)
    if d:
        out["listed_at"] = d
    u = edge_find_utilities(html)
    if u:                                  # None -> leave alone, as the server does
        out["energie"] = u["energie"]
        out["energies_included"] = u["energies_included"]
    out["_photo_url"] = edge_find_image_url(html)

    # --- structured: columns with no server counterpart -----------------------
    par = structured_params(html)
    if not par:
        return out

    fn = num(par.get("floor")) if par.get("floor") is not None else None
    ft = num(par.get("numberOfFloors")) if par.get("numberOfFloors") is not None else None
    if fn is not None:
        out["floor_num"] = fn
        out["floor"] = f"{fn}/{ft}" if ft else str(fn)
    if ft is not None:
        out["floor_total"] = ft
    if isinstance(par.get("hasElevator"), bool):
        out["lift"] = par["hasElevator"]
    if par.get("construction"):
        out["build_type"] = par["construction"]

    note = ((par.get("price") or {}).get("noteToPrice")) or ""
    # "Depozit - 900 €". A bare "Depozit" label states nothing.
    m = re.search(r"[Dd]epozit\D{0,15}(\d[\d\s]{2,7})\s*€", note)
    if m:
        out["deposit"] = num(m.group(1).replace(" ", ""))
    m = re.search(r"[Pp]rov[íi]zia[^\d€]{0,20}((?:\d[\d\s]*\s*(?:€|%))|[^,;.]{0,30})", note)
    if m and m.group(1).strip():
        out["rk_fee"] = m.group(1).strip()[:60]

    attrs = par.get("attributes") or []
    blob  = " ".join(f"{a.get('label','')} {a.get('value','')}"
                     for a in attrs if isinstance(a, dict))
    if re.search(r"klimatiz", blob + " " + (par.get("title") or ""), re.I):
        out["has_ac"] = not re.search(r"[Kk]limatiz\w*\s*[:\-]?\s*Nie", blob)
    return out


def mirror_photo(row, photo_dir, pause):
    """Download the cover photo the way index.ts does — the URL its regex finds,
    User-Agent only, NO Referer — into photo_dir/<id>.webp, mirroring the
    `apartment-photos` bucket. Returns the function's own status string."""
    url = row.get("_photo_url")
    if not url:
        return "no-image"
    dest = os.path.join(photo_dir, row["id"] + ".webp")
    if os.path.exists(dest):
        return "exists"
    b = fetch(url, referer=False)
    if b is None:
        return "img-failed"
    open(dest, "wb").write(b)
    time.sleep(pause)
    return f"saved {len(b)//1024}kB"


# ---------------------------------------------------------------- output

def sql_lit(v):
    if v is None:                   return "null"
    if isinstance(v, bool):         return "true" if v else "false"
    if isinstance(v, (int, float)): return str(v)
    return "'" + str(v).replace("'", "''") + "'"


COLS = ["id", "title", "address", "street", "price", "energie", "energies_included",
        "price_per_m2", "area", "floor", "floor_num", "floor_total", "lift",
        "build_type", "rooms", "image", "url", "category", "listed_at",
        "deposit", "rk_fee", "has_ac"]


def write_sql(rows, path, category):
    lines = [
        f"-- {len(rows)} {category} listings scraped {time.strftime('%Y-%m-%d %H:%M')}",
        "-- Generated by scrape.py. Safe to re-run: 'do nothing' keeps your",
        "-- saved/rejected decisions. Run category_setup.sql first.",
        "--",
        "-- listed_at / energie / energies_included match what the listing-photo",
        "-- Edge Function writes, so the insert webhook will not change them.",
        "",
        f"insert into public.apartments ({','.join(COLS)}) values",
    ]
    lines += ["  (" + ",".join(sql_lit(r.get(c)) for c in COLS) + ")"
              + ("," if i < len(rows) - 1 else "")
              for i, r in enumerate(rows)]
    lines += ["on conflict (id) do nothing;", ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=["garsonka", "sale3i", "all"], default="all")
    ap.add_argument("--no-detail", action="store_true",
                    help="skip detail pages (no floor/lift/utilities)")
    ap.add_argument("--photos", action="store_true",
                    help="mirror cover photos into --photo-dir like the Edge Function")
    ap.add_argument("--photo-dir", default="photos")
    ap.add_argument("--audit", action="store_true",
                    help="report where server logic disagrees with the structured "
                         "fields (does not change the output)")
    ap.add_argument("--limit", type=int, help="cap listings per category (testing)")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    if args.photos:
        os.makedirs(args.photo_dir, exist_ok=True)
    cats = ["garsonka", "sale3i"] if args.category == "all" else [args.category]

    for cat in cats:
        print(f"\n=== {cat} ===")
        rows, seen = [], set()
        for url in SEARCHES[cat]:
            print(f"  {url}")
            for r in crawl_search(url, cat, pause=args.pause):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    rows.append(r)
        if args.limit:
            rows = rows[:args.limit]
        print(f"  {len(rows)} listings from search")

        audit = []
        if not args.no_detail and rows:
            print(f"  detail pages (pause {args.pause}s)…")
            for i, r in enumerate(rows, 1):
                html = fetch_text(r["url"])
                if not html:
                    print(f"    [{i}/{len(rows)}] {r['id']} FAILED")
                    continue
                r.update(parse_detail(html))
                note = ""
                if args.audit:
                    srv = ({"energie": r["energie"],
                            "energies_included": r["energies_included"]}
                           if r["energies_included"] is not None else None)
                    st = structured_utilities(structured_params(html))
                    if srv != st:
                        audit.append((r["id"], srv, st))
                        note = f"  ~ audit: server={srv} structured={st}"
                if args.photos:
                    note = "  photo: " + mirror_photo(r, args.photo_dir, args.pause) + note
                print(f"    [{i}/{len(rows)}] {r['id']} ok{note}")
                if i < len(rows):
                    time.sleep(args.pause)

        for r in rows:
            r.pop("_photo_url", None)

        jp = os.path.join(args.out, f"listings_{cat}.json")
        sp = os.path.join(args.out, f"insert_{cat}.sql")
        json.dump({"source": SEARCHES[cat], "scrapedAt": time.strftime("%Y-%m-%d"),
                   "count": len(rows), "listings": rows},
                  open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_sql(rows, sp, cat)

        have = lambda k: sum(1 for r in rows if r.get(k) is not None)
        print(f"  -> {jp}\n  -> {sp}")
        print(f"     price {have('price')}/{len(rows)}  area {have('area')}/{len(rows)}  "
              f"floor {have('floor')}/{len(rows)}  lift {have('lift')}/{len(rows)}  "
              f"energie {have('energies_included')}/{len(rows)}")
        if args.audit:
            inc = sum(1 for _, s, t in audit
                      if s and s.get("energies_included") and t
                      and not t.get("energies_included"))
            print(f"     audit: {len(audit)}/{len(rows)} utilities differ from "
                  f"structured; {inc} where the server says 'included' but the "
                  f"listing states a monthly amount")


if __name__ == "__main__":
    main()
