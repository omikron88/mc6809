# Emulátor Zeta SBC V2 v Pythonu

Emulace základní desky **Zeta2 bez ParPortProp**. Konzole používá vestavěný
UART 16550. Procesor vykonává instrukce prostřednictvím požadované knihovny
[omikron88/mc6809, src/z80](https://github.com/omikron88/mc6809/tree/main/src/z80).
Emulátor používá přímo balíček `src/z80` tohoto repozitáře; nic se nestahuje za běhu.

Požadavky: **Python 3.10 nebo novější**, standardní knihovna, terminál.
Z kořene repozitáře spusťte `python -m pip install -e .`. Testováno na Linuxu s Pythonem 3.12; větev obsluhy
terminálu pro Windows je implementovaná, ale nebyla zde ověřena.

## Rychlé spuštění

Po instalaci z kořene repozitáře spusťte:

```sh
python -m zeta2 --demo
```

Vestavěná ukázková ROM nastaví stránkování, inicializuje UART, vypíše hlášení
a opakuje znaky z klávesnice. Jde o skutečný program Z80 běžící na emulovaném
procesoru. Ukázka není CP/M ani RomWBW. Ukončení: **Ctrl-]**.
Ctrl-C se v režimu raw posílá hostovanému počítači, takže jej může používat CP/M.

Automaticky ukončená ukázka bez klávesnice:

```sh
python -m zeta2 --demo --headless --cycles 100000
```

## Grafický terminál VT100 připojený k UART

```sh
python -m zeta2 --demo --vt100
python -m zeta2 --rom ZETA2_noppp.rom --vt100 --ram zeta2.ram --rtc-state zeta2-rtc.json
```

Přepínač `--vt100` otevře samostatné okno s monochromatickou obrazovkou 80×24.
Výstup UART jde do parseru terminálu, stisky kláves i odpovědi na dotazy terminálu
se vracejí přes RBR emulovaného UART. Nepoužívá ParPortProp ani přímé volání BIOSu.
Ukázková ROM v tomto režimu vykreslí rámeček DEC, textové atributy a vstupní řádek.

Okno vyžaduje **Tkinter/Tk a grafické prostředí**. Na Debianu/Ubuntu lze Tkinter
doinstalovat balíčkem `python3-tk`; u Pythonu pro Windows bývá součástí instalace.
Bez `--vt100` funguje původní konzolový režim. `--headless` a `--vt100` se vylučují.
Zavření okna nebo Ctrl-] ukončí běh a uloží nakonfigurované obrazy paměti/disků.

Podporované funkce: kurzor CUP/HVP/CUU/CUD/CUF/CUB, ED/EL, CR/LF/BS/HT,
nastavitelné tabulátory, rolovací oblast DECSTBM, IND/RI/NEL, DECOM, DECAWM,
DECCOLM 80/132, DECSCNM, DECSC/DECRC, reset RIS, zarovnávací test DECALN,
ASCII/UK/DEC graphics (G0/G1, SI/SO), SGR tučné/podtržené/blikající/inverzní
písmo, DSR/CPR a identifikace DA. Parser uchovává stav mezi jednotlivými bajty.

Šipky respektují normální/aplikační režim DECCKM, F1–F4 posílají PF1–PF4.
Numerická klávesnice respektuje DECKPAM/DECKPNM. Enter posílá CR (v režimu LNM
CR+LF), Backspace/Delete posílají DEL, Ctrl-C posílá bajt 03h. Ctrl-Shift-V nebo
Shift-Insert vloží ASCII text ze schránky; řádky se převádějí na CR. Znaky mimo
ASCII se při vstupu vynechávají. Schránka se čte pouze na výslovný stisk vložení.

Jde o funkční podmnožinu VT100: není implementován režim VT52, dvojitá šířka/výška
řádků, hladké rolování, LED klávesnice, testy hardwaru ani XON/XOFF. Barevné SGR,
OSC, UTF-8 a moderní rozšíření xterm nejsou cílem tohoto terminálu. Zobrazení
rámečků používá Unicode glyfy lokálního fontu; UART samotný zůstává sedmibitový.
Grafická vrstva používá Tk Canvas a překresluje změněné buňky maximálně 30× za
sekundu. Parser a obousměrné připojení UART jsou automaticky otestované; vizuální
ověření Tk okna v tomto prostředí bez displeje nebylo možné.

