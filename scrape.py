#!/usr/bin/env python3
"""
scrape.py — local listing scraper for nehnutelnosti.sk + bezrealitky.sk (Garsonka app).

Finds listings from search URLs and produces the rows `apartments` expects.
Plain python3, stdlib only — nothing to install.

    python3 scrape.py                        # both categories, with detail pages
    python3 scrape.py --category garsonka    # just the rentals
    python3 scrape.py --photos               # also mirror the cover photos locally
    python3 scrape.py --audit                # report where server logic loses data
    python3 scrape.py --limit 5 --no-detail  # smoke test

Each search URL is dispatched by host (see SOURCES): nehnutelnosti.sk data comes
out of Next.js App Router flight chunks, bezrealitky.sk out of the Pages Router
`__NEXT_DATA__` blob and its Apollo cache. Rows from the two sites land in the
same category and are told apart by the `br-` id prefix.

SEARCHES currently lists nehnutelnosti.sk URLs only — `sale3i` was cut back to the
single nehnutelnosti search. The bezrealitky reader below is kept intact, so adding
a bezrealitky.sk URL back to SEARCHES is all it takes to turn that source on again;
until then `--source bezrealitky` matches nothing and yields no rows.

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

The webhook fires on EVERY insert, whatever site the row's `url` points at, so
the same three ports also run over bezrealitky pages. There they normally match
nothing — no `createdAt`, no `powerCosts`, no img.nehnutelnosti.sk URL — but
`findUtilities` also tests free text, and a description saying "vrátane energií"
does trip it. Hence: run the ports, don't assume. The one place the function
genuinely cannot help is the cover photo, so `--photos` falls back to the site's
own image URL for those rows — see `mirror_photo`.

Every other column has no server counterpart, so it is read from the page's
real JSON instead (floor, lift, build_type, price, area, deposit, …).

`--audit` re-reads the same pages with the structured fields and reports where
the two disagree. It never changes the output — it only tells you what parity
costs. As of the last check the server's `findUtilities` tests free text across
the whole page before reading the structured `powerCosts`, so it can pick up a
neighbouring listing's image alt text; --audit is how you see that happening.
"""

import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
BASE = "https://www.nehnutelnosti.sk"
BR   = "https://www.bezrealitky.sk"
BR_ID = "br-"          # id prefix, so the two sites cannot collide on the PK

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


# ---------------------------------------------- nehnutelnosti.sk: search pages

def nh_parse_search(html):
    """-> (rows, total_count). Reads the `advertisements` block."""
    fl = flight(html)
    for d in objects_at(fl, '"advertisements":{'):
        if isinstance(d, dict) and isinstance(d.get("results"), list):
            rows = [r["advertisement"] for r in d["results"]
                    if isinstance(r.get("advertisement"), dict)
                    and r["advertisement"].get("id")]
            return rows, d.get("totalCount")
    return [], None


def nh_row_from_search(a, category):
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



# ---------------------------------------------- nehnutelnosti.sk: detail pages

def nh_structured_params(html):
    """The detail page's real `parameters` JSON, for the columns the server
    does not touch (and for --audit)."""
    for d in objects_at(flight(html), '"parameters":{'):
        if isinstance(d, dict) and ("construction" in d or "transaction" in d):
            return d
    return None


def nh_structured_utilities(par):
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


def nh_parse_detail(html):
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
    par = nh_structured_params(html)
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


# -------------------------------------------------------------- bezrealitky.sk
# A different site and a different Next.js: the Pages Router, so everything the
# page rendered sits in one <script id="__NEXT_DATA__"> blob rather than in flight
# chunks. Search pages hand us an Apollo cache of thin `Advert` objects; the detail
# page hands us the whole listing as `pageProps.origAdvert`.

BR_ROOMS = {                       # disposition -> the `rooms` text in the table
    "DISP_GARSONIERA": "Garsónka",
    "DISP_1_1": "1-izbový byt", "DISP_1_KK": "1-izbový byt", "DISP_1_IZB": "1-izbový byt",
    "DISP_2_1": "2-izbový byt", "DISP_2_KK": "2-izbový byt", "DISP_2_IZB": "2-izbový byt",
    "DISP_3_1": "3 izbový byt",  "DISP_3_KK": "3 izbový byt",  "DISP_3_IZB": "3 izbový byt",
    "DISP_4_1": "4-izbový byt",  "DISP_4_KK": "4-izbový byt",  "DISP_4_IZB": "4-izbový byt",
}

