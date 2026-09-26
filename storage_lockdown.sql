-- OPTIONAL — run this AFTER upload_photos.command finishes successfully.
-- It removes the upload permission so the public key can no longer write to Storage.
-- Photos stay readable (the bucket is public); you just can't upload with the anon key anymore.
-- (Re-run storage_setup.sql later if you ever need to upload again.)

drop policy if exists "anon upload apartment-photos" on storage.objects;
drop policy if exists "anon update apartment-photos" on storage.objects;
