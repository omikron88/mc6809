# mc6809

A small, dependency-free Python emulation library for the Motorola MC6809 and
Hitachi HD6309. The CPU has no built-in RAM: **every memory access is performed
through host callbacks**. This permits bank switching, memory-mapped devices,
breakpoints, and bus tracing without modifying the CPU.

## Quick start

```python
from mc6809 import MC6809

memory = bytearray(65536)
def Read(address: int) -> int:
    return memory[address]
def Write(address: int, value: int) -> None:
    memory[address] = value

memory[0xfffe:0x10000] = (0x1000).to_bytes(2, "big")
memory[0x1000:0x1005] = bytes([0x86, 0x2a, 0x8b, 0x10, 0x12])

cpu = MC6809(Read, Write)
cpu.reset()
cpu.step()                  # LDA #$2a
cpu.step()                  # ADDA #$10
assert cpu.r.a == 0x3a
```

Use `HD6309(Read, Write)` for the enhanced variant. Registers are intentionally
public in `cpu.r`; 16/32-bit `d`, `w`, and `q` properties keep their component
registers synchronized. `step()` returns instruction cycles, `run(n)` executes
whole instructions to a cycle budget, and `cpu.cycles` contains the total.

## Host interface

* `Read(address) -> int` is called once per byte read. Addresses are masked to
  16 bits and results to 8 bits.
* `Write(address, value)` is called once per byte write, with both values masked.
* `irq(bool)` and `firq(bool)` set level-sensitive interrupt lines; `nmi()`
  latches an edge. Interrupt vectors and reset vector are fetched through Read.
* `IllegalInstruction` reports the instruction address, prefix page, and opcode.

The implementation covers the complete regular 6809 ALU/addressing matrix,
branches, stack and control instructions, all indexed postbyte forms, and
interrupt entry/return. The 6309 class exposes E/F, W, V, Q and MD and implements
register transfer plus common E/F and MD instructions. Remaining specialised
6309 operations deliberately raise `IllegalInstruction` rather than silently
behaving as a 6809 instruction, providing a safe extension point.

## Accuracy and integration

Cycle values model documented instruction-level timing. Callback accesses are
in architectural byte order, but dummy/internal bus cycles are not emitted.
Consequently this core is intended for machine emulation and tooling rather
than electrical, cycle-pin-exact simulation.

Install for development and run tests:

```sh
python -m pip install -e .
```


# Jednoduchý assembler 6809/6309

`assembler.py` je dvouprůchodový assembler bez externích závislostí. Tabulku
mnemonik, opcodů a adresovacích režimů nepřepisuje: používá přímo veřejná data
z `ins6809.py`. Výchozí cílový procesor je Hitachi 6309; přepínačem `--cpu
6809` se instrukce a registry dostupné pouze na 6309 odmítnou.

## Použití

```sh
python -m mc6809 program.asm -o program.bin
python -m mc6809 program.asm -o program.hex --format hex --cpu 6809
python -m mc6809 program.asm -o oblast.bin --trim --fill 0xff
```

Binární výstup má standardně přesně 65536 bajtů a mezery vyplňuje hodnotou z
`--fill` (výchozí je nula). `--trim` uloží pouze souvislý úsek od nejnižší do
nejvyšší použité adresy. Intel HEX obsahuje jen skutečně použité oblasti, takže
nesouvislé bloky nevytvářejí zbytečná data.

## Syntaxe

* návěští lze psát s dvojtečkou, `konstanta EQU výraz` také bez ní;
* čísla: `$CAFE`, `0xCAFE`, `%1010`, desetinná čísla a znakové konstanty;
* výrazy podporují `+ - * // % << >> & | ^ ~` a `*` jako aktuální adresu;
* funkce `Hi(výraz)` vrátí bity 15–8 a `Lo(výraz)` bity 7–0; názvy funkcí
  nerozlišují velikost písmen;
* `<výraz` vynutí direct, `>výraz` extended adresování;
* podporováno je immediate, direct, extended, relativní a úplné běžné
  indexované adresování 6809 včetně nepřímého a PCR; rovněž W formy 6309;
* registry pro `TFR`, `EXG`, `PSH*`, `PUL*`, `TFM` a bitové instrukce 6309 se
  převádějí na příslušný postbyte.

Direktivy jsou `ORG`, `EQU`/`SET`, `DB`/`FCB`/`BYTE`, `DW`/`FDB`/`WORD`,
`RMB`/`DS`, `FILL hodnota,počet` a `END`. Řetězec v `DB` se zapisuje v Latin-1.

