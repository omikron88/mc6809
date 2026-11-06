# Holý ZX Spectrum 48K — Z80 a Pygame

Samostatný příklad v `src/zxspectrum/` používá přímo zdejší knihovnu `src/z80`.
Emuluje základní **48K Spectrum PAL**, bez rozšiřujících desek, disket, pásky
a přepínání paměťových bank. Nejde o Spectrum 128K ani ZX Spectrum Next.

## Instalace a spuštění

Z kořene repozitáře:

```sh
python -m pip install -e ".[spectrum]"
python -m zxspectrum --demo
```

Vyžaduje Python 3.10+ a Pygame 2.5+. Pygame je volitelná závislost; ostatní
emulátory ji nepotřebují. Po instalaci lze použít i příkaz `zxspectrum --demo`.

Vestavěná původní demonstrační ROM spustí skutečný kód Z80. Pomocí LDIR přenese
bitmapu a atributy z ROM do RAM, nastaví IM1 a čeká v HALT. Obsluha přerušení
čte klávesnici, mění rámeček a překlápí reproduktor. Barevný obraz ukazuje
atributy INK/PAPER, BRIGHT a FLASH. Není to Sinclair BASIC.

Pro vlastní firmware:

```sh
python -m zxspectrum --rom /cesta/48.rom
```

ROM musí mít přesně **16384 bajtů** a být určena pro Spectrum 48K. Sinclair ROM
není přiložena ani automaticky stahována. Start konkrétní originální BASIC ROM
nebyl při tomto ověření testován. Žádné snapshoty SNA/Z80 ani pásky TAP/TZX se
nenačítají.

## Ovládání

| Klávesa PC | Klávesa Spektra |
| --- | --- |
| A–Z, 0–9, Enter, Space | Odpovídající klávesy |
| Levý nebo pravý Shift | CAPS SHIFT |
| Levý nebo pravý Ctrl | SYMBOL SHIFT |
| Šipky vlevo/dolů/nahoru/vpravo | CAPS SHIFT + 5/6/7/8 |
| Backspace | CAPS SHIFT + 0 (DELETE) |
| Escape | CAPS SHIFT + SPACE (BREAK) |
| Čárka / tečka / minus / rovná se | SYMBOL SHIFT + N / M / J / L |
| Lomítko / středník / uvozovka | SYMBOL SHIFT + V / O / P |
| F12 | Reset CPU/ULA, obsah RAM zůstane |
| F10 nebo zavření okna | Ukončení |

Vstup používá matici původních čtyřiceti kláves, nikoli automatické vkládání
textu do BASICu. Číslice a písmena proto zachovávají klávesové režimy původní ROM.
Pomocná mapování interpunkce nejsou plnou emulací českého rozložení PC.
Při ztrátě fokusu se všechny klávesy uvolní. Současné držení například Shiftu
a šipky se vyhodnocuje společně; uvolnění jedné kombinace nezruší druhou.

## Obraz, časování a zvuk

* ROM 0000h–3FFFh je chráněna proti zápisu, RAM 4000h–FFFFh má 48 KiB.
* Bitmapa 4000h–57FFh používá původní prokládané adresování řádků. Atributy
  5800h–5AFFh určují barvy buněk 8×8. FLASH obrací inkoust/papír každých 16 snímků.
* Pygame zobrazuje 256×192 bodů s 32bodovým rámečkem, celkem 320×256.
  Výchozí celočíselné zvětšení je 3×. Rámeček má poslední zapsanou barvu snímku;
  změny barvy uvnitř řádku/snímku se nevykreslují.
* Sudé porty dekódují A0 stejně jako ULA. Klávesové řádky vybírají horní adresní
  bity, které jsou v nule. Více vybraných řádků se logicky slučuje. Bit 6 je EAR
  (výchozí jednička), nezapojené liché porty vracejí FFh. Floating bus, klávesové
  ghosting a analogové vazby EAR/MIC/reproduktor nejsou modelovány.
* CPU má 3,5 MHz. Snímek je 69888 T-stavů, tedy 19,968 ms a přibližně 50,08 Hz.
  Spectrum používá neprokládaný obraz; zde jde o celý snímek. IRQ je aktivní prvních
  32 T-stavů každého snímku a při potvrzení přerušení vrací sběrnice FFh.