# construction -> the `build_type` wording nehnutelnosti rows already use. Only
# the values actually seen in the data are mapped; anything new passes through
# raw, so an unknown enum shows up in the column instead of silently going null.
BR_BUILD = {
    "PANEL": "Panelová", "BRICK": "Tehlová", "MIXED": "Zmiešaná",
    "SKELET": "Skeletová",
}


def br_next_data(html):
    """The page's whole data blob, or None."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def br_page_props(html):
    d = br_next_data(html)
    return ((d or {}).get("props") or {}).get("pageProps") or {}


def br_field(obj, name):
    """Apollo cache keys carry their GraphQL arguments — `address({"locale":"SK"})`
    — so fetch by field name, with or without them."""
    if not isinstance(obj, dict):
        return None
    if name in obj:
        return obj[name]
    for k, v in obj.items():
        if k.split("(", 1)[0] == name:
            return v
    return None


def br_parse_search(html):
    """-> (adverts, total_count), read out of the Apollo cache's listAdverts entry.

    The same cache also holds `listSimilarAdverts` — near-misses from OTHER
    districts, shown as suggestions — and a `discountedOnly` teaser. Neither is
    the search result, and taking either would smuggle in listings the search
    did not match, so match the key exactly."""
    cache = br_page_props(html).get("apolloCache") or {}
    root  = cache.get("ROOT_QUERY") or {}
    for key, val in root.items():
        if not key.startswith("listAdverts(") or '"discountedOnly":true' in key:
            continue
        if not isinstance(val, dict) or not isinstance(val.get("list"), list):
            continue
        rows = []
        for ref in val["list"]:
            a = cache.get(ref.get("__ref")) if isinstance(ref, dict) else None
            if not (isinstance(a, dict) and a.get("id")):
                continue
            a = dict(a)
            img = br_field(a, "mainImage")          # {"__ref": "Image:123"}
            if isinstance(img, dict) and "__ref" in img:
                a["mainImage"] = cache.get(img["__ref"]) or {}
            rows.append(a)
        return rows, val.get("totalCount")
    return [], None


def br_ppm2(price, surface):
    """€/m² in the same shape as the nehnutelnosti column: Slovak decimal comma,
    no thousands separator, no ",00" tail on a round number. The site does not
    publish it, so we do the division ourselves."""
    if not price or not surface:
        return None
    v = price / surface
    return (str(round(v)) if abs(v - round(v)) < 0.005
            else f"{v:.2f}".replace(".", ","))


def br_row_from_search(a, category):
    addr    = br_field(a, "address") or ""
    surface = num(br_field(a, "surface"))
    price   = num(br_field(a, "price"))
    uri     = a.get("uri")
    # There is no title field — `imageAltText` is what the site puts in the card
    # heading ("Predaj bytu 3-izbový 69 m², Milana Marečka, ").
    title   = (br_field(a, "imageAltText") or "").strip().strip(",").strip()
    rooms   = ("Rodinný dom" if br_field(a, "estateType") == "DUM"
               else BR_ROOMS.get(br_field(a, "disposition")) or br_field(a, "disposition"))
    return {
        "id": BR_ID + a["id"],
        "title": title or None,
        "address": addr,
        "street": addr.split(",")[0].strip() or None,
        "price": price,
        "area": round(surface) if surface is not None else None,
        "price_per_m2": br_ppm2(price, surface),
        "rooms": rooms,
        "image": br_field(br_field(a, "mainImage"), "url"),
        "url": f"{BR}/nehnutelnosti-byty-domy/{uri}" if uri else f"{BR}/detail/{a['id']}",
        "category": category,
        # `listed_at` has no counterpart here: bezrealitky publishes no post date,
        # on the search page or the detail page. It stays null — the app treats
        # that as "market age unknown" rather than as day zero.
        "listed_at": None,
        "energie": None, "energies_included": None,
        "floor": None, "floor_num": None, "floor_total": None,
        "lift": None, "build_type": None,
        "deposit": None, "rk_fee": None, "has_ac": None,
        "_photo_url": None, "_own_photo_url": None,
    }


def br_structured_utilities(oa):
    """Monthly charges from the structured fields. 0 means "not stated" here, not
    "free" — every sale listing sampled left all three at 0."""
    oa = oa or {}
    charges = num(oa.get("charges")) or num(oa.get("utilityCharges")) \
              or num(oa.get("serviceCharges")) or None
    if charges:
        return {"energie": charges, "energies_included": False}
    return None


def br_parse_detail(html):
    """Server-parity fields from the SAME ported extractors as nehnutelnosti — the
    Edge Function runs on whatever `url` the row holds, so parity here means
    running its regexes over bezrealitky's HTML too. Everything else comes from
    `pageProps.origAdvert`, the complete listing JSON."""
    out = {}

    d = edge_find_listed_date(html)
    if d:
        out["listed_at"] = d
    u = edge_find_utilities(html)
    if u:                                  # None -> leave alone, as the server does
        out["energie"] = u["energie"]
        out["energies_included"] = u["energies_included"]
    # Stays None in practice: the function's regex is img.nehnutelnosti.sk-only, so
    # it uploads nothing to the bucket for these rows. `_own_photo_url` below is
    # what --photos mirrors instead.
    out["_photo_url"] = edge_find_image_url(html)

    oa = br_page_props(html).get("origAdvert")
    if not isinstance(oa, dict):
        return out

    if not u:
        # The webhook found nothing to overwrite, so there is no parity constraint
        # left and we can use the structured charges.
        st = br_structured_utilities(oa)
        if st:
            out.update(st)

    # `floor` is an enum here (GROUND / MIDDLE / …); `etage` is the number.
    fn = num(oa.get("etage")) if oa.get("etage") is not None else None
    ft = num(oa.get("totalFloors")) if oa.get("totalFloors") is not None else None
    if fn is not None:
        out["floor_num"] = fn
        out["floor"] = f"{fn}/{ft}" if ft else str(fn)
    if ft is not None:
        out["floor_total"] = ft
    if isinstance(oa.get("lift"), bool):
        out["lift"] = oa["lift"]
    if oa.get("construction"):
        out["build_type"] = BR_BUILD.get(oa["construction"]) or oa["construction"]
    if oa.get("street"):
        out["street"] = oa["street"]           # explicit, beats splitting `address`
    if num(oa.get("deposit")):
        out["deposit"] = num(oa["deposit"])
    if num(oa.get("fee")):                     # 0 on an owner-direct ad
        out["rk_fee"] = f"{num(oa['fee'])} €"

    blob = " ".join(str(t) for t in (oa.get("tags") or []))
    blob += " " + (oa.get("description") or "")
    if re.search(r"klimatiz", blob, re.I):
        out["has_ac"] = not re.search(r"bez\s+klimatiz", blob, re.I)

    img = oa.get("mainImage")                  # full size, not the search thumbnail
    if isinstance(img, dict) and img.get("url"):
        out["image"] = img["url"]
        out["_own_photo_url"] = img["url"]
    return out


# ------------------------------------------------------------------- the crawl
# One search-page loop for both sites; everything site-specific hangs off here.

SOURCES = {
    "nehnutelnosti": {
        "host":   "nehnutelnosti.sk",
        "search": nh_parse_search,
        "row":    nh_row_from_search,
        "detail": nh_parse_detail,
        "audit":  lambda html: nh_structured_utilities(nh_structured_params(html)),
    },
    "bezrealitky": {
        "host":   "bezrealitky.sk",
        "search": br_parse_search,
        "row":    br_row_from_search,
        "detail": br_parse_detail,
        "audit":  lambda html: br_structured_utilities(br_page_props(html).get("origAdvert")),
    },
}


def source_of(url):
    """Which site a search or detail URL belongs to, or None if we cannot parse it."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    for name, src in SOURCES.items():
        if host == src["host"] or host.endswith("." + src["host"]):
            return name
    return None


