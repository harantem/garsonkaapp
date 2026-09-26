-- ===== Garsónka apartment tracker — Supabase setup =====
-- Paste this whole file into the Supabase SQL editor and click RUN.
-- Safe to run more than once. Re-running will NOT erase your save/reject choices.

create table if not exists public.apartments (
  id text primary key,
  title text, address text, street text,
  price int, energie int, energies_included boolean,
  price_per_m2 text, area int,
  floor text, floor_num int, floor_total int,
  lift boolean, build_type text, rooms text,
  image text, url text,
  status text default 'new',
  reason text default '',
  updated_at timestamptz default now()
);

-- Row Level Security: allow the app's public (anon) key to read and edit.
alter table public.apartments enable row level security;
drop policy if exists "anon read"   on public.apartments;
drop policy if exists "anon write"  on public.apartments;
drop policy if exists "anon insert" on public.apartments;
create policy "anon read"   on public.apartments for select using (true);
create policy "anon write"  on public.apartments for update using (true) with check (true);
create policy "anon insert" on public.apartments for insert with check (true);

-- Seed the 20 listings. 'on conflict do nothing' keeps your decisions on re-run.
insert into public.apartments (id,title,address,street,price,energie,energies_included,price_per_m2,area,floor,floor_num,floor_total,lift,build_type,rooms,image,url) values
  ('JuRgfzENSJF', 'Prenájom samostatnej nepriechodnej izby v centre Bratislavy', 'Krížna, Bratislava-Staré Mesto, okres Bratislava I', 'Krížna', 350, null, true, '31,82', 11, '1/4', 1, 4, false, 'Zmiešaná', 'Garsónka', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/lSpoTGHUb_fss', 'https://www.nehnutelnosti.sk/detail/JuRgfzENSJF/prenajom-samostatnej-nepriechodnej-izby-v-centre-bratislavy'),
  ('JuRAwga1iza', 'Prenájom samostatnej izby v 3 izbovom byte s terasou, vlastným dvorom a záhradkou, ako oddelený samostatný byt v rodinnom dome v Bratislave – Staré Mesto, Slávičie údolie.', 'Bratislava-Staré Mesto, okres Bratislava I', 'Bratislava-Staré Mesto', 400, null, false, '16', 25, null, null, null, false, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/P69pWqBFA_fss', 'https://www.nehnutelnosti.sk/detail/JuRAwga1iza/prenajom-samostatnej-izby-v-3-izbovom-byte-s-terasou-vlastnym-dvorom-a-zahradkou-ako-oddeleny-samostatny-byt-v-rodinnom-dome-v-bratislave-stare-mesto-slavicie-udolie'),
  ('Ju2OXjdfnlT', 'Prenájom priestrannej izby v 2 izbovom byte s loggiou – Bratislava – Staré Mesto, lokalita Mozartova', 'Bratislava-Staré Mesto, okres Bratislava I', 'Bratislava-Staré Mesto', 400, null, false, '22,22', 18, null, null, null, true, 'Novostavba', 'Garsónka', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/hDkprp7HB_fss', 'https://www.nehnutelnosti.sk/detail/Ju2OXjdfnlT/prenajom-priestrannej-zby-v-2-izbovom-byte-s-loggiou-bratislava-stare-mesto-lokalita-mozartova-v-prijemnom-tichom-prostredi-v-blizkom-dosahu-ku-prirode'),
  ('Juev-sCi24h', 'AXIS REAL | Pekná štýlová garsónka, PIVNICA, BA I SM, Slávičie údolie', 'Slávičie údolie, Bratislava-Staré Mesto, okres Bratislava I', 'Slávičie údolie', 450, 150, false, '14,06', 32, '2/4', 2, 4, true, 'Tehlová', 'Garsónka', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/RVVIjdtyS_fss', 'https://www.nehnutelnosti.sk/detail/Juev-sCi24h/axis-real-pekna-stylova-garsonka-pivnica-ba-i-sm-slavicie-udolie'),
  ('Ju70pTFt6GS', 'KLIMATIZOVANÝ 1-izbový byt 40 m2, NADSTAVBA, CENTRUM Bratislavy / Heydukova ul.', 'Heydukova, Bratislava-Staré Mesto, okres Bratislava I', 'Heydukova', 500, 200, false, '12,5', 40, '5/6', 5, 6, true, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvcnNm/nA0HLELPo_fss', 'https://www.nehnutelnosti.sk/detail/Ju70pTFt6GS/klimatizovany-1-izbovy-byt-40-m2-nadstavba-centrum-bratislavy-heydukova-ul'),
  ('Ju7AvM-kGnE', 'Prenajmeme veľký 1 izb byt na Heydukovej ulici', 'Heydukova, Bratislava-Staré Mesto, okres Bratislava I', 'Heydukova', 500, 200, false, '12,5', 40, '5/6', 5, 6, true, 'Tehlová', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/NDsXLfws8_fss', 'https://www.nehnutelnosti.sk/detail/Ju7AvM-kGnE/prenajmeme-velky-1-izb-byt-na-heydukovej-ulici'),
  ('Ju3Q9teGy7p', 'BOSEN | Zariadená garzónka s balkónom, Blumentálska ul., BA', 'Blumentálska, Bratislava-Staré Mesto, okres Bratislava I', 'Blumentálska', 500, 175, false, '19,23', 26, '5/8', 5, 8, false, 'Zmiešaná', 'Garsónka', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/n_BzYGVmv_fss', 'https://www.nehnutelnosti.sk/detail/Ju3Q9teGy7p/bosen-zariadena-garzonka-s-balkonom-blumentalska-ul-ba'),
  ('JuaRg_NbGP9', 'Prenájom 1 izb. bytu Steinov dvor', 'Steinov dvor, Bratislava-Staré Mesto, okres Bratislava I', 'Steinov dvor', 520, 150, false, '14,44', 36, null, null, null, false, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/C0NLqwNZu_fss', 'https://www.nehnutelnosti.sk/detail/JuaRg_NbGP9/prenajom-1-izb-bytu-steinov-dvor'),
  ('JulWJBn0EHz', 'Príjemný 2i byt s balkónom, pri Horskom parku a Slavíne. Svetlá ul.', 'Svetlá, Bratislava-Staré Mesto, okres Bratislava I', 'Svetlá', 520, 230, false, '9,29', 56, '1/11', 1, 11, true, 'Panelová', '2-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKGp1bC9VSTBzX1VFUXRfZnNzLC0yNSwtMjUsNTAsMjAsMjApL2p1bA==/_Mg3p5V-f_fss', 'https://www.nehnutelnosti.sk/detail/JulWJBn0EHz/prijemny-2i-byt-s-balkonom-pri-horskom-parku-a-slavine-svetla-ul'),
  ('Jum1vVXXPn9', 'Na prenájom moderný 1-izbový byt v novostavbe Steinov dvor – Staré Mesto, Bratislava', 'Krížna, Bratislava-Staré Mesto, okres Bratislava I', 'Krížna', 520, 150, false, '14,44', 36, '2/7', 2, 7, true, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/TGvMQAVS2_fss', 'https://www.nehnutelnosti.sk/detail/Jum1vVXXPn9/na-prenajom-moderny-1-izbovy-byt-v-novostavbe-steinov-dvor-stare-mesto-bratislava'),
  ('JuU4EhWTxOF', 'Pekný, slnečný 1-izbový byt, Malý trh, Staré Mesto', 'Malý trh, Bratislava-Staré Mesto, okres Bratislava I', 'Malý trh', 550, null, false, '17,19', 32, '2/4', 2, 4, false, 'Tehlová', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/c8jcOlCtP_fss', 'https://www.nehnutelnosti.sk/detail/JuU4EhWTxOF/ponukame-na-prenajom-pekny-slnecny-1-izbovy-byt-nachadzajuci-sa-2poschodi4-v-tehlovom-dome-na-malom-trhu-v-lokalite-stare-mesto-byt-je-priestranny'),
  ('JuzP9cU5z3G', 'Prenájom byty 1 iz. NOVOSTAVBA Blumentál, Radlinského ul. BA I', 'Radlinského, Bratislava-Staré Mesto, okres Bratislava I', 'Radlinského', 550, null, false, '15,28', 36, '2/6', 2, 6, true, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/T35EReNLa_fss', 'https://www.nehnutelnosti.sk/detail/JuzP9cU5z3G/prenajom-byty-1-iz-novostavba-blumental-radlinskeho-ul-ba-i'),
  ('JuzCOg_jA3y', 'REZERVOVANÝ 1-izbový byt na Špitálskej ulici', 'Špitálska, Bratislava-Staré Mesto, okres Bratislava I', 'Špitálska', 555, 125, false, '13,88', 40, '4/5', 4, 5, true, 'Tehlová', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKHB1cy9RanAzd1paa2lfZnNzLC0yNSwtMjUsMjAsMjAsMjApL2p1bA==/nkxBPFGd8_fss', 'https://www.nehnutelnosti.sk/detail/JuzCOg_jA3y/1-izbovy-byt-na-spitalskej-ulici'),
  ('JuQBUw6AU18', 'Na prenájom kompletne zariadená garsónka v Starom Meste – Dunajská', 'Dunajská, Bratislava-Staré Mesto, okres Bratislava I', 'Dunajská', 570, null, false, '38', 15, '5/6', 5, 6, false, 'Zmiešaná', 'Garsónka', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKHB1cy84V05ZaDRueExfZnNzLDI1LC0yNSwwLDIwLDIwKS9qdWw=/RGRkHu_0P_fss', 'https://www.nehnutelnosti.sk/detail/JuQBUw6AU18/na-prenajom-kompletne-zariadena-garsonka-v-starom-meste-dunajska'),
  ('JulEG0AgFso', 'Štýlové bývanie v srdci mesta s veľkou terasou a panoramatickým výhľadom!', 'Grösslingova, Bratislava-Staré Mesto, okres Bratislava I', 'Grösslingova', 570, null, false, '15,83', 36, null, null, null, true, 'Novostavba', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKHB1cy83QVlJNC1NS25fZnNzLGNlbnRlcixjZW50ZXIsMCwyMCwyMCkvanVs/lA2NCmvmD_fss', 'https://www.nehnutelnosti.sk/detail/JulEG0AgFso/stylove-byvanie-v-srdci-mesta-s-velkou-terasou-a-panoramatickym-vyhladom'),
  ('JuYlGqB3kdt', 'Prenájom: 1 izbový zariadený byt, BA I – Staré Mesto, Tichá ul.', 'Tichá, Bratislava-Staré Mesto, okres Bratislava I', 'Tichá', 570, 200, false, '11,18', 51, '7/10', 7, 10, true, 'Tehlová', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/0t79G3r70c_fss', 'https://www.nehnutelnosti.sk/detail/JuYlGqB3kdt/prenajom-1-izbovy-zariadeny-byt-ba-i-stare-mesto-ticha-ul'),
  ('Juzmx3VlsMc', '1 IZBOVÝ BYT PO KOMPLETNEJ REKONŠTRUKCII s FAMÓZNYM VÝHĽADOM – STARÉ MESTO – Námestie SNP – MANDERLA', 'Nám. SNP, Bratislava-Staré Mesto, okres Bratislava I', 'Nám. SNP', 590, 230, false, '15,53', 38, '9/10', 9, 10, true, 'Tehlová', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKHB1cy9xMkFNRXU1T3dfZnNzLGNlbnRlcixjZW50ZXIsMCwyMCwyMCkvanVs/yQPrPWuSLU_fss', 'https://www.nehnutelnosti.sk/detail/Juzmx3VlsMc/1-izbovy-byt-po-kompletnej-rekonstrukcii-s-famoznym-vyhladom-stare-mesto-namestie-snp-manderla'),
  ('JueJpKjNYoC', 'Skvelý 1i byt 20m2, NA KRÁTKODOBÝ PRENÁJOM 6 MESIACOV', 'Janáčkova, Bratislava-Staré Mesto, okres Bratislava I', 'Janáčkova', 590, null, false, '29,5', 20, null, null, null, false, null, '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/2kkqhwZjFp_fss', 'https://www.nehnutelnosti.sk/detail/JueJpKjNYoC/skvely-1i-byt-20m2-na-kratkodoby-prenajom-6-mesiacov'),
  ('JuHHRn8MYQM', 'Grebeči real | jedinečný a kompletne zrekonštruovaný moderný 1-izbový byt, Námestie SNP', 'Námestie SNP, Bratislava-Staré Mesto, okres Bratislava I', 'Námestie SNP', 590, null, false, '15,53', 38, '9/10', 9, 10, true, 'Zmiešaná', '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCk6d2F0ZXJtYXJrKGp1bC84WWRua05OZVhfZnNzLGNlbnRlcixjZW50ZXIsMTAsMjAsMjApL2p1bA==/h2yFP_fwR_fss', 'https://www.nehnutelnosti.sk/detail/JuHHRn8MYQM/grebeci-real-ponuka-na-prenajom-jedinecny-a-kompletne-zrekonstruovany-moderny-1-izbovy-byt-namestie-snp-stare-mesto-bratislava'),
  ('JuKmk-fN0UZ', 'PRENÁJOM 1-izbový, Staré Mesto Vazovová, nezariadený', 'Vazovova, Bratislava-Staré Mesto, okres Bratislava I', 'Vazovova', 600, null, false, '15', 40, '3/6', 3, 6, true, null, '1-izbový byt', 'https://img.unitedclassifieds.sk/foto/ZmlsdGVyczpmb3JtYXQod2VicCkvanVs/e1L724lwX_fss', 'https://www.nehnutelnosti.sk/detail/JuKmk-fN0UZ/prenajom-1-izbovy-stare-mesto-vazovova-nezariadeny')
on conflict (id) do nothing;
bash upload_photos.command
cd ~/Documents/Claude/Projects/Garsonka\ app
bash download_photos.command
bash upload_photos.command
cd ~/Documents/Claude/Projects/Garsonka\ app
bash download_photos.command
bash upload_photos.command