* CPU vykonává celé instrukce. Překročení konce snímku se přenáší do následujícího
  a nesčítá se jako dodatečný čas každého snímku. Přerušení je vzorkované mezi
  instrukcemi. Nejsou implementované WAIT/contention, přesné ULA fetch cykly,
  snow efekt ani přesné načasování portového zápisu uvnitř instrukce.
* Bit 4 portu FEh budí jednoduchý beeper. Změny se převádějí na PCM 44100 Hz,
  mono signed 16-bit. Bit 3 MIC se uchovává, ale neposílá do zvuku. Audio nemodeluje
  analogový filtr ani magnetofon. Když není zvukový výstup dostupný, emulátor
  pokračuje bez zvuku. Při přetížení hostitele může zvuk přeskakovat.

```sh
python -m zxspectrum --demo --scale 2 --mute
python -m zxspectrum --demo --frames 100 --no-limit --screenshot spectrum.png
```

`--scale` dovoluje 1–6, `--frames` ukončí běh po zadaném kladném počtu snímků.
`--no-limit` vypne čekání na skutečný čas. `--screenshot` uloží konečný obraz
v nativním rozlišení. Režim omezení rychlosti pouze čeká, pokud je hostitel
rychlejší; nestíhající běh nezrychluje a nevynechává instrukce CPU.

## Stihne Python snímek za 20 ms?

Ne vždy. Rozhoduje délka instrukcí a cena jejich implementace. Samé NOP
vyžadují 17472 volání dekodéru za snímek; instrukce HALT účtují také 4 T-stavy,
ale emulační smyčka při nich dělá méně práce. Delší instrukce mohou vyžadovat méně
volání, avšak jejich obsluha může být složitější. T-stavy tedy nejsou počet
instrukcí Pythonu ani přímo měřítko času hostitele.

Reprodukovatelné měření zahrnuje rozběh, CPU, RGB renderování, PCM a volitelně
Pygame zvětšení a flip:

```sh
python -m zxspectrum.benchmark --frames 80 --pygame
```

Příklad měření z 2026-11-06, sdílený cloudový hostitel x86_64, CPython 3.12.14,
Pygame 2.6.1. Pro každou zátěž 8 zahřívacích a 80 měřených snímků, bez čekání
na limit. Pygame používá **virtuální SDL displej**, zvětšení 3×, bez nákladů
skutečného okenního systému. Časy jsou v milisekundách:

| Zátěž | Medián CPU | Medián celkem | 95. percentil celkem | Maximum celkem |
| --- | ---: | ---: | ---: | ---: |
| NOP | 25,94 | 31,02 | 38,56 | 44,08 |
| HALT | 8,19 | 12,86 | 16,65 | 25,44 |
| Smyčka RAM/ALU | 19,64 | 24,38 | 30,44 | 33,07 |
| Barevná ukázka, převážně HALT | 8,58 | 13,45 | 17,72 | 19,93 |

Tato implementace tedy na tomto hostiteli **nezaručuje reálný čas 3,5 MHz**.
Pro lehčí zátěž jej splní, pro aktivní programy často ne. Výsledek není obecný
limit Pythonu; jiný procesor, PyPy nebo nativní/Cython implementace kritické
smyčky může dopadnout jinak. Měřte vlastní program a sledujte také nejpomalejší
snímky, nikoli jen průměr. Ukázka čekající v HALT není test plné herní zátěže.

## Testy a struktura

```sh
python -m unittest discover -s tests -v
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m zxspectrum --demo --frames 4 --no-limit --screenshot spectrum.png
```

Nové testy ověřují paměť, všech 40 kláves, dekódování ULA, IM1/IRQ/HALT,
hranice snímků, adresování a barvy obrazovky, zvukové vzorkování a běh Pygame
s virtuálním displejem i zvukovým zařízením. Pokud Pygame není nainstalováno,
je jeho integrační test přeskočen. S instalovaným Pygame prošlo všech 50 testů
repozitáře. Virtuální test nenahrazuje kontrolu fyzické klávesnice a reproduktoru.

`machine.py` obsahuje desku, `video.py` obrazový dekodér, `audio.py` beeper,
`demo.py` vlastní ROM, `__main__.py` frontend a `benchmark.py` měření výkonu.
Model desky a obrazový dekodér lze importovat bez Pygame. Kód používá stejnou
GPL-3.0 licenci jako zbytek repozitáře; viz `LICENSE`.
