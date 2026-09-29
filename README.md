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
python3 asm6809.py program.asm -o program.bin
python3 asm6809.py program.asm -o program.hex --format hex --cpu 6809
python3 asm6809.py program.asm -o oblast.bin --trim --fill 0xff
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
