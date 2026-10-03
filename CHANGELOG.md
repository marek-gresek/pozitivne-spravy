# Zmeny

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