def with_page(url, page):
    """Append the page parameter (both sites take `&page=N`), keeping any
    #fragment last so it cannot swallow it."""
    if page == 1:
        return url
    base, _, frag = url.partition("#")
    base += ("&" if "?" in base else "?") + f"page={page}"
    return base + ("#" + frag if frag else "")


def crawl_search(url, category, page_cap=40, pause=1.5):
    name = source_of(url)
    if not name:
        print(f"    ! unknown site, skipped: {url[:90]}", file=sys.stderr)
        return []
    src = SOURCES[name]
    rows, seen, total = [], set(), None
    for page in range(1, page_cap + 1):
        html = fetch_text(with_page(url, page))
        if html is None:
            break
        batch, tc = src["search"](html)
        if tc is not None:
            total = tc
        fresh = [a for a in batch if a["id"] not in seen]
        if not fresh:
            break                                  # no new ids -> done
        for a in fresh:
            seen.add(a["id"])
            rows.append(src["row"](a, category))
        print(f"    page {page}: +{len(fresh)} (running {len(rows)}"
              + (f"/{total}" if total else "") + ")")
        if total and len(rows) >= total:
            break
        time.sleep(pause)
    return rows


def mirror_photo(row, photo_dir, pause):
    """Download the cover photo the way index.ts does — the URL its regex finds,
    User-Agent only, NO Referer — into photo_dir/<id>.webp, mirroring the
    `apartment-photos` bucket. Returns the function's own status string.

    For a bezrealitky row the function finds nothing (its regex only matches
    img.nehnutelnosti.sk), so the bucket would stay empty and the card would show
    no photo at all. There we mirror the site's own cover instead and say
    `local-only`: these bytes reach the app only once upload_photos.command has
    pushed ./photos/ into the bucket. The filename keeps the .webp the app asks
    for even though bezrealitky serves JPEG — <img> sniffs the bytes."""
    url = row.get("_photo_url")
    own = not url and row.get("_own_photo_url")
    if own:
        url = row["_own_photo_url"]
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
    return f"saved {len(b)//1024}kB" + (" local-only" if own else "")


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


