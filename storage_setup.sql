-- ===== Garsónka photos — Supabase Storage setup =====
-- Run this in the SQL editor of the REAL ESTATE APP project, then run upload_photos.command.
-- Safe to run more than once.

-- 1) A public bucket to hold the cover photos (public = readable by the app without a login).
insert into storage.buckets (id, name, public)
values ('apartment-photos', 'apartment-photos', true)
on conflict (id) do nothing;

-- 2) Let the public (anon) key UPLOAD into this one bucket — needed by the upload script.
drop policy if exists "anon upload apartment-photos" on storage.objects;
create policy "anon upload apartment-photos"
  on storage.objects for insert to anon
  with check (bucket_id = 'apartment-photos');

drop policy if exists "anon update apartment-photos" on storage.objects;
create policy "anon update apartment-photos"
  on storage.objects for update to anon
  using (bucket_id = 'apartment-photos')
  with check (bucket_id = 'apartment-photos');
