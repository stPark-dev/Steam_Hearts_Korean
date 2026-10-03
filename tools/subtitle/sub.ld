OUTPUT_FORMAT("elf32-shbig-linux")
ENTRY(_start)
SECTIONS
{
    . = 0x06086340;
    .text : { *(.text.entry) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss : { *(.bss .bss.*) *(COMMON) }
    _end = .;
    .stagetest 0x06087340 : { *(.stagetest) }      /* pilot builds only: lands in the data area */
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
ASSERT(_end <= 0x06087340, "subtitle code overruns its 4 KB")
