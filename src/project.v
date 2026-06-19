/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */


// tt_um_sem15_mul.v — TinyTapeout SEM15 Raw Multiplier
// SEM15: 1s/6e/8m, bias=31. Raw SEM15 in/out, no Q8.8 encoder/decoder.
// Fully combinational. Result valid 1 clock after FIRE.
//
// PINOUT
//   ui_in[7:0]   : data bus (operand bytes, byte-serial)
//   uo_out[7:0]  : result byte
//   uio[0]       : out_valid (OUTPUT) — pulses 1 cycle after FIRE
//   uio[3:2]     : CMD  00=NOP 01=LOAD_A 10=LOAD_B 11=FIRE  (INPUT)
//   uio[4]       : BYTE_SEL  0=low byte 1=high byte          (INPUT)
//   uio[6]       : RESULT_HI 0=result[7:0] 1=result[14:8]   (INPUT)
//   uio[1,5,7]   : unused
//
// SEM15 is 15 bits. Loaded as 2 bytes:
//   LOAD (BYTE_SEL=0): ui_in[7:0]  -> operand[7:0]   (mantissa + low exp)
//   LOAD (BYTE_SEL=1): ui_in[6:0]  -> operand[14:8]  (sign + high exp)
//                      (ui_in[7] ignored on high byte)
//
// Read result:
//   RESULT_HI=0 -> uo_out = result[7:0]
//   RESULT_HI=1 -> uo_out = {1'b0, result[14:8]}
`default_nettype none
`timescale 1ns/1ps

module tt_um_sem15_mul (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    assign uio_oe = 8'b0000_0011; // uio[0]=out, uio[1]=out(unused), rest=in

    wire [1:0] cmd      = uio_in[3:2];
    wire       byte_sel = uio_in[4];
    wire       res_hi   = uio_in[6];

    localparam CMD_NOP    = 2'b00;
    localparam CMD_LOAD_A = 2'b01;
    localparam CMD_LOAD_B = 2'b10;
    localparam CMD_FIRE   = 2'b11;

    // Input registers — store raw SEM15 (15-bit), loaded byte by byte
    reg [14:0] a_reg, b_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_reg <= 15'h0000;
            b_reg <= 15'h0000;
        end else begin
            case (cmd)
                CMD_LOAD_A: begin
                    if (!byte_sel) a_reg[7:0]  <= ui_in;
                    else           a_reg[14:8] <= ui_in[6:0];
                end
                CMD_LOAD_B: begin
                    if (!byte_sel) b_reg[7:0]  <= ui_in;
                    else           b_reg[14:8] <= ui_in[6:0];
                end
                default: ;
            endcase
        end
    end

    // SEM15 combinational multiplier
    wire [14:0] product;
    sem15_mul mul_inst (.a(a_reg), .b(b_reg), .product(product));

    // Output register — latch on FIRE
    reg [14:0] result_reg;
    reg        out_valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result_reg <= 15'h0000;
            out_valid  <= 1'b0;
        end else begin
            out_valid <= (cmd == CMD_FIRE);
            if (cmd == CMD_FIRE)
                result_reg <= product;
        end
    end

    assign uo_out     = res_hi ? {1'b0, result_reg[14:8]} : result_reg[7:0];
    assign uio_out[0] = out_valid;
    assign uio_out[1] = 1'b0;
    assign uio_out[7:2] = 6'b000000;

    wire _unused = &{ena, uio_in[7], uio_in[5], uio_in[1:0], 1'b0};
endmodule


// SEM15 (1s/6e/8m, bias=31) combinational multiplier
// No pipeline registers. Result valid same cycle as inputs.
module sem15_mul (
    input  wire [14:0] a,
    input  wire [14:0] b,
    output wire [14:0] product
);
    wire        sa = a[14], sb = b[14];
    wire [5:0]  ea = a[13:8],  eb = b[13:8];
    wire [8:0]  ma = (ea == 6'd0) ? 9'd0 : {1'b1, a[7:0]};
    wire [8:0]  mb = (eb == 6'd0) ? 9'd0 : {1'b1, b[7:0]};
    wire        za = (ea == 6'd0), zb = (eb == 6'd0);
    wire        sgn = sa ^ sb;

    wire [7:0]  esum  = {2'b00, ea} + {2'b00, eb} - 8'd31;
    wire [17:0] p     = ma * mb;
    wire        ovf   = p[17];
    wire [8:0]  mfrac = ovf ? p[17:9] : p[16:8];
    wire [7:0]  efin  = esum + {7'b0, ovf};
    wire        grd   = ovf ? p[8]    : p[7];
    wire        stk   = ovf ? |p[7:0] : |p[6:0];
    wire        rndup = grd & (stk | mfrac[0]);
    wire [9:0]  mrnd  = {1'b0, mfrac} + {9'b0, rndup};
    wire        mcar  = mrnd[9];
    wire [7:0]  efin2 = efin + {7'b0, mcar};
    wire [7:0]  mout  = mcar ? 8'd0 : mrnd[7:0];
    wire        uflow = (za | zb) | efin2[7] | (efin2 == 8'd0);
    wire        oflow = (~efin2[7]) & (efin2 >= 8'd63);

    assign product = uflow ? {sgn, 14'd0}        :
                     oflow ? {sgn, 6'd62, 8'hFF} :
                             {sgn, efin2[5:0], mout};
endmodule
