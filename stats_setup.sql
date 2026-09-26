-- Garsonka app — price-history snapshots.
-- Run this ONCE in Supabase → SQL Editor (safe to re-run). It lets the app and the
-- daily feed record one row per day per group so the Statistics page can chart price over time.

create table if not exists public.stats_snapshots (
  id          bigint generated always as identity primary key,
  snap_date   date not null,
  grp         text not null check (grp in ('all','old','new')),
  avg_price   numeric,
  avg_m2      numeric,
  avg_size    numeric,
  n           int,
  created_at  timestamptz not null default now(),
  unique (snap_date, grp)
);

alter table public.stats_snapshots enable row level security;

-- Same trust model as the apartments table: anyone with the publishable key may read/append.
drop policy if exists stats_read   on public.stats_snapshots;
drop policy if exists stats_insert on public.stats_snapshots;
drop policy if exists stats_update on public.stats_snapshots;
create policy stats_read   on public.stats_snapshots for select using (true);
create policy stats_insert on public.stats_snapshots for insert with check (true);
create policy stats_update on public.stats_snapshots for update using (true) with check (true);
