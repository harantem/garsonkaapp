# Automatic listing photos — setup (one time)

Photos are stored in your Supabase `apartment-photos` bucket as `<id>.webp` — the
same place the app already loads them from. The `listing-photo` Edge Function fetches
each listing's cover photo **server-side** (a browser can't, because nehnutelnosti's
images are CORS-locked and hot-link protected). A database webhook fires the function
on every new row in `apartments`, so the daily feed AND any manual sync get photos with
no extra work.

## 1. Deploy the function (Terminal, in this folder)

```
cd "/Users/ema/Documents/Claude/Projects/Garsonka app"
# one-time: install the CLI if you don't have it
brew install supabase/tap/supabase

supabase login
supabase link --project-ref nfqmwccfeahkpuznkbla
supabase functions deploy listing-photo --no-verify-jwt
```

`--no-verify-jwt` lets the database trigger call it without a key. The function uses the
project's service-role key (injected automatically at runtime) only to write to Storage.

## 2. Create the insert webhook

Open the Supabase SQL editor for the REAL ESTATE APP project and run
**`photo_webhook.sql`** (in this folder). That's it — new listings now self-populate.

## 3. Backfill the listings that are currently missing a photo

```
curl -X POST https://nfqmwccfeahkpuznkbla.supabase.co/functions/v1/listing-photo \
  -H "Content-Type: application/json" -d '{"backfill":true}'
```

It returns how many it uploaded. Re-running is safe — it skips photos that already exist.

## Notes
- No app change and no redeploy of the site is needed; photos appear as soon as they
  land in the bucket.
- If a future test shows a listing comes back `no-image` or `img-403`, the fix is to
  tweak the `Referer`/headers in `supabase/functions/listing-photo/index.ts` and
  redeploy — the rest stays the same.