## Vlastní firmware / RomWBW

```sh
python -m zeta2 --rom ZETA2_noppp.rom --ram zeta2.ram --rtc-state zeta2-rtc.json
```

`--rom` přijímá surový binární obraz o velikosti 1 až 524288 bajtů. Kratší obrazy
se doplní hodnotou FFh. Intel HEX není podporován. Pro systém s ROM diskem použijte
úplný 512KiB obraz určený pro **ZETA2**, nikoli ZETA V1 nebo jinou desku.

RomWBW ani CP/M nejsou v archivu přiložené. Kompletní start RomWBW / CP/M nebyl
ověřen: ověření zahrnuje vlastní ROM a cílené testy periferií. Kompatibilita
s libovolným konkrétním vydáním firmwaru proto není zaručena.

V [RomWBW](https://github.com/wwarthen/RomWBW) vytvořte vlastní konfiguraci
`Source/HBIOS/Config/ZETA2_noppp.asm` s obsahem přiloženého
`examples/zeta2/ZETA2_noppp.asm`. Vychází z `ZETA2_std.asm`, ale nastavuje:

```asm
PPPENABLE       .SET FALSE
CRTACT          .SET FALSE
BOOTCON         .SET 0
```

Standardní konfigurace RomWBW `ZETA2_std` může ParPortProp zapínat, přestože jej
základní konfigurace platformy vypíná. Použijte proto výslovnou konfiguraci bez PPP.
Sestavte ji podle návodu příslušné verze RomWBW (`Source/ReadMe.txt`). Emulátor
zobrazuje JP1 jako zapojený: bit CONFIG je v nule a volí sériovou konzoli.

## Diskety a trvalá paměť

```sh
python -m zeta2 --rom ZETA2_noppp.rom --disk-a cpm.img --disk-b data.img
```

Výchozí diskety jsou chráněné proti zápisu. Zápis a uložení povolíte:

```sh
python -m zeta2 --rom ZETA2_noppp.rom --disk-a pracovni-kopie.img --disk-write --ram zeta2.ram
```

Podporovány jsou RAW obrazy se sektory 512 B: 160, 180, 320, 360, 720, 1200
a 1440 KiB. Geometrie se určuje z délky souboru. IMD, DSK, flux a nestandardní
velikosti sektorů nejsou podporované. Obsah CP/M musí odpovídat geometrii a
formátu, který očekává firmware. Běžný harddiskový obraz RomWBW nelze připojit
jako disketu.

Změny obrazu disku, SRAM a RTC se ukládají při řádném ukončení, dosažení limitu
cyklů nebo KeyboardInterrupt. Soubory se nahrazují přes dočasný soubor. Násilné
ukončení procesu může neuložené změny ztratit. SRAM má přesně 512 KiB.

RTC začíná místním časem hostitele, případně časem z `--rtc-time 2026-11-05T12:00:00`.
Potom postupuje podle emulovaných cyklů CPU. Uložený RTC stav během vypnutého
emulátoru nepostupuje. To zajišťuje opakovatelné běhy; nejde o běžící hodiny hostitele.

## Parametry a diagnostika

```sh
python -m zeta2 --help
python -m zeta2 --demo --headless --cycles 50000 --trace-io io.log
python -m unittest discover -s tests -v
```

`--hz` určuje frekvenci emulovaného CPU (výchozí 8000000 Hz). `--realtime` omezuje
rychlost na tuto frekvenci, pokud ji hostitel zvládá; nezrychluje pomalejší běh.
Bez tohoto přepínače emulátor běží maximální rychlostí Pythonu. Nejde o příslib
výkonu 8 MHz. Při změně `--hz` upravte také konfiguraci firmwaru.

`--stop-on-halt` zastaví běh po HALT; běžně jej nepoužívejte pro systémy,
které HALT využívají k čekání na přerušení. Bez přepínače čas a přerušení během
HALT pokračují. `--cycles` je limit T-stavů, který lze překročit o jednu instrukci.

`--input soubor` zařadí bajty do přijímací fronty před startem. Firmware ji může
během inicializace UART vyprázdnit; pro interaktivní práci používejte terminál.
`--trace-io` zapisuje čas CPU, směr, celý 16bitový port a hodnotu. Při dekódování
desky se používá dolních osm bitů adresy portu.

## Implementované zařízení a hranice věrnosti

| Část | Implementace |
| --- | --- |
| Z80 | Přiložené jádro z požadovaného repozitáře; paměťové a I/O callbacky, IRQ, IM2, HALT. |
| MMU | 4 × 16 KiB, 512 KiB ROM + 512 KiB SRAM. Po resetu ROM stránka 0 ve všech bankách. MPGENA používá bit 0. Selektory jsou 7bitové; stránky 64–127 nemají osazenou paměť a vracejí FFh. |
| UART 16550 | RBR/THR, IER/IIR, DLAB/divisor, LCR, MCR, LSR, MSR, scratch, FIFO identifikace/reset, loopback, RX/TX přerušení přes CTC2. Přenos je okamžitý, bez časování baudů. Hostitelská RX fronta nemá limit 16 bajtů; nejsou emulovány FIFO timeouty, prahy, modemové změny a chyby linky. |
| CTC | Čtyři časovače/čítače, prescalery 16/256, konstanty 1–256, řetězení CH0→CH1, externí takt 921600 Hz na CH0, hrany UART→CH2, priority, vektory a RETI. Časování má přesnost jedné instrukce. |
| PPI 8255 | Registry režimu 0, směry vstup/výstup, BSR, aliasy portů. Volné vstupy vracejí jedničky. Handshake režimů 1/2 a přerušení PPI nejsou implementovány. Žádné PPP, VGA, PS/2 ani SD. |
| WD37C65 | SPECIFY, SENSE DRIVE/INTERRUPT, SEEK, RECALIBRATE, READ ID, READ/WRITE DATA, READ TRACK a FORMAT TRACK, výsledkové fáze, reset DOR a terminal count. Funkční PIO přenosy, bez DMA, rotačních prodlev a přesného časování. READ TRACK je zjednodušen na sektory, READ ID vrací první sektor. Deleted data a SCAN nejsou implementovány. |
| DS1302 | Bitové rozhraní na 70h, BCD čas, 12/24hodinový režim, CH, WP, registry trickle charger, 31 B RAM, jednotlivé i burst přenosy. Kalendář používá datum Pythonu; zápis registru dne v týdnu se samostatně neuchovává a neplatné mezihodnoty data se ignorují. |
| Flash | Čtení ROM; programovací/mazací sekvence flash nejsou implementovány. |

Neosazené porty a čtení write-only registrů vracejí FFh. Bit disk-change je
stále nula; výměna média za běhu není implementována. Po resetu se obsah MMU
registrů deterministicky nastavuje na nulu, ačkoli skutečný hardware jej má
nedefinovaný. SRAM při prvním spuštění obsahuje nuly.

## Struktura a původ

`src/zeta2/machine.py` propojuje CPU a sběrnici, `devices.py` obsahuje UART/PPI/CTC/RTC,
`floppy.py` řadič a obrazy disket, `demo.py` sestavuje ukázkovou ROM,
`vt100.py` obsahuje model terminálu, `vt100_gui.py` jeho Tk okno a
`__main__.py` poskytuje příkazovou řádku.

Hardware vychází z dokumentace [skiselev/zeta_sbc](https://github.com/skiselev/zeta_sbc).
Detaily resetu FDC, polarity RTC /WE, konzole a MMU byly porovnány se zdroji
RomWBW `fd.asm`, `dsrtc.asm`, `cfg_ZETA2.asm` a `Config/ZETA2_std.asm`.
Rozpory v README desky: porty 7Ch–7Fh jsou zde enable paging, nikoli aliasy
page-select; povolení stránkování používá bit 0, jak uvádí konfigurace RomWBW.

Jádro Z80: autor **omikron88**, repozitář `omikron88/mc6809`, commit
`88b546eae18bf46ce128e460786ba20a68a133da` (2026-10-29). Jádro `src/z80` zůstává beze změn. Vlastní emulátor desky a testy byly vytvořeny 2026-11-05.
Celý projekt je poskytován pod **GPL-3.0**, bez záruky; úplné znění je v `LICENSE`.

Ověření: 36 automatických testů pokrývá MMU/reset, skutečnou Z80 ukázku a echo,
UART/PPI, CTC a IM2/RETI, sériové RTC transakce, disketové operace, CLI,
parser VT100, vstup kláves a dotazy/odpovědi přes UART.
Nejde o úplnou certifikaci všech periferních režimů nebo instrukcí CPU.
