# Zmeny

## Plynulejšie nahovorenie · 2026-10-05

- Podcastový scenár používa prirodzené celé vety, krátke prechody a jeden odsek na kapitolu bez režijných značiek, SSML či dramatickej interpunkcie.
- Supertonic 3 M1 má natívne tempo 1.15 a kratšie medzery medzi blokmi; dlhé úseky veľmi tichého audia sa konzervatívne skracujú so zachovaním ich okrajov.
- Tempo 140–160 slov za minútu je orientačný redakčný cieľ, nie garantovaná hodnota. Existujúce audio, prepisy a merané časy kapitol sa spätne nemenia.

## Verejný zoznam zdrojov · 2026-10-03

- Stránka O projekte obsahuje 15 médií a všetkých 24 nakonfigurovaných RSS kanálov, rozdelených na slovenské, české a zahraničné zdroje, s odkazmi na weby aj feedy.
- Obsahové verzie štýlov a skriptov zabezpečujú načítanie aktuálnych súborov pri bežnom obnovení stránky.
- README obsahuje aktuálny prehľad zdrojov a screenshot verejného zoznamu.

## Výber správ pred AI · 2026-10-03

- Najviac 80 nových udalostí denne, osem od vydavateľa a postupné uvoľňovanie miest počas dňa; všetkých 24 RSS kanálov zostáva aktívnych.
- Konzervatívne zoskupovanie titulkov a RSS výňatkov pred AI s pripojením ďalších zdrojov po analýze.
- Priorita užitočných tém, pestrosť zdrojov, 48-hodinové okno bežných správ a sedem dní pre pozitívne zamerané zdroje.
- Úvodná stránka s 20 správami a odkazom na úplný prehľad; existujúci textový archív a štatistiky zostávajú zachované.
- Trvalé rezervácie miest a dôvody odloženia či vyradenia v administrácii; opakované pokusy neobchádzajú limit.

## Úsporné spracovanie · 2026-10-03

- Dávky najviac po 16 článkoch, lokálne čistenie podkladov a výber odsekov z dlhých textov; pôvodný archív ostáva zachovaný.
- Opravy iba chybných položiek najprv Lunou a potom Solom; opravy sú zahrnuté do spotreby na článok.
- Spoločné volanie pre oba denné scenáre s jednorazovým vstupom súhrnov a samostatným uložením každého platného scenára.


## Zlepšenia po V2.0.0 · 2026-10-03

- Mužský lokálny hlas Supertonic 3 M1 nahrádza Piper pre nové vydania. Model aj hlas zodpovedajú vybranej ukážke; existujúce epizódy sa nenahrávajú znova.
- Prehrávač zobrazuje klikateľné úseky tém podľa skutočných dĺžok a zvýrazňuje aktuálnu kapitolu.
- Hlasový server ostáva dostupný pre kontrolu zdravia počas nahovorenia; krátke požiadavky a dlhšia pracovná lehota zohľadňujú rýchlosť CPU.

## V2.0.0 · 2026-10-03

- Kompletný redizajn verejného webu a administrácie, široké rozloženie na počítači, mobilné ovládanie a svetlá/tmavá téma.
- Smajlíky, farebné sentimenty, počty a percentá; kombinované filtre a samostatné stránkovanie každého sentimentu.
- OpenAI Responses API, povolené modely Luna a Sol 6.1 s high, dávkové spracovanie, trvalá fronta, validácia a evidencia tokenov.
- Archív, FTS vyhľadávanie a detail článkov so zdrojmi a vysvetlením sentimentu.
- Dve denné epizódy, lokálny Piper, skutočné MP3, prepisy, kapitoly, RSS a prehrávanie počas navigácie.
- Automatická 14-dňová audio retencia a zachovanie textových dát.
- Cloudflare Access s overovaním JWT, CSRF, oddelený API kľúč pracovníka, offline regresné testy a kontrola tajomstiev v CI.
- Verejné README so screenshotmi, MIT licencia, bezpečnostné pokyny a odkaz na zdrojový kód z webu.

Predchádzajúca implementácia je zachovaná v histórii Gitu. Nová verzia neobsahuje súkromné prevádzkové dáta ani konfiguráciu.
