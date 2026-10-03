# Bezpečnosť

## Čo nepatrí do repozitára

API kľúče, `.env`, adresár `secrets/`, dáta, databázy vrátane WAL/SHM, zálohy, audio, privátne kľúče, autentifikačné tokeny a logy. `.env.example` obsahuje iba všeobecné nastavenia a prázdne tajné hodnoty. Skutočný OpenAI API kľúč je pripojený len pracovníkovi ako read-only súbor.

`.gitignore` ani `.dockerignore` neodstránia tajomstvo, ktoré už bolo commitnuté. Pred každým pushom skontrolujte **pracovné súbory aj históriu**:

```sh
gitleaks dir --redact .
gitleaks git --redact --log-opts=--all .
git diff --cached --stat
```

Testy používajú iba syntetické hodnoty. Do screenshotov nepridávajte emaily, tokeny, súkromné adresy, administrátorské relácie ani prevádzkové logy. Zverejňujte len overené snímky verejného rozhrania.

## Nahlásenie problému

Použite súkromné nahlásenie zraniteľnosti v záložke Security na GitHube, ak je dostupné. Ak nie je, môžete vytvoriť issue iba so všeobecným popisom a žiadosťou o súkromný kontakt; bez kľúčov, tokenov či reprodukcie umožňujúcej útok na živý web.

Ak tajomstvo uniklo, jeho odstránenie z posledného commitu nestačí. Najprv ho zneplatnite u poskytovateľa; následne riešte históriu, forky, cache a prípadné balíky.
