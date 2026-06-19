"""
test.py — SEM15 Raw Multiplier cocotb testbench
SEM15: 1s/6e/8m, bias=31. Raw SEM15 in/out, no Q8.8 conversion.

Protocol:
  uio_in[3:2] = CMD  00=NOP 01=LOAD_A 10=LOAD_B 11=FIRE
  uio_in[4]   = BYTE_SEL  0=low byte  1=high byte
  uio_in[6]   = RESULT_HI 0=result[7:0]  1=result[14:8]
  uio_out[0]  = out_valid (pulses 1 cycle after FIRE)

SEM15 encoding:
  bit[14]   = sign
  bits[13:8]= exponent (bias=31)
  bits[7:0] = mantissa (implicit leading 1)
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles

CMD_NOP    = 0b00
CMD_LOAD_A = 0b01
CMD_LOAD_B = 0b10
CMD_FIRE   = 0b11

def mk_uio(cmd=0, byte_sel=0, res_hi=0):
    return (cmd << 2) | (byte_sel << 4) | (res_hi << 6)

# -------------------------------------------------------
# SEM15 encode/decode helpers
# -------------------------------------------------------
def float_to_sem15(v: float) -> int:
    """Convert float to 15-bit SEM15 integer."""
    if v == 0.0:
        return 0
    sign = 1 if v < 0 else 0
    v = abs(v)
    import math
    exp_unbiased = math.floor(math.log2(v))
    biased_exp   = exp_unbiased + 31
    biased_exp   = max(1, min(62, biased_exp))
    mantissa_f   = v / (2 ** exp_unbiased) - 1.0   # fractional part after implicit 1
    mantissa_i   = int(round(mantissa_f * 256)) & 0xFF
    return (sign << 14) | (biased_exp << 8) | mantissa_i

def sem15_to_float(raw: int) -> float:
    """Convert 15-bit SEM15 integer to float."""
    if (raw & 0x7FFF) == 0:
        return 0.0
    sign  = (raw >> 14) & 1
    exp   = (raw >> 8) & 0x3F
    mant  = raw & 0xFF
    value = (1 + mant / 256.0) * (2 ** (exp - 31))
    return -value if sign else value

# -------------------------------------------------------
# Protocol helpers
# -------------------------------------------------------
async def reset(dut):
    dut.rst_n.value  = 0
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 3)

async def load_sem15(dut, cmd, val: int):
    """Load a 15-bit SEM15 value (2 bytes)."""
    await FallingEdge(dut.clk)
    dut.ui_in.value  = val & 0xFF
    dut.uio_in.value = mk_uio(cmd=cmd, byte_sel=0)
    await FallingEdge(dut.clk)
    dut.ui_in.value  = (val >> 8) & 0x7F
    dut.uio_in.value = mk_uio(cmd=cmd, byte_sel=1)
    await FallingEdge(dut.clk)
    dut.ui_in.value  = 0
    dut.uio_in.value = mk_uio(cmd=CMD_NOP)

async def multiply(dut, a: float, b: float) -> float:
    """Load A and B as SEM15, fire, read result. Returns float."""
    a_raw = float_to_sem15(a)
    b_raw = float_to_sem15(b)
    await load_sem15(dut, CMD_LOAD_A, a_raw)
    await load_sem15(dut, CMD_LOAD_B, b_raw)
    # FIRE
    await FallingEdge(dut.clk)
    dut.uio_in.value = mk_uio(cmd=CMD_FIRE)
    await RisingEdge(dut.clk)   # result registered
    await FallingEdge(dut.clk)
    # Read low byte
    dut.uio_in.value = mk_uio(res_hi=0)
    await RisingEdge(dut.clk)
    lo = dut.uo_out.value.to_unsigned()
    # Read high byte
    await FallingEdge(dut.clk)
    dut.uio_in.value = mk_uio(res_hi=1)
    await RisingEdge(dut.clk)
    hi = dut.uo_out.value.to_unsigned() & 0x7F
    dut.uio_in.value = 0
    return sem15_to_float((hi << 8) | lo)

# -------------------------------------------------------
# Tests
# -------------------------------------------------------
@cocotb.test()
async def test_one_times_two(dut):
    """1.0 x 2.0 = 2.0"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 1.0, 2.0)
    dut._log.info(f"1.0 x 2.0 = {r:.4f}  expect 2.0")
    assert abs(r - 2.0) < 0.1

@cocotb.test()
async def test_fraction(dut):
    """1.5 x 2.0 = 3.0"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 1.5, 2.0)
    dut._log.info(f"1.5 x 2.0 = {r:.4f}  expect 3.0")
    assert abs(r - 3.0) < 0.1

@cocotb.test()
async def test_negative(dut):
    """-1.0 x 3.0 = -3.0"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, -1.0, 3.0)
    dut._log.info(f"-1.0 x 3.0 = {r:.4f}  expect -3.0")
    assert abs(r - (-3.0)) < 0.1

@cocotb.test()
async def test_both_negative(dut):
    """-2.0 x -3.0 = 6.0"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, -2.0, -3.0)
    dut._log.info(f"-2.0 x -3.0 = {r:.4f}  expect 6.0")
    assert abs(r - 6.0) < 0.1

@cocotb.test()
async def test_zero(dut):
    """0.0 x 5.0 = 0.0"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 0.0, 5.0)
    dut._log.info(f"0.0 x 5.0 = {r:.4f}  expect 0.0")
    assert abs(r) < 0.01

@cocotb.test()
async def test_saturation(dut):
    """1e10 x 1e10 -> overflow -> maxpos"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 1e10, 1e10)
    dut._log.info(f"1e10 x 1e10 = {r:.4e}  expect maxpos")
    assert r > 1e8  # saturated to large value

@cocotb.test()
async def test_small(dut):
    """0.25 x 0.25 = 0.0625"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 0.25, 0.25)
    dut._log.info(f"0.25 x 0.25 = {r:.4f}  expect 0.0625")
    assert abs(r - 0.0625) < 0.02

@cocotb.test()
async def test_large(dut):
    """7.5 x 3.0 = 22.5"""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    r = await multiply(dut, 7.5, 3.0)
    dut._log.info(f"7.5 x 3.0 = {r:.4f}  expect 22.5")
    assert abs(r - 22.5) < 0.5
