/* Voice subtitles (SUB.BIN): visual scenes and in-stage dialogue.

   Timing: a cue belongs to one voice file and is counted in real vblanks (the game's vblank
   counter) from the moment that voice starts sounding: the sound driver keys on SCSP slot 12
   when the stream begins, after the CD seek (VIS1A: 39 vblanks after the call, VIS1B: 24).
   If no key-on is seen within KEYON_WAIT vblanks, the call + KEYON_FALLBACK is used.

   Visual scenes (SUBn.DAT, loaded with the scene's first picture): the line goes into the
   black bar under the picture, VDP2 NBG0 bitmap rows 228..239, written by the CPU from the
   scene's per-frame wait.  Voices are numbered by play order.

   Stages (STGn.DAT, loaded when the first voice of stage n is played, "st3_01.aif" -> 3;
   the stage counter does not map 1:1 onto the voice files): up to two lines on
   NBG3, which the stages leave unused, drawn from the vblank handler.  Voices are found by
   file name.  VDP2 registers are write-only and re-uploaded every frame by the game's VDP2
   library from RAM copies, so our NBG3 fields are written right after that upload.

   Built with sh4-linux-gnu-gcc -m4-nofpu -mb; check_sh2.py rejects any opcode the SH-2
   does not have.  No libc, no division, no variable shifts. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define BASE        0x06086340u
#define DATA        ((const u8 *)0x06087340)    /* BASE + 0x1000 */
#define SCENE_MAGIC 0x4B485332u                 /* "KHS2" */
#define STAGE_MAGIC 0x4B485431u                 /* "KHT1" */
#define CELLBUF     ((u32 *)0x0608CC00)         /* 160 NBG3 cells, up to 0x0608E000 */
#define VRAM        ((volatile u16 *)0x25E00000)
#define CRAM16      ((volatile u16 *)0x25F00000)
#define VDP2_REG(o) (*(volatile u16 *)(0x25F80000 + (o)))

#define VBLANKS     (*(volatile u32 *)0x060730D0)
#define GAME_MODE   (*(volatile u16 *)0x0605D716)   /* 1 = stage */
#define WAIT_VBLANK ((void (*)(void))0x0604A500)
#define READ_FILE   ((int (*)(const char *, void *))0x06010CD4)
#define VOICE_SLOT  (*(volatile u16 *)(0x25B00000 + 12 * 0x20))    /* SCSP slot 12, KYONB 0x0800 */
#define KEYON_WAIT      120
#define KEYON_FALLBACK  39
#define MAX_AUDIO   4

/* ---- small helpers: gcc for SH-4 turns constant shifts into shad, force SH-2 sequences
   (shll/shlr set T: the "t" clobber keeps gcc from testing a stale T across them) */
