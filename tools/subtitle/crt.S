/* SUB.BIN entry points, loaded at BASE = 0x06086340 by the 32-byte stub in MAIN.BIN.

   The stub reads the magic word at BASE+0x10 through the cache before SUB.BIN is loaded,
   so that cache line may hold stale data.  The first 16-byte line therefore purges the
   whole cache before anything past it is fetched.  The loader hook always runs first in
   a scene (pictures are loaded before any voice is played or frame is waited for).

   BASE+0x00  loader hook: scene's picture loader 0x06030E78(name)
   BASE+0x0A  frame hook:  scene's per-frame vblank wait 0x0604A500()
   BASE+0x10  magic "KHSU"
   BASE+0x14  play hook:   scene's voice player 0x06010EB8(name)
   BASE+0x18  vblank hook: the vblank handler's last call 0x06010578 (staff roll)
   BASE+0x1C  upload hook: the VDP2 library's register upload 0x0604B728
              (both installed in RAM by SUB.BIN itself once it is loaded, never on the disc)
*/
        .section .text.entry, "ax"
        .global _start
_start:
        mov.w   .Lccr, r1               /* 0xFE92 sign-extends to CCR 0xFFFFFE92 */
        mov.b   @r1, r0
        or      #0x10, r0               /* CP: purge all cache lines */
        bra     loader_hook
        mov.b   r0, @r1
        bra     frame_hook              /* BASE+0x0A */
        nop
.Lccr:  .word   0xFE92                  /* still inside the first cache line */
        .long   0x4B485355              /* BASE+0x10: magic "KHSU" */
        bra     play_hook               /* BASE+0x14 */
        nop
        bra     vblank_hook             /* BASE+0x18 */
        nop
        bra     upload_hook             /* BASE+0x1C */
        nop

loader_hook:
        sts.l   pr, @-r15
        mov.l   r4, @-r15
        mov.l   .Lon_load, r0
        jsr     @r0                     /* sub_on_load(name) */
        nop
        mov.l   @r15+, r4
        lds.l   @r15+, pr
        mov.l   .Lorig_loader, r0
        jmp     @r0                     /* tail call: original picture loader(name) */
        nop

play_hook:
        sts.l   pr, @-r15
        mov.l   r4, @-r15
        mov.l   .Lon_play, r0
        jsr     @r0                     /* sub_on_play() */
        nop
        mov.l   @r15+, r4
        lds.l   @r15+, pr
        mov.l   .Lorig_play, r0
        jmp     @r0                     /* tail call: original voice player(name) */
        nop

vblank_hook:
        sts.l   pr, @-r15
        mov.l   .Lon_vblank, r0
        jsr     @r0                     /* sub_on_vblank() */
        nop
        lds.l   @r15+, pr
        mov.l   .Lorig_vblank, r0
        jmp     @r0                     /* tail call: original staff-roll routine */
        nop

upload_hook:
        sts.l   pr, @-r15
        mov.l   .Lorig_upload, r0
        jsr     @r0                     /* the library's VDP2 register upload */
        nop
        mov.l   .Lafter_upload, r0
        jsr     @r0                     /* sub_after_upload(): our NBG3 fields on top */
        nop
        lds.l   @r15+, pr
        rts
        nop

frame_hook:
        mov.l   .Lon_frame, r0
        jmp     @r0                     /* sub_on_frame(), returns to the scene */
        nop

        .align  2
.Lon_load:      .long   sub_on_load
.Lon_play:      .long   sub_on_play
.Lon_frame:     .long   sub_on_frame
.Lorig_loader:  .long   0x06030E78
.Lorig_play:    .long   0x06010EB8
.Lon_vblank:    .long   sub_on_vblank
.Lorig_vblank:  .long   0x06010578
.Lorig_upload:  .long   0x0604B728
.Lafter_upload: .long   sub_after_upload