```asm
        org $F000
start:  ldx #text
loop:   lda ,x+
        beq hotovo
        sta $0400
        bra loop
hotovo: rts
text:   db "Ahoj!", 0
vektor: dw start
        lda #Hi(vektor)  ; horní bajt adresy
        ldb #Lo(vektor)  ; spodní bajt adresy
```

Při automatické volbě se adresa `$00..$FF` zakóduje jako direct, ostatní jako
extended. U dopředného odkazu proběhne opakované ustálení rozložení; tam, kde
má mít symbol záměrně direct režim, je přesto nejčitelnější použít `<symbol`.

## Z80 a Intel 8080

Nový balíček [`z80`](Z80.md) obsahuje emulátor Z80 s pamětí a porty přes
callbacky, úplný katalog dokumentovaných instrukcí, assembler a disassembler.
Příznak `Instruction.is_i8080` označuje instrukce sdílející dokumentované
kódování s Intel 8080; assembler nabízí přepínač `--i8080-only`.

Balíček `z80` poskytuje tabulku instrukcí, emulátor, assembler a disassembler
bez běhových závislostí. Je součástí stejné distribuce jako `mc6809` a nemění
jeho API. Vyžaduje Python 3.10 nebo novější.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Emulátor

```python
from z80 import Z80

memory = bytearray(65536)
memory[:7] = bytes.fromhex('3e 2a c6 10 32 00 80')
cpu = Z80(memory.__getitem__, memory.__setitem__)
cpu.step()                        # LD A,$2A
cpu.step()                        # ADD A,$10
cpu.step()                        # LD ($8000),A
assert memory[0x8000] == 0x3a
```

Každý přístup do paměti používá `read(address) -> byte` nebo
`write(address, byte)`. Adresy se maskují na 16 bitů a bajty na 8 bitů.
Volitelné `fetch(address) -> byte` odděluje čtení opcode v cyklu
**MREQ+M1** od běžného `read`. Bez něj se pro fetch použije `read`.
Volitelné `intack() -> byte` dodá bajt při potvrzení maskovatelného přerušení
**IORQ+M1**. Volá se právě jednou při přijetí INT ve všech režimech:
v IM 0 dodá opcode, v IM 2 dolní bajt adresy vektorové tabulky a v IM 1
se vrácená hodnota ignoruje. Bez něj se použije hodnota `data` z `irq()`
(výchozí `$FF`). Návratové hodnoty obou callbacků se maskují na 8 bitů.

```python
cpu = Z80(read, write, fetch=fetch_opcode, intack=interrupt_acknowledge)
```

Operandy, displacementy, zásobník a čtení vektorové tabulky IM 2 používají
`read`. Prefixy CB/ED/DD/FD i následující M1 opcode používají `fetch`;
poslední opcode u DD/FD CB se podle skutečného cyklu čte přes `read`, stejně
jako displacement. HALT a potvrzení NMI provedou ignorované čtení přes
`fetch` z aktuálního PC bez jeho inkrementace. NMI nevolá `intack`.
Callbacky zůstávají zachované při `reset()` a lze je měnit přes `cpu.fetch`
a `cpu.intack`. Tato rozlišení nemodelují jednotlivé hrany sběrnicových signálů.

Volitelné callbacky `input_port(port) -> byte` a `output_port(port, byte)`
dostávají celou 16bitovou adresu portu. Bez nich čtení vrací `$FF` a zápis
nic neprovádí.

Registry jsou veřejné v `cpu.r`: `a`, `f`, `b`, `c`, `d`, `e`, `h`, `l`,
`af`, `bc`, `de`, `hl`, `ix`, `iy`, `sp`, `pc`, `i`, `r` a alternativní
registry se suffixem `_alt`. Dvojice jsou synchronizované s bajtovými registry.
`reset()` vytvoří deterministický počáteční stav (PC 0, SP $FFFF, ostatní
registry 0); nejde o slib hodnot nedefinovaných skutečným hardwarem.

`step()` vrátí počet T-stavů, `cpu.cycles` obsahuje jejich součet.
`run(budget)` provede celé instrukce do dosažení nebo překročení rozpočtu a
vrátí skutečně spotřebované T-stavy. HALT zastaví vykonávání programu, další
kroky účtují obnovovací cykly do přerušení. `cpu.halted` hlásí tento stav.

`irq(active=True, data=0xff)` nastaví úrovňový INT a bajt na sběrnici;
`nmi()` zachytí hranu NMI. Podporované jsou IM 0/1/2, zpoždění EI,
RETI/RETN, `iff1`, `iff2`, `im` a obnovovací registr R. V IM 0 může
sběrnicový bajt obsahovat libovolný opcode; jeho další bajty se čtou z PC.
Řadič přerušení a zařízení v daisy chain spravuje hostitel.