static inline int shr1(int x) { __asm__("shlr %0" : "+r"(x) : : "t"); return x; }
static inline int shr2(int x) { __asm__("shlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shr3(int x) { __asm__("shlr2 %0\n\tshlr %0" : "+r"(x) : : "t"); return x; }
static inline int shr4(int x) { __asm__("shlr2 %0\n\tshlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shr6(int x) { __asm__("shlr2 %0\n\tshlr2 %0\n\tshlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shl2(int x) { __asm__("shll2 %0" : "+r"(x) : : "t"); return x; }
static inline int shl4(int x) { __asm__("shll2 %0\n\tshll2 %0" : "+r"(x) : : "t"); return x; }
static inline int shl5(int x) { __asm__("shll2 %0\n\tshll2 %0\n\tshll %0" : "+r"(x) : : "t"); return x; }

static inline void purge_cache(void)
{
    volatile u8 *ccr = (volatile u8 *)0xFFFFFE92;
    *ccr = *ccr | 0x10;
}

static int lower(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

/* ---- runtime hooks the disc cannot hold (SUB.BIN is not in RAM at boot) ---------------- */
struct hook { u32 addr, orig, hook; };
static const struct hook hooks[] = {
    { 0x06010828, 0x06010578, BASE + 0x18 },    /* vblank handler's last call */
    { 0x0604B9E4, 0x0604B728, BASE + 0x1C },    /* VDP2 library register upload */
    { 0x0601AD98, 0x06010EB8, BASE + 0x14 },    /* stage dialogue: voice player */
    { 0x0601AF10, 0x06010EB8, BASE + 0x14 },
    { 0x0601B080, 0x06010EB8, BASE + 0x14 },
    { 0x0601B29C, 0x06010EB8, BASE + 0x14 },
};

static void install_hooks(void)
{
    int changed = 0;
    for (unsigned i = 0; i < sizeof hooks / sizeof hooks[0]; i++) {
        volatile u32 *lit = (volatile u32 *)hooks[i].addr;
        if (*lit == hooks[i].orig) {
            *lit = hooks[i].hook;
            changed = 1;
        }
    }
    if (changed)
        purge_cache();
}

/* ---- data loading --------------------------------------------------------------------- */
static int loaded_kind = 0;     /* 0 none, 1 scene, 2 stage */
static int loaded_no = -1;
static char scene_name[] = "SUB1.DAT";
static char stage_name[] = "STG1.DAT";

static int load(char *name, int kind, int no)
{
    if (loaded_kind == kind && loaded_no == no)
        return 1;
    loaded_kind = 0;
    loaded_no = no;
    if (READ_FILE(name, (void *)DATA) >= 0) {
        purge_cache();
        u32 magic = *(const u32 *)DATA;
        if ((kind == 1 && magic == SCENE_MAGIC) || (kind == 2 && magic == STAGE_MAGIC))
            loaded_kind = kind;
    }
    return loaded_kind == kind;
}

/* ---- voices and key-on ------------------------------------------------------------------ */
static int nplay = 0;                   /* scenes: voices played so far */
static int stage_voice = -1;            /* stages: index of the voice playing (by name) */
static u32 called[MAX_AUDIO] = { 0 };
static u32 anchor[MAX_AUDIO] = { 0 };
static u8 started[MAX_AUDIO] = { 0 };
static u8 seen_off[MAX_AUDIO] = { 0 };
static int watch = -1;                  /* slot being watched for key-on */

static void start_watch(int slot)
{
    called[slot] = VBLANKS;
    started[slot] = seen_off[slot] = 0;
    watch = slot;
}

static void watch_keyon(u32 now)
{
    int a = watch;
    if (a < 0 || started[a])
        return;
    if (!(VOICE_SLOT & 0x0800)) {
        seen_off[a] = 1;
    } else if (seen_off[a]) {
        anchor[a] = now;
        started[a] = 1;
        return;
    }
    if (now - called[a] >= KEYON_WAIT) {
        anchor[a] = called[a] + KEYON_FALLBACK;
        started[a] = 1;
    }
}

/* ======================================================================================== */
/* visual scenes: black bar under the picture                                                */

struct scene_header { u32 magic; u16 ncues, nglyphs; u32 cues, glyphs, text, bits; };
struct scene_cue { u8 audio, pad; u16 start, end, text, nchars, x; };
struct glyph { u16 width, bits; };

#define STRIDE      1024
#define BAR_Y       228
#define BAR_H       12
#define SCREEN_W    640
#define MARK_POS    ((BAR_Y + BAR_H - 1) * STRIDE + SCREEN_W - 1)
#define MARK        0x0001
#define BG          0x0000

static int bar_cur = -1;
static const u16 bar_pal[4] = { BG, 0x8000 | 10 << 10 | 10 << 5 | 10,
                                0x8000 | 21 << 10 | 21 << 5 | 21, 0xFFFF };

void sub_on_load(const char *picture)
{
    install_hooks();
    if (picture[0] != 'v' || picture[1] != 'i' || picture[2] != 's')
        return;                 /* title logos and other pictures */
    /* the scene is the digit in the picture name, "vis3_1s.pxt" -> 3 */
    int scene = picture[3] - '0';
    nplay = 0;                  /* pictures are loaded before the first voice */
    watch = -1;
    bar_cur = -1;
    if (scene < 1 || scene > 7)
        return;
    scene_name[3] = (char)('0' + scene);
    load(scene_name, 1, scene);
}

static void bar_draw(int idx)
{
    const struct scene_header *h = (const struct scene_header *)DATA;
    volatile u32 *row32 = (volatile u32 *)(VRAM + BAR_Y * STRIDE);
    for (int y = 0; y < BAR_H; y++, row32 += STRIDE / 2)
        for (int x = 0; x < SCREEN_W / 2; x++)
            row32[x] = BG << 16 | BG;
    if (idx >= 0) {
        const struct scene_cue *c = (const struct scene_cue *)(DATA + h->cues) + idx;
        const u16 *text = (const u16 *)(DATA + h->text) + c->text;
        const struct glyph *gl = (const struct glyph *)(DATA + h->glyphs);
        int x = c->x;
        for (int i = 0; i < c->nchars; i++) {
            const struct glyph *g = gl + text[i];
            int w = g->width, pitch = shr2(w + 3);
            const u8 *bits = DATA + h->bits + g->bits;
            volatile u16 *dst = VRAM + BAR_Y * STRIDE + x;
            for (int y = 0; y < BAR_H; y++, bits += pitch, dst += STRIDE)
                for (int bx = 0; bx < pitch; bx++) {
                    int b = bits[bx];
                    volatile u16 *d = dst + shl2(bx);
                    if (b & 0xC0) d[0] = bar_pal[shr6(b) & 3];
                    if (b & 0x30) d[1] = bar_pal[shr4(b) & 3];
                    if (b & 0x0C) d[2] = bar_pal[shr2(b) & 3];
                    if (b & 0x03) d[3] = bar_pal[b & 3];
                }
            x += w;
        }
    }
    VRAM[MARK_POS] = MARK;
    bar_cur = idx;
}

void sub_on_frame(void)         /* the scene's per-frame wait */
{
    WAIT_VBLANK();
    if (loaded_kind != 1)
        return;
    const struct scene_header *h = (const struct scene_header *)DATA;
    const struct scene_cue *c = (const struct scene_cue *)(DATA + h->cues);
    u32 now = VBLANKS;
    int idx = -1;
    for (int i = 0; i < h->ncues; i++) {
        int a = c[i].audio;
        if (a >= nplay || !started[a])
            continue;
        u32 t = now - anchor[a];
        if (t >= c[i].start && t < c[i].end) {
            idx = i;
            break;
        }
    }
    /* redraw when the line changes, or when something repainted the bar */
    if (idx != bar_cur || (bar_cur >= 0 && VRAM[MARK_POS] != MARK))
        bar_draw(idx);
}

/* ======================================================================================== */
/* stages: NBG3 text layer                                                                   */

struct stage_header { u32 magic; u16 naudio, ncues, nglyphs, pad; u32 names, cues, glyphs, text, bits; };
struct stage_cue { u8 audio, nlines; u16 start, end, text, n1, n2, x1, x2; };

#define N3_MAP      0x70000         /* VRAM bank B1, unused by the stages */
#define N3_CHARS    0x74000
#define N3_PAL      15              /* palette 15 at colour offset 7: CRAM 0x7F0.. */
#define N3_BLANK    ((N3_PAL << 12) | ((N3_CHARS >> 5) & 0x3FF))
#define N3_ROW      12              /* first map row of the two text lines (y = 96..127, above the faces) */
#define N3_CELLS    160             /* 2 lines x 2 cell rows x 40 */
#define GLYPH_ROWS  16

/* registers the library uploads from RAM: 0x0E..0x27 at 0x060859B0+reg, 0x28..0x6F at
   0x060859B8+reg, 0xE0.. at 0x06085B80+reg */
#define SH(base, reg)  (*(volatile u16 *)((base) + (reg)))
#define SYS  0x060859B0
#define NOR  0x060859B8
#define DAT  0x06085B80

static int n3_on = 0;
static int n3_cur = -2;         /* cue in the cells, -1 = blank, -2 = unknown */

static void n3_regs(void)
{
    VDP2_REG(0x20) = SH(SYS, 0x20) | 0x0008;                /* BGON: N3ON */
    VDP2_REG(0x2A) = SH(NOR, 0x2A) & ~0x0030;               /* CHCTLB: N3 1x1 cell, 16 colours */
    VDP2_REG(0x36) = 0x8000 | (N3_CHARS >> 15);             /* PNCN3: 1 word, char bits 14..10 */
    VDP2_REG(0x3A) = SH(NOR, 0x3A) & ~0x00C0;               /* PLSZ: N3 1x1 plane */
    VDP2_REG(0x3C) = SH(NOR, 0x3C) & ~0x7000;               /* MPOFN: N3 map offset 0 */
    VDP2_REG(0x4C) = (N3_MAP >> 13) * 0x0101;               /* MPABN3 */
    VDP2_REG(0x4E) = (N3_MAP >> 13) * 0x0101;               /* MPCDN3 */
    VDP2_REG(0x94) = 0;                                     /* SCXIN3 */
    VDP2_REG(0x96) = 0;                                     /* SCYIN3 */
    VDP2_REG(0xFA) = (SH(DAT, 0xFA) & 0x00FF) | 0x0700;     /* PRINB: N3 priority 7 */
    VDP2_REG(0xE4) = (SH(DAT, 0xE4) & 0x0FFF) | 0x7000;     /* CRAOFA: N3 colour offset 7 */
    VDP2_REG(0x1E) = (SH(SYS, 0x1E) & 0x00FF) | 0x3700;     /* CYCB1 T4,T5: N3 name, N3 char */
}

void sub_after_upload(void)
{
    if (n3_on)
        n3_regs();
}

/* map and palette; the stage start clears VRAM and CRAM, so this is redone when they vanish */
static void n3_layout(void)
{
    static const u16 col[4] = { 0, 0x0000, 0x5294, 0x7FFF };
    for (int i = 0; i < 4; i++)
        CRAM16[0x7F0 + i] = col[i];
    volatile u32 *ch = (volatile u32 *)(0x25E00000 + N3_CHARS);
    for (int i = 0; i < 8; i++)
        ch[i] = 0;                                          /* char 0: clear */
    volatile u16 *map = (volatile u16 *)(0x25E00000 + N3_MAP);
    for (int i = 0; i < 64 * 64; i++)
        map[i] = N3_BLANK;
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 40; c++)
            map[(N3_ROW + r) * 64 + c] = N3_BLANK + 1 + r * 40 + c;
    n3_cur = -2;
}

static int n3_layout_ok(void)
{
    volatile u16 *map = (volatile u16 *)(0x25E00000 + N3_MAP);
    return map[0] == N3_BLANK && map[N3_ROW * 64] == N3_BLANK + 1 && CRAM16[0x7F3] == 0x7FFF;
}

/* one line of glyphs into the cell buffer: line 0 = cells 0..79, line 1 = 80..159 */
static void n3_line(int line, const u16 *text, int n, int x)
{
    const struct stage_header *h = (const struct stage_header *)DATA;
    const struct glyph *gl = (const struct glyph *)(DATA + h->glyphs);
    u8 *buf = (u8 *)CELLBUF;
    int base = line ? 80 : 0;
    for (int i = 0; i < n; i++) {
        const struct glyph *g = gl + text[i];
        int w = g->width, pitch = shr2(w + 3);
        const u8 *bits = DATA + h->bits + g->bits;
        for (int y = 0; y < GLYPH_ROWS; y++, bits += pitch) {
            int rowcell = base + (y < 8 ? 0 : 40);
            int yoff = shl2(y & 7);
            for (int px = 0; px < w; px++) {
                int b = bits[shr2(px)];
                switch (px & 3) {
                case 0: b = shr6(b); break;
                case 1: b = shr4(b); break;
                case 2: b = shr2(b); break;
                }
                b &= 3;
                if (!b)
                    continue;
                int sx = x + px;
                if (sx < 0 || sx >= 320)
                    continue;
                u8 *p = buf + shl5(rowcell + shr3(sx)) + yoff + shr1(sx & 7);
                if (sx & 1)
                    *p = (u8)((*p & 0xF0) | b);
                else
                    *p = (u8)((*p & 0x0F) | shl4(b));
            }
        }
        x += w;
    }
}

static void n3_draw(int idx)
{
    for (int i = 0; i < N3_CELLS * 8; i++)
        CELLBUF[i] = 0;
    if (idx >= 0) {
        const struct stage_header *h = (const struct stage_header *)DATA;
        const struct stage_cue *c = (const struct stage_cue *)(DATA + h->cues) + idx;
        const u16 *text = (const u16 *)(DATA + h->text) + c->text;
        if (c->n1)
            n3_line(0, text, c->n1, c->x1);
        if (c->n2)
            n3_line(1, text + c->n1, c->n2, c->x2);
    }
    volatile u32 *ch = (volatile u32 *)(0x25E00000 + N3_CHARS) + 8;    /* chars 1.. */
    for (int i = 0; i < N3_CELLS * 8; i++)
        ch[i] = CELLBUF[i];
    n3_cur = idx;
}

static int stage_cue_now(u32 now)
{
    int a = stage_voice;
    if (a < 0 || !started[0])
        return -1;
    const struct stage_header *h = (const struct stage_header *)DATA;
    const struct stage_cue *c = (const struct stage_cue *)(DATA + h->cues);
    u32 t = now - anchor[0];
    for (int i = 0; i < h->ncues; i++)
        if (c[i].audio == a && t >= c[i].start && t < c[i].end)
            return i;
    return -1;
}

void sub_on_vblank(void)        /* end of the vblank handler, every frame in every mode */
{
    u32 now = VBLANKS;
    watch_keyon(now);
    if (GAME_MODE == 1 && loaded_kind == 2) {
        if (!n3_on) {
            n3_on = 1;
            n3_regs();
        }
        if (!n3_layout_ok())
            n3_layout();
        int idx = stage_cue_now(now);
        if (idx != n3_cur)
            n3_draw(idx);
    } else if (n3_on) {
        n3_on = 0;
        VDP2_REG(0x20) = SH(SYS, 0x20);
    }
}

/* ---- voice play hook (scenes and stages) ----------------------------------------------- */
void sub_on_play(const char *voice)
{
    if (GAME_MODE == 1 && lower(voice[0]) == 's' && lower(voice[1]) == 't'
        && voice[2] >= '1' && voice[2] <= '9') {
        int no = voice[2] - '0';
        stage_voice = -1;
        if (loaded_kind != 2 || loaded_no != no) {
            n3_cur = -2;
            stage_name[3] = (char)voice[2];
            if (!load(stage_name, 2, no))
                return;
        }
        const struct stage_header *h = (const struct stage_header *)DATA;
        const char *names = (const char *)(DATA + h->names);
        stage_voice = -1;
        for (int i = 0; i < h->naudio; i++) {
            const char *n = names + i * 12;
            int k = 0;
            while (n[k] && lower(voice[k]) == n[k])
                k++;
            if (!n[k] && !voice[k]) {
                stage_voice = i;
                break;
            }
        }
        start_watch(0);
    } else if (nplay < MAX_AUDIO) {
        start_watch(nplay);
        nplay++;
    }
}
