-- ===== Garsónka tracker — extra fields (deposit, agency fee, AC, first-seen date) =====
-- Paste into the Supabase SQL editor (REAL ESTATE APP project) and click RUN. Safe to re-run.

-- 1) New columns
alter table public.apartments add column if not exists deposit   int;
alter table public.apartments add column if not exists rk_fee    text;
alter table public.apartments add column if not exists has_ac    boolean default false;
alter table public.apartments add column if not exists scraped_at date;

-- 2) Stamp every existing row with a first-seen date (today) if not set
update public.apartments set scraped_at = current_date where scraped_at is null;

-- 3) Air conditioning (true only for these; everything else false)
update public.apartments set has_ac = false;
update public.apartments set has_ac = true where id in (
  'Ju0dIp8xfw4','Ju10RKJsPMa','Ju70pTFt6GS','Ju7AvM-kGnE',
  'Jugs4gQwC3M','JuJTSHTgXJD','JupOgnemL20','JuyVDdgbGui'
);

-- 4) Deposits stated on the listing (others stay null = "not stated")
update public.apartments set deposit = 750 where id = 'JulWJBn0EHz';
update public.apartments set deposit = 400 where id = 'JuRgfzENSJF';
update public.apartments set deposit = 677 where id = 'JuYlGqB3kdt';

-- (Agency fee / provízia is not published on any of these listings, so rk_fee stays null.)
