#!/bin/bash
# Uploads every photo in ./photos/ to the Supabase Storage bucket "apartment-photos".
# Run storage_setup.sql in Supabase first, then run this:  bash upload_photos.command
set -u
cd "$(dirname "$0")"

URL="https://nfqmwccfeahkpuznkbla.supabase.co"
KEY="sb_publishable_VIa_sGDBf3gzVXKCm1wxPg_vMiyjo_w"
BUCKET="apartment-photos"

if ! ls photos/*.webp >/dev/null 2>&1; then
  echo "No photos found in ./photos/ — run download_photos.command first."; exit 1
fi

ok=0; fail=0
for f in photos/*.webp; do
  name=$(basename "$f")
  if curl -fsS -X POST "$URL/storage/v1/object/$BUCKET/$name" \
       -H "apikey: $KEY" \
       -H "Authorization: Bearer $KEY" \
       -H "x-upsert: true" \
       -H "Content-Type: image/webp" \
       --data-binary "@$f" >/dev/null; then
    echo "✓ uploaded $name"; ok=$((ok+1))
  else
    echo "✗ $name failed"; fail=$((fail+1))
  fi
done

echo ""
echo "Done. Uploaded $ok, failed $fail."
echo "Refresh index.html — photos now load from Supabase Storage."
