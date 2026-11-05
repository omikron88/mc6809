; Custom RomWBW configuration for the base Zeta2 board, no ParPortProp.
; Copy to Source/HBIOS/Config/ZETA2_noppp.asm in a RomWBW checkout.
#INCLUDE "ZETA2_std.asm"
PPPENABLE       .SET FALSE
CRTACT          .SET FALSE
BOOTCON         .SET 0
