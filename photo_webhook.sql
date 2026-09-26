-- ===== Auto cover-photo on new listing =====
-- Fires the `listing-photo` Edge Function every time a row is INSERTed into
-- public.apartments, so new listings get their photo into the apartment-photos
-- bucket automatically. Run this in the SQL editor of the REAL ESTATE APP project
-- AFTER deploying the function. Safe to run more than once.

-- pg_net lets Postgres make an outbound HTTP call.
create extension if not exists pg_net with schema extensions;

create or replace function public.fire_listing_photo()
returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform net.http_post(
    url     := 'https://nfqmwccfeahkpuznkbla.supabase.co/functions/v1/listing-photo',
    headers := jsonb_build_object('Content-Type', 'application/json'),
    body    := jsonb_build_object('record',
                 jsonb_build_object('id', NEW.id, 'url', NEW.url))
  );
  return NEW;
end;
$$;

drop trigger if exists trg_listing_photo on public.apartments;
create trigger trg_listing_photo
  after insert on public.apartments
  for each row
  execute function public.fire_listing_photo();