## Instrukce a Intel 8080

```python
from z80 import INSTRUCTIONS, BY_OPCODE

assert BY_OPCODE[bytes.fromhex('80')].text == 'ADD A,B'
assert BY_OPCODE[bytes.fromhex('80')].is_i8080
assert not BY_OPCODE[bytes.fromhex('ed 44')].is_i8080  # NEG
common = [i for i in INSTRUCTIONS if i.is_i8080]
assert len(common) == 244
```

Jedna položka `Instruction` popisuje konkrétní kódování: `mnemonic`,
`operands`, `opcode`, `byte_count`, `cycles`, `cycles_taken`, `is_i8080`,
`undocumented` a `displacement_before_opcode`. Časování je vždy pro Z80;
`cycles_taken` uvádí alternativu při provedeném podmíněném skoku nebo
opakované blokové instrukci.

**`is_i8080` znamená dokumentovanou instrukci Intel 8080 se stejným
opcodem a kódováním operandů.** Používáme názvosloví Zilog: například
`LD B,C` odpovídá `MOV B,C`, `JP (HL)` odpovídá `PCHL` a `EX DE,HL`
odpovídá `XCHG`. Příznak nezaručuje stejné časování ani stejné příznakové
bity; Z80 má například overflow pro aritmetiku místo parity 8080.
Není to samostatný emulátor 8080 ani parser jeho mnemonik.

Katalog obsahuje 1 268 forem: všechny dokumentované instrukce Z80 a běžné
nedokumentované formy (IXH/IXL/IYH/IYL, SLL, indexované CB s výsledkem
v registru a aliasy ED). IX/IY displacement se při DD/FD CB ukládá **před**
poslední opcode, přestože pole `opcode` obsahuje jen pevné bajty.
Opakované a ignorované DD/FD prefixy řeší emulátor a disassembler dynamicky;
nejsou vypsané jako nekonečná sada položek. Nedefinované ED opcodes se
vykonávají jako dvoubajtové NOP.

Jde o instrukční model standardního NMOS Z80, nikoli o pinově přesnou
simulaci: nemodeluje WAIT, BUSREQ, contention, interní WZ/Q latch ani všechny
odchylky nedokumentovaných příznaků konkrétních revizí čipu. Nejde o Z180,
eZ80 či instrukce Z80N. Sada testů ověřuje katalog, roundtrip assembleru a
disassembleru, spuštění všech forem a cílené výsledky operací; nenahrazuje
úplnou externí hardwarovou konformanční sadu.

## Assembler a disassembler

```python
from z80 import Assembler, disassemble_one, format_line

result = Assembler().assemble('''
    org $1000
start: ld ix,$8000
    ld (ix-2),42
    djnz start
    halt
''')
print(format_line(disassemble_one(result.memory.__getitem__, 0x1000)))
image = result.binary()             # 65536 bajtů, výchozí výplň nula
compact = result.binary(full=False) # nejnižší až nejvyšší použitá adresa
hex_text = result.intel_hex()
```

Assembler podporuje Zilog syntaxi, dopředná návěští v instrukcích,
`ORG`, `EQU`, `DB`/`DEFB`/`BYTE`, `DW`/`DEFW`/`WORD`, `DS`/`RMB` a `END`.
Čísla mohou být desetinná, `$ABCD`, `0xABCD` nebo `0ABCDh`. Výrazy dovolují
aritmetiku, bitové operace a závorky ve výrazech datových direktiv.
`$` jako samostatný výraz znamená aktuální adresu. Layout direktivy a EQU
vyžadují již známé symboly. Relativní skoky přijímají cílovou adresu,
indexované operandy znaménkový displacement -128 až 127. Makra, sekce a
linkování nejsou implementovány.

```sh
python -m z80 program.asm -o program.bin
python -m z80 program.asm -o program.hex --format hex
python -m z80 program.asm -o program.bin --trim --i8080-only
python -m z80 program.asm -o program.bin --undocumented
```

`Assembler(i8080_only=True)` i `--i8080-only` odmítnou instrukce bez příznaku
`is_i8080`. Nedokumentované instrukce vyžadují
`Assembler(allow_undocumented=True)` nebo `--undocumented`.

`disassemble_one(read8, address)` vrací `Decoded` s původní adresou,
spotřebovanými bajty, metadaty instrukce, textem operandů a následující
adresou. `format_line()` připraví řádek výpisu.