# Columns a re-scrape is allowed to overwrite with --update. `id` is the key;
# `category` never changes for a given listing; `status`, `reason` and
# `updated_at` are the user's own decisions and are not in COLS at all, so an
# upsert cannot touch them.
UPDATE_COLS = [c for c in COLS if c not in ("id", "category")]


def write_sql(rows, path, category, do_update=False):
    lines = [
        f"-- {len(rows)} {category} listings scraped {time.strftime('%Y-%m-%d %H:%M')}",
        "-- Generated by scrape.py. Run category_setup.sql first.",
    ]
    if do_update:
        lines += [
            "-- Re-run safe: refreshes price/area/… on listings already in the table.",
            "-- Your saved/rejected decisions (status, reason) are never written here.",
        ]
    else:
        lines += [
            "-- Safe to re-run: 'do nothing' keeps your saved/rejected decisions,",
            "-- but existing rows also keep their OLD price. Use --update to refresh.",
        ]
    lines += [
        "--",
        "-- listed_at / energie / energies_included match what the listing-photo",
        "-- Edge Function writes, so the insert webhook will not change them.",
        "",
        f"insert into public.apartments ({','.join(COLS)}) values",
    ]
    lines += ["  (" + ",".join(sql_lit(r.get(c)) for c in COLS) + ")"
              + ("," if i < len(rows) - 1 else "")
              for i, r in enumerate(rows)]
    if do_update:
        sets = ",\n".join(f"  {c} = excluded.{c}" for c in UPDATE_COLS)
        lines += ["on conflict (id) do update set", sets + ";", ""]
    else:
        lines += ["on conflict (id) do nothing;", ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))



