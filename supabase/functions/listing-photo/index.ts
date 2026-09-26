// listing-photo — Supabase Edge Function
// For a nehnutelnosti.sk listing it (a) fetches the cover photo SERVER-SIDE and stores
// it in the public `apartment-photos` bucket as `<id>.webp`, and (b) reads the listing's
// original post date (`createdAt` in the page data) and writes it to `apartments.listed_at`
// so the app can show how long each flat has been on the market. Runs from a DB insert
// webhook on `apartments`, so every new listing self-populates both — no manual work.
//
// Backfill:  POST {"backfill": true}            -> fills photo+date for all that are missing
//            POST {"backfill": true, "max": 25} -> process at most 25 (returns `remaining`)
// One row:   POST {"record": {"id","url"}}       (what the insert webhook sends)

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const BUCKET = "apartment-photos";
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36";

const sb = createClient(SB_URL, SB_KEY);

async function photoExists(id: string): Promise<boolean> {
  const r = await fetch(
    `${SB_URL}/storage/v1/object/public/${BUCKET}/${encodeURIComponent(id)}.webp`,
    { method: "HEAD" },
  );
  return r.ok;
}

// Cover image: slashes/ampersands are escaped in the page's inline JSON — decode them
// or the signed query (?st=…&ts=…&e=0) breaks and the image server 403s. Real photos
// end in `_fss?st=…`.
function findImageUrl(html: string): string | null {
  const norm = html
    .replace(/\\u002[fF]/g, "/")
    .replace(/\\u0026/g, "&")
    .replace(/&amp;/g, "&")
    .replace(/\\\//g, "/");
  const m = norm.match(
    /https:\/\/img\.nehnutelnosti\.sk\/foto\/[^\s"'\\<>]*_fss\?[^\s"'\\<>]+/,
  );
  return m ? m[0] : null;
}

// Original post date — the listing object carries "createdAt":"YYYY-MM-DD...".
// In the raw server HTML the quotes are backslash-escaped (\"createdAt\":\"…), so
// un-escape first.
function findListedDate(html: string): string | null {
  const m = html.replace(/\\"/g, '"').match(/"createdAt"\s*:\s*"(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : null;
}

// Utilities (energie). Structured fields are most reliable:
//   "powerCosts":{"value":"150 €/mes"}   -> €150/mo, billed separately
//   "noteToPrice":"… vrátane energií"    -> included in rent
// Returns null when nothing is stated (so we never overwrite a good value with null).
function findUtilities(
  html: string,
): { energie: number | null; energies_included: boolean } | null {
  const h = html.replace(/\\"/g, '"');
  const note = (h.match(/"noteToPrice"\s*:\s*"([^"]{0,120})"/) || [])[1] || "";
  if (/vr[aá]tane energi|s energiami|energie v cene|v cene[^.]{0,20}energi/i.test(h) ||
      /vr[aá]tane|v cene/i.test(note)) {
    return { energie: null, energies_included: true };
  }
  const pc = (h.match(/"powerCosts"\s*:\s*\{\s*"value"\s*:\s*"([^"]+)"/) || [])[1] || "";
  let n = pc.match(/(\d+)/);
  if (!n && /energi|pripočítava|poplatk/i.test(note)) n = note.match(/(\d{2,4})/);
  if (n) return { energie: parseInt(n[1], 10), energies_included: false };
  return null;
}

async function processOne(
  id: string,
  url: string,
  needPhoto: boolean,
  needDate: boolean,
  needUtil: boolean,
): Promise<Record<string, string>> {
  if (!url) return { id, status: "no-url" };
  if (!needPhoto && !needDate && !needUtil) return { id, status: "skip" };

  const page = await fetch(url, { headers: { "User-Agent": UA } });
  if (!page.ok) return { id, status: `page-${page.status}` };
  const html = await page.text();
  const out: Record<string, string> = { id, status: "ok" };

  if (needDate) {
    const d = findListedDate(html);
    if (d) {
      await sb.from("apartments").update({ listed_at: d }).eq("id", id);
      out.listed_at = d;
    } else out.date = "no-date";
  }

  if (needUtil) {
    const u = findUtilities(html);
    if (u) {
      // only write when we actually found something — never overwrite with null
      await sb.from("apartments")
        .update({ energie: u.energie, energies_included: u.energies_included })
        .eq("id", id);
      out.energie = u.energies_included ? "included" : String(u.energie);
    } else out.util = "not-stated";
  }

  if (needPhoto) {
    const img = findImageUrl(html);
    if (!img) out.photo = "no-image";
    else {
      // image fetch: User-Agent only, NO Referer (a Referer triggers hot-link 403).
      const ir = await fetch(img, { headers: { "User-Agent": UA } });
      if (!ir.ok) out.photo = `img-${ir.status}`;
      else {
        const bytes = new Uint8Array(await ir.arrayBuffer());
        const { error } = await sb.storage
          .from(BUCKET)
          .upload(`${id}.webp`, bytes, { contentType: "image/webp", upsert: true });
        out.photo = error ? "upload-error: " + error.message : "uploaded";
      }
    }
  }
  return out;
}

function json(o: unknown, status = 200) {
  return new Response(JSON.stringify(o), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  try {
    const body = await req.json().catch(() => ({} as Record<string, unknown>));

    if ((body as any).backfill) {
      const max = Number((body as any).max ?? 25);
      const { data, error } = await sb
        .from("apartments")
        .select("id,url,listed_at,energie,energies_included")
        .order("id");
      if (error) return json({ error: error.message }, 500);

      const todo: { id: string; url: string; needPhoto: boolean; needDate: boolean; needUtil: boolean }[] = [];
      for (const row of data ?? []) {
        const needDate = !row.listed_at;
        const needUtil = (row.energie == null) && !row.energies_included;
        const needPhoto = !(await photoExists(row.id));
        if (needDate || needPhoto || needUtil) todo.push({ id: row.id, url: row.url, needPhoto, needDate, needUtil });
      }
      const batch = todo.slice(0, max);
      const results = [];
      for (const t of batch) results.push(await processOne(t.id, t.url, t.needPhoto, t.needDate, t.needUtil));
      return json({ processed: results.length, remaining: todo.length - batch.length, results });
    }

    const rec = (body as any).record ?? (body as any);
    if (!rec?.id) return json({ error: "no record id" }, 400);
    const needPhoto = !(await photoExists(rec.id));
    return json(await processOne(rec.id, rec.url, needPhoto, true, true));
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
