<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
--->

## How it works

This project implements a **single-cycle combinational floating-point multiplier** using a custom 15-bit format called **SEM15** (1 sign / 6 exponent / 8 mantissa, bias = 31), targeting the TinyTapeout GF180MCU platform in a single 1×1 tile.

Unlike the common IEEE 754 float, SEM15 is a compact custom format designed to fit an entire multiply-accumulate datapath inside a small tile. There is no Q8.8 encoder or decoder — the host sends and receives raw SEM15 values directly over the byte-serial IO protocol.

### SEM15 Format

| Field | Bits | Description |
|-------|------|-------------|
| Sign | `[14]` | 0 = positive, 1 = negative |
| Exponent | `[13:8]` | 6-bit biased, bias = 31 |
| Mantissa | `[7:0]` | 8-bit stored fraction, implicit leading 1 |

- Dynamic range: 2⁻³¹ to 2³¹
- Precision: ~2.4 decimal digits
- Zero: `15'h0000`
- Overflow saturates to `{sign, 6'd62, 8'hFF}`
- Underflow flushes to zero. No NaN, no Inf.

### Architecture

The entire design is a single combinational path between two registered inputs and one registered output — no pipeline stages.

```
  ui_in (SEM15 bytes, byte serial)
        │
   [a_reg / b_reg]    ← only registers in the design
        │
      sem15_mul        ← 9x9 unsigned mantissa multiply + normalize + round
        │
   [result_reg]        ← latches on FIRE posedge
        │
     uo_out (SEM15)

  Latency : 1 clock after FIRE
  Cells   : 706  (fits 1x1 tile)
```

**sem15_mul** — unpack sign/exp/mantissa, add exponents (`Ea + Eb − 31`), 9×9 unsigned mantissa multiply → 18-bit product, normalize (leading 1 at bit 16 or 17), round-to-nearest, saturate on overflow/underflow.

### IO Protocol

SEM15 is 15 bits, loaded as two bytes. The host drives `uio_in` for commands.

| Pin | Dir | Function |
|-----|-----|----------|
| `ui[7:0]` | IN | 8-bit data bus |
| `uo[7:0]` | OUT | Result byte |
| `uio[0]` | OUT | `out_valid` — 1-cycle pulse 1 clock after FIRE |
| `uio[3:2]` | IN | CMD: `00`=NOP `01`=LOAD_A `10`=LOAD_B `11`=FIRE |
| `uio[4]` | IN | BYTE_SEL: `0`=low byte `1`=high byte |
| `uio[6]` | IN | RESULT_HI: `0`=`uo_out=result[7:0]` `1`=`result[14:8]` |

### SEM15 byte loading

SEM15 is 15 bits wide, split across two bytes:

```
Low byte  (BYTE_SEL=0): ui_in[7:0]  -> operand[7:0]   (mantissa)
High byte (BYTE_SEL=1): ui_in[6:0]  -> operand[14:8]  (sign + exponent)
                         ui_in[7] is ignored
```

## How to test

Load operands A and B as raw SEM15 values byte-serially, send FIRE, then read the result on the next clock.

### Host sequence (one multiply)

```
cycle 1 : CMD=LOAD_A, BYTE_SEL=0, ui_in = a[7:0]
cycle 2 : CMD=LOAD_A, BYTE_SEL=1, ui_in = a[14:8]  (bit7 ignored)
cycle 3 : CMD=LOAD_B, BYTE_SEL=0, ui_in = b[7:0]
cycle 4 : CMD=LOAD_B, BYTE_SEL=1, ui_in = b[14:8]
cycle 5 : CMD=FIRE
cycle 6 : out_valid=1  →  read result
          RESULT_HI=0  →  uo_out = result[7:0]
          RESULT_HI=1  →  uo_out = {1'b0, result[14:8]}
```

### SEM15 encoding examples

| Value | SEM15 (hex) | Calculation |
|-------|-------------|-------------|
| 1.0 | `0x1F00` | exp=31, mant=0x00 |
| 2.0 | `0x2000` | exp=32, mant=0x00 |
| 1.5 | `0x1F80` | exp=31, mant=0x80 |
| 0.5 | `0x1E00` | exp=30, mant=0x00 |
| -1.0 | `0x5F00` | sign=1, exp=31, mant=0x00 |

### Running the cocotb testbench

```sh
cd test
make
```

| Test | A | B | Expected |
|------|---|---|----------|
| `test_one_times_two` | 1.0 | 2.0 | 2.0 |
| `test_fraction` | 1.5 | 2.0 | 3.0 |
| `test_negative` | −1.0 | 3.0 | −3.0 |
| `test_both_negative` | −2.0 | −3.0 | 6.0 |
| `test_zero` | 0.0 | 5.0 | 0.0 |
| `test_saturation` | 1e10 | 1e10 | maxpos (overflow) |
| `test_small` | 0.25 | 0.25 | 0.0625 |
| `test_large` | 7.5 | 3.0 | 22.5 |

## External hardware

None. The host microcontroller (e.g. RP2040 on the TT demo board) drives `ui_in` and `uio_in` directly over GPIO.
