-- Garsonka app — category switch (garsónky ⇄ 3-izbové + domy).
-- Run this ONCE in Supabase → SQL Editor. Safe to re-run.
--
-- The header toggle flips the app between two listing sets that live in the SAME
-- apartments table, told apart by the `category` column:
--
--   'garsonka'  Bratislava · Staré Mesto · PRENÁJOM · garsónky + 1-izbové
--               (everything already in the table — backfilled below)
--   'sale3i'    Devínska Nová Ves · Vajnory · Záhorská Bystrica · PREDAJ
--               3-izbové byty + domy, plocha od 70 m²
--               https://www.nehnutelnosti.sk/vysledky/predaj?locations=100012516&locations=100012515&locations=100012521&categories=300001&categories=200000&areaFrom=70
--               plus the same three districts on bezrealitky.sk (owner-direct,
--               one search per district, plocha od 65 m²) — those rows carry a
--               'br-' id prefix. See SEARCHES in scrape.py.

-- 1) apartments: add the category column and backfill existing rows.
alter table public.apartments
  add column if not exists category text not null default 'garsonka';

update public.apartments set category = 'garsonka' where category is null or category = '';

create index if not exists apartments_category_idx on public.apartments (category);

-- 2) stats_snapshots: one price-history series per category, so the sale trend
--    never collides with the rental trend. Existing rows become 'garsonka'.
alter table public.stats_snapshots
  add column if not exists category text not null default 'garsonka';

alter table public.stats_snapshots
  drop constraint if exists stats_snapshots_snap_date_grp_key;

create unique index if not exists stats_snapshots_day_grp_cat
  on public.stats_snapshots (snap_date, grp, category);

-- 3) Insert the sale listings here. Same columns as the rental seed, except:
--      price  = full asking price in € (not monthly rent)
--      energie / energies_included / deposit / rk_fee  -> leave null
--      rooms  = '3 izbový byt' or 'Rodinný dom'
--      category = 'sale3i'
--
-- insert into public.apartments
--   (id,title,address,street,price,price_per_m2,area,floor,floor_num,floor_total,
--    lift,build_type,rooms,image,url,category) values
--   ('<id>','<title>','<address>','<street>',459000,'4153,85',110.5,null,null,null,
--    null,'Novostavba','3 izbový byt','<image url>','<listing url>','sale3i')
-- on conflict (id) do nothing;