def write_data_js(out_dir):
    """Bundle every out/listings_<cat>.json into one classic <script> file.

    index.html pulls this in with <script src>, not fetch(): Chrome refuses to
    fetch() a local file from a file:// page, but a classic script tag loads
    fine, so the page keeps working when you just double-click index.html.

    Reads whatever category files are on disk rather than only the categories
    this run touched, so `--category garsonka` does not blank out sale3i.
    """
    payload = {"generatedAt": time.strftime("%Y-%m-%d %H:%M")}
    for name in sorted(os.listdir(out_dir)):
        m = re.match(r"listings_(.+)\.json$", name)
        if not m:
            continue
        with open(os.path.join(out_dir, name), encoding="utf-8") as f:
            d = json.load(f)
        payload[m.group(1)] = {"scrapedAt": d.get("scrapedAt"),
                               "count": d.get("count", len(d.get("listings", []))),
                               "listings": d.get("listings", [])}
    # A listing title containing "</script>" would otherwise end the tag early.
    body = json.dumps(payload, ensure_ascii=False, indent=1).replace("</", "<\\/")
    path = os.path.join(out_dir, "data.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("/* Generated by scrape.py — do not edit; re-run the scraper. */\n"
                "window.SCRAPED = " + body + ";\n")
    cats = [k for k in payload if k != "generatedAt"]
    return path, cats


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=["garsonka", "sale3i", "all"], default="all")
    ap.add_argument("--source", choices=["nehnutelnosti", "bezrealitky", "all"],
                    default="all", help="only crawl one site's searches")
    ap.add_argument("--no-detail", action="store_true",
                    help="skip detail pages (no floor/lift/utilities)")
    ap.add_argument("--photos", action="store_true",
                    help="mirror cover photos into --photo-dir like the Edge Function")
    ap.add_argument("--photo-dir", default="photos")
    ap.add_argument("--audit", action="store_true",
                    help="report where server logic disagrees with the structured "
                         "fields (does not change the output)")
    ap.add_argument("--update", action="store_true",
                    help="emit 'on conflict do update' so a re-scrape refreshes "
                         "price/area/… on listings already in the table "
                         "(your saved/rejected decisions are never touched)")
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
            if args.source != "all" and source_of(url) != args.source:
                continue
            print(f"  {url}")
            for r in crawl_search(url, cat, pause=args.pause):
                if r["id"] not in seen:          # ids are site-prefixed, so this
                    seen.add(r["id"])            # de-dupes within a site, never across
                    rows.append(r)
        if args.limit:
            rows = rows[:args.limit]
        by_src = {}
        for r in rows:
            key = source_of(r["url"]) or "?"
            by_src[key] = by_src.get(key, 0) + 1
        print(f"  {len(rows)} listings from search"
              + (" (" + ", ".join(f"{k} {n}" for k, n in sorted(by_src.items())) + ")"
                 if len(by_src) > 1 else ""))

        audit = []
        if not args.no_detail and rows:
            print(f"  detail pages (pause {args.pause}s)…")
            for i, r in enumerate(rows, 1):
                html = fetch_text(r["url"])
                if not html:
                    print(f"    [{i}/{len(rows)}] {r['id']} FAILED")
                    continue
                src = SOURCES[source_of(r["url"])]
                r.update(src["detail"](html))
                note = ""
                if args.audit:
                    srv = ({"energie": r["energie"],
                            "energies_included": r["energies_included"]}
                           if r["energies_included"] is not None else None)
                    st = src["audit"](html)
                    if srv != st:
                        audit.append((r["id"], srv, st))
                        note = f"  ~ audit: server={srv} structured={st}"
                if args.photos:
                    note = "  photo: " + mirror_photo(r, args.photo_dir, args.pause) + note
                print(f"    [{i}/{len(rows)}] {r['id']} ok{note}")
                if i < len(rows):
                    time.sleep(args.pause)

        local_only = sum(1 for r in rows if not r.get("_photo_url")
                         and r.get("_own_photo_url"))
        for r in rows:
            r.pop("_photo_url", None)
            r.pop("_own_photo_url", None)

        jp = os.path.join(args.out, f"listings_{cat}.json")
        sp = os.path.join(args.out, f"insert_{cat}.sql")
        json.dump({"source": SEARCHES[cat], "scrapedAt": time.strftime("%Y-%m-%d"),
                   "count": len(rows), "listings": rows},
                  open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_sql(rows, sp, cat, do_update=args.update)

        have = lambda k: sum(1 for r in rows if r.get(k) is not None)
        print(f"  -> {jp}\n  -> {sp}")
        print(f"     price {have('price')}/{len(rows)}  area {have('area')}/{len(rows)}  "
              f"floor {have('floor')}/{len(rows)}  lift {have('lift')}/{len(rows)}  "
              f"energie {have('energies_included')}/{len(rows)}")
        if args.photos and local_only:
            print(f"     {local_only} covers are local-only (bezrealitky): the insert "
                  f"webhook cannot fetch them, so run upload_photos.command to get "
                  f"them into the bucket")
        if args.audit:
            inc = sum(1 for _, s, t in audit
                      if s and s.get("energies_included") and t
                      and not t.get("energies_included"))
            print(f"     audit: {len(audit)}/{len(rows)} utilities differ from "
                  f"structured; {inc} where the server says 'included' but the "
                  f"listing states a monthly amount")

    djs, dcats = write_data_js(args.out)
    print(f"\n-> {djs}  ({', '.join(dcats)})  — index.html reads this directly")


if __name__ == "__main__":
    main()
