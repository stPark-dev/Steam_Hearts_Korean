/* Voice subtitles (SUB.BIN): visual scenes and in-stage dialogue, drawn as VDP1 sprites.

   Timing: a cue belongs to one voice file and is counted in real vblanks (the game's vblank
   counter) from the moment that voice starts sounding: the sound driver keys on SCSP slot 12
   when the stream begins, after the CD seek (VIS1A: 39 vblanks after the call, VIS1B: 24).
   If no key-on is seen within KEYON_WAIT vblanks, the call + KEYON_FALLBACK is used.

   Textures: the game's VDP1 VRAM heap ends 8 KB early (MAIN.BIN patch), so VDP1 VRAM
   0x7E000..0x7FFFF is ours.  A line is assembled in RAM (TEXBUF, 4 bits per pixel) and
   copied there; a signature word at the end of the reserve shows if anyone cleared it.

   Visual scenes (SUBn.DAT, loaded with the scene's first picture): VDP1 draws nothing during
   a scene, so SUB.BIN writes its own command list at VDP1 VRAM 0 (system clip, local
   coordinates, one or two sprites, end) from the scene's per-frame wait.  The line sits over
   the bottom of the picture (rows 212..225) with a black outline, inside the 224 lines every
   display shows.  The scene setup (0x06035364) turns on additive sprite colour calculation
   (CCCTL 0x0540), which would add our black outline to the picture and make it vanish, so
   SPCCEN is cleared (register and the VDP2 library's RAM copy) while a scene runs.  Voices are numbered
   by play order.

   Stages (STGn.DAT, loaded when the first voice of stage n is played, "st3_01.aif" -> 3):
   the game collects VDP1 commands in RAM in 64 priority lists and its frame end routine
   (0x060112F4) closes and DMAs them to VDP1 VRAM.  Our sprites are added to the last list
   right before that.  Up to two lines, above the faces.  Voices are found by file name.
   The pause loop (0x0603355C..) saves the lists once (0x0601123C), stops the voice stream and
   then restores the saved lists every frame (0x06011298): the cue clock and the texture are
   held while that happens.  Our sprites in a saved copy are switched off when it is saved;
   fresh ones are added on top every frame.

   An earlier version drew the stage text on VDP2 NBG3.  That only works in emulators: the
   stages use every VRAM read slot (NBG0/1 at 1/2 reduction), and the NBG3 character read
   we scheduled at T5 after a T4 pattern-name read breaks the VDP2 timing rules (ST-058
   Table 3.4), so a real Saturn showed nothing.

   Built with sh4-linux-gnu-gcc -m4-nofpu -mb; check_sh2.py rejects any opcode the SH-2
   does not have.  No libc, no division, no variable shifts. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define BASE        0x06086340u
#define DATA        ((const u8 *)0x06087540)    /* BASE + 0x1200 */
#define SCENE_MAGIC 0x4B485332u                 /* "KHS2" */
#define STAGE_MAGIC 0x4B485431u                 /* "KHT1" */
#define TEXBUF      ((u8 *)0x0608CC00)          /* 5 KB up to the game heap at 0x0608E000 */
#define CRAM16      ((volatile u16 *)0x25F00000)
#define VDP1_VRAM   ((volatile u16 *)0x25C00000)
#define TEX_VRAM    0x7E000                     /* reserved: 0x7E000..0x7FFFF */
#define TEX_SIG     ((0x80000 - 2) >> 1)        /* word index of the signature */
#define SIG         0x4B48
#define SPRITE_MAX_W 504                        /* CMDSIZE holds width / 8 in 6 bits */

#define VBLANKS     (*(volatile u32 *)0x060730D0)
#define GAME_MODE   (*(volatile u16 *)0x0605D716)   /* 1 = stage (visual scenes run in mode 1 too) */
#define WAIT_VBLANK ((void (*)(void))0x0604A500)
#define READ_FILE   ((int (*)(const char *, void *))0x06010CD4)
#define LIST_PTR    (*(u8 **)0x0606D85C)            /* next free command in the RAM list */
#define ADD_CMD     ((void (*)(int, void *))0x060113D0)   /* (priority list 0..63, command) */
#define VOICE_SLOT  (*(volatile u16 *)(0x25B00000 + 12 * 0x20))    /* SCSP slot 12, KYONB 0x0800 */
#define KEYON_WAIT      120
#define KEYON_FALLBACK  39
#define MAX_AUDIO   4
#define SCENE_GONE  30          /* vblanks without the scene's frame wait: the scene is over */

/* ---- small helpers: gcc for SH-4 turns constant shifts into shad, force SH-2 sequences
   (shll/shlr set T: the "t" clobber keeps gcc from testing a stale T across them) */
static inline int shr1(int x) { __asm__("shlr %0" : "+r"(x) : : "t"); return x; }
static inline int shr2(int x) { __asm__("shlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shr3(int x) { __asm__("shlr2 %0\n\tshlr %0" : "+r"(x) : : "t"); return x; }
static inline int shr4(int x) { __asm__("shlr2 %0\n\tshlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shr6(int x) { __asm__("shlr2 %0\n\tshlr2 %0\n\tshlr2 %0" : "+r"(x) : : "t"); return x; }
static inline int shl4(int x) { __asm__("shll2 %0\n\tshll2 %0" : "+r"(x) : : "t"); return x; }
static inline int shl8(int x) { __asm__("shll8 %0" : "+r"(x)); return x; }

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
    { 0x0601AD98, 0x06010EB8, BASE + 0x14 },    /* stage dialogue: voice player */
    { 0x0601AF10, 0x06010EB8, BASE + 0x14 },
    { 0x0601B080, 0x06010EB8, BASE + 0x14 },
    { 0x0601B29C, 0x06010EB8, BASE + 0x14 },
    { 0x06032104, 0x060112F4, BASE + 0x1C },    /* VDP1 list close + DMA (frame end) */
    { 0x06032660, 0x060112F4, BASE + 0x1C },
    { 0x06033434, 0x060112F4, BASE + 0x1C },
    { 0x06033678, 0x060112F4, BASE + 0x1C },
    { 0x06033680, 0x06011298, BASE + 0x20 },    /* pause loop: restore the frozen lists */
    { 0x06032564, 0x0601123C, BASE + 0x24 },    /* list save (game over / continue) */
    { 0x06033460, 0x0601123C, BASE + 0x24 },    /* list save (pause) */
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

#define NOINLINE __attribute__((noinline))

/* the helpers below stay real functions: smaller code, and easy to read in the listing */
static NOINLINE void watch_keyon(u32 now)
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
/* textures                                                                                  */

struct glyph { u16 width, bits; };

/* one 4-bit pixel of a linear texture `w` pixels wide */
static void tex_put(u8 *tex, int w, int x, int y, int v)
{
    u8 *p = tex + y * shr1(w) + shr1(x);
    if (x & 1)
        *p = (u8)((*p & 0xF0) | v);
    else
        *p = (u8)((*p & 0x0F) | shl4(v));
}

static int tex_get(const u8 *tex, int w, int x, int y)
{
    int b = tex[y * shr1(w) + shr1(x)];
    return (x & 1) ? (b & 15) : shr4(b);
}

/* glyphs (2 bits per pixel, `rows` rows) into a texture at (x, y0); a glyph's 1s (outline)
   never cover the ink of its neighbours */
static NOINLINE void tex_text(u8 *tex, int tw, int y0, const struct glyph *gl, const u8 *bits0,
                     const u16 *text, int n, int x, int rows)
{
    for (int i = 0; i < n; i++) {
        const struct glyph *g = gl + text[i];
        int w = g->width, pitch = shr2(w + 3);
        const u8 *bits = bits0 + g->bits;
        for (int y = 0; y < rows; y++, bits += pitch)
            for (int px = 0; px < w; px++) {
                int b = bits[shr2(px)];
                switch (px & 3) {
                case 0: b = shr6(b); break;
                case 1: b = shr4(b); break;
                case 2: b = shr2(b); break;
                }
                b &= 3;
                int sx = x + px;
                if (!b || sx < 0 || sx >= tw)
                    continue;
                if (b == 1 && tex_get(tex, tw, sx, y0 + y))
                    continue;
                tex_put(tex, tw, sx, y0 + y, b);
            }
        x += w;
    }
}

/* black outline around the ink: two columns sideways, one row up and down (a scene pixel is
   twice as tall as wide).  Runs once per line change inside the scene's frame wait, so it
   only visits ink pixels and touches bytes directly. */
static NOINLINE void tex_outline(u8 *tex, int tw, int th)
{
    int pitch = shr1(tw);
    for (int y = 0; y < th; y++) {
        const u8 *row = tex + y * pitch;
        for (int x = 0; x < tw; x++) {
            int b = row[shr1(x)];
            int v = (x & 1) ? (b & 15) : shr4(b);
            if (v < 2)
                continue;
            for (int yy = y - 1; yy <= y + 1; yy++) {
                if ((unsigned)yy >= (unsigned)th)
                    continue;
                u8 *r = tex + yy * pitch;
                for (int xx = x - 2; xx <= x + 2; xx++) {
                    if ((unsigned)xx >= (unsigned)tw)
                        continue;
                    u8 *p = r + shr1(xx);
                    if (xx & 1) {
                        if (!(*p & 0x0F))
                            *p |= 0x01;
                    } else if (!(*p & 0xF0)) {
                        *p |= 0x10;
                    }
                }
            }
        }
    }
}

static void tex_clear(u8 *tex, int bytes)
{
    u32 *p = (u32 *)tex;
    for (int i = 0; i < shr2(bytes); i++)
        p[i] = 0;
}

/* copy columns [x0, x0 + w) of a linear texture to VDP1 VRAM as a w-wide sprite texture */
static NOINLINE void tex_upload(const u8 *tex, int tw, int th, int x0, int w, u32 vram)
{
    volatile u16 *dst = VDP1_VRAM + shr1(vram);
    for (int y = 0; y < th; y++) {
        const u8 *src = tex + y * shr1(tw) + shr1(x0);
        for (int i = 0; i < shr1(w); i += 2)
            *dst++ = (u16)(shl8(src[i]) | src[i + 1]);
    }
}

static void tex_sign(void) { VDP1_VRAM[TEX_SIG] = SIG; }
static int tex_signed(void) { return VDP1_VRAM[TEX_SIG] == SIG; }

/* a VDP1 normal sprite, colour bank mode (4 bits per dot), end codes off, dot 0 clear */
static void put_sprite(volatile u16 *c, u16 colr, u32 vram, int w, int h, int x, int y)
{
    c[0] = 0x0000;
    c[1] = 0;
    c[2] = 0x0080;
    c[3] = colr;
    c[4] = (u16)shr3((int)vram);
    c[5] = (u16)(shl8(shr3(w)) | h);
    c[6] = (u16)x;
    c[7] = (u16)y;
    for (int i = 8; i < 16; i++)
        c[i] = 0;
}

static int round8(int x) { return (x + 7) & ~7; }

/* ======================================================================================== */
/* visual scenes: own VDP1 list over the picture                                             */

struct scene_header { u32 magic; u16 ncues, nglyphs; u32 cues, glyphs, text, bits; };
struct scene_cue { u8 audio, pad; u16 start, end, text, nchars, x; };

#define SCENE_Y     212
#define SCENE_ROWS  14          /* 12 glyph rows + outline */
#define SCENE_MARGIN 2
#define SCENE_COLR  0x0070      /* 8-bit sprites: priority bit 0 (S0 over NBG0), CRAM 0x70.. */
#define SCENE_CRAM  0x70

#define CCCTL_COPY  (*(volatile u16 *)0x06085C6C)   /* 0x06085B80 + 0xEC: the library's copy */
#define CCCTL_REG   (*(volatile u16 *)0x25F800EC)   /* write-only; scenes do not re-upload */
#define SPCCEN      0x0040

static int bar_cur = -1;
static int scene_live = 0;
static int cc_cleared = -1;     /* CCCTL copy as we left it, -1 = untouched */
static u32 scene_seen = 0;
static int scene_tw = 0;

static const u16 text_pal[4] = { 0, 0x0000, 0x5294, 0x7FFF };

static int list_ours(void) { return VDP1_VRAM[0] == 0x0009 && VDP1_VRAM[14] == SIG; }

static void scene_list_end(void)
{
    if (list_ours())
        VDP1_VRAM[0] = 0x8000;
}

static void scene_cram(void)
{
    for (int i = 0; i < 4; i++)
        CRAM16[SCENE_CRAM + i] = text_pal[i];
}

static int scene_cram_ok(void) { return CRAM16[SCENE_CRAM + 3] == 0x7FFF && CRAM16[SCENE_CRAM + 2] == 0x5294; }

/* commands: 0 system clip, 1 local coordinates, 2..3 sprites, then end; command 0 is
   written last so VDP1 never sees half a list */
static NOINLINE void scene_list(int x)
{
    volatile u16 *c = VDP1_VRAM;
    int w0 = scene_tw < SPRITE_MAX_W ? scene_tw : SPRITE_MAX_W;
    int w1 = scene_tw - w0;
    c[0] = 0x8000;
    c[16] = 0x000A;                             /* local coordinates 0,0 */
    for (int i = 17; i < 32; i++)
        c[i] = 0;
    put_sprite(c + 32, SCENE_COLR, TEX_VRAM, w0, SCENE_ROWS, x, SCENE_Y);
    int end = 48;
    if (w1) {
        put_sprite(c + 48, SCENE_COLR, TEX_VRAM + shr1(w0 * SCENE_ROWS), w1, SCENE_ROWS, x + w0, SCENE_Y);
        end = 64;
    }
    c[end] = 0x8000;
    for (int i = 1; i < 16; i++)
        c[i] = 0;
    c[10] = 639;                                /* system clip: whole 640x240 screen */
    c[11] = 239;
    c[14] = SIG;
    c[0] = 0x0009;
}

static NOINLINE void scene_show(int idx)
{
    bar_cur = idx;
    if (idx < 0) {
        scene_list_end();
        return;
    }
    const struct scene_header *h = (const struct scene_header *)DATA;
    const struct scene_cue *c = (const struct scene_cue *)(DATA + h->cues) + idx;
    const u16 *text = (const u16 *)(DATA + h->text) + c->text;
    const struct glyph *gl = (const struct glyph *)(DATA + h->glyphs);
    int w = 0;
    for (int i = 0; i < c->nchars; i++)
        w += gl[text[i]].width;
    scene_tw = round8(w + 2 * SCENE_MARGIN);
    tex_clear(TEXBUF, shr1(scene_tw * SCENE_ROWS));
    tex_text(TEXBUF, scene_tw, 1, gl, DATA + h->bits, text, c->nchars, SCENE_MARGIN, SCENE_ROWS - 2);
    tex_outline(TEXBUF, scene_tw, SCENE_ROWS);
    int w0 = scene_tw < SPRITE_MAX_W ? scene_tw : SPRITE_MAX_W;
    tex_upload(TEXBUF, scene_tw, SCENE_ROWS, 0, w0, TEX_VRAM);
    if (scene_tw > w0)
        tex_upload(TEXBUF, scene_tw, SCENE_ROWS, w0, scene_tw - w0, TEX_VRAM + shr1(w0 * SCENE_ROWS));
    tex_sign();
    scene_cram();
    scene_list(c->x);
}

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

void sub_on_frame(void)         /* the scene's per-frame wait */
{
    WAIT_VBLANK();
    u32 now = VBLANKS;
    scene_seen = now;
    scene_live = 1;
    if (CCCTL_COPY & SPCCEN) {
        CCCTL_COPY = CCCTL_COPY & ~SPCCEN;
        cc_cleared = CCCTL_COPY;
        CCCTL_REG = (u16)cc_cleared;
    }
    if (loaded_kind != 1)
        return;
    const struct scene_header *h = (const struct scene_header *)DATA;
    const struct scene_cue *c = (const struct scene_cue *)(DATA + h->cues);
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
    /* redraw when the line changes, or when something replaced our list, texture or colours */
    if (idx != bar_cur || (idx >= 0 && (!list_ours() || !tex_signed() || !scene_cram_ok())))
        scene_show(idx);
}

/* ======================================================================================== */
/* stages: sprites added to the game's own VDP1 list                                         */

struct stage_header { u32 magic; u16 naudio, ncues, nglyphs, pad; u32 names, cues, glyphs, text, bits; };
struct stage_cue { u8 audio, nlines; u16 start, end, text, n1, n2, x1, x2; };

#define STAGE_ROWS  16
#define STAGE_Y0    96          /* the two lines: rows 96..111 and 112..127, above the faces */
#define STAGE_LINE_BYTES 2432   /* 304 x 16 / 2: second line's texture offset */
#define STAGE_COLR  0x07F0      /* 16-bit sprite type 5: priority S0 (top), CRAM 0x7F0.. */
#define STAGE_CRAM  0x7F0
#define STAGE_LIST  63          /* the game's last priority list: drawn on top */
#define PAUSE_GAP   2           /* vblanks since the pause loop's restore that mean "paused" */

static int stg_cur = -2;        /* cue in the texture, -1 = none, -2 = unknown */
static u32 last_pause = 0;      /* vblank of the pause loop's last list restore */
static volatile u16 *added[2] = { 0 };   /* our commands in the RAM lists this frame */
static int nadded = 0;
static int stg_n = 0;           /* sprites to add: 0..2 */
static int stg_w[2] = { 0 }, stg_x[2] = { 0 }, stg_y[2] = { 0 };
static u32 stg_vram[2] = { 0 };
static int stg_want = -1;       /* cue the vblank handler wants shown */

static void stage_cram(void)
{
    for (int i = 0; i < 4; i++)
        CRAM16[STAGE_CRAM + i] = text_pal[i];
}

static NOINLINE void stage_upload(void)
{
    for (int i = 0; i < stg_n; i++)
        tex_upload(TEXBUF + (stg_vram[i] - TEX_VRAM), stg_w[i], STAGE_ROWS, 0, stg_w[i], stg_vram[i]);
    tex_sign();
}

/* one text line (`count` > 0 glyphs) into sprite slot n; second == 1 for the lower row */
static NOINLINE void stage_line(int n, int second, const u16 *text, int count, int x)
{
    const struct stage_header *h = (const struct stage_header *)DATA;
    const struct glyph *gl = (const struct glyph *)(DATA + h->glyphs);
    int w = 0;
    for (int i = 0; i < count; i++)
        w += gl[text[i]].width;
    u32 off = second ? STAGE_LINE_BYTES : 0;
    int tw = round8(w);
    stg_w[n] = tw;
    stg_x[n] = x;
    stg_y[n] = second ? STAGE_Y0 + STAGE_ROWS : STAGE_Y0;
    stg_vram[n] = TEX_VRAM + off;
    tex_clear(TEXBUF + off, shr1(tw * STAGE_ROWS));
    tex_text(TEXBUF + off, tw, 0, gl, DATA + h->bits, text, count, 0, STAGE_ROWS);
}

static NOINLINE void stage_show(int idx)
{
    stg_n = 0;                  /* the frame end hook may run in between: publish n last */
    stg_cur = idx;
    if (idx < 0)
        return;
    const struct stage_header *h = (const struct stage_header *)DATA;
    const struct stage_cue *c = (const struct stage_cue *)(DATA + h->cues) + idx;
    const u16 *text = (const u16 *)(DATA + h->text) + c->text;
    int n = 0;
    if (c->n1 > 0) {
        stage_line(n, 0, text, c->n1, c->x1);
        n++;
    }
    if (c->n2 > 0) {
        stage_line(n, 1, text + c->n1, c->n2, c->x2);
        n++;
    }
    if (n > 0) {
        stg_n = n;
        stage_upload();
        stage_cram();
    }
}

static NOINLINE int stage_cue_now(u32 now)
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

void sub_on_pause_frame(void)   /* the pause loop restores the lists saved when it began */
{
    last_pause = VBLANKS;
}

static int paused(u32 now) { return now - last_pause <= PAUSE_GAP; }

/* the game saves its lists (pause, game over) and redraws the saved copy every frame after;
   our sprites in that copy would keep pointing at a texture that changes, so they are turned
   into skipped commands first (the copy keeps its links) */
void sub_before_list_save(void)
{
    u8 *lo = *(u8 **)0x0606D860;            /* this frame's list buffer start */
    for (int i = 0; i < nadded; i++)
        if ((u8 *)added[i] >= lo && (u8 *)added[i] < LIST_PTR)
            added[i][0] |= 0x4000;
    nadded = 0;
}

void sub_before_list_end(void)  /* right before the game closes its VDP1 list */
{
    nadded = 0;
    if (!(GAME_MODE == 1 && loaded_kind == 2))
        return;
    /* textures are built here in the game's main loop, not in the vblank handler */
    int want = stg_want;
    if (want != stg_cur)
        stage_show(want);
    else if (stg_n) {
        /* the stage start clears VRAM and CRAM: put the texture and colours back */
        if (!tex_signed())
            stage_upload();
        if (CRAM16[STAGE_CRAM + 3] != 0x7FFF)
            stage_cram();
    }
    if (!stg_n)
        return;
    u8 *p = LIST_PTR;
    for (int i = 0; i < stg_n; i++) {
        put_sprite((volatile u16 *)p, STAGE_COLR, stg_vram[i], stg_w[i], STAGE_ROWS, stg_x[i], stg_y[i]);
        ADD_CMD(STAGE_LIST, p);
        added[nadded++] = (volatile u16 *)p;
        p += 32;
    }
    LIST_PTR = p;
}

void sub_on_vblank(void)        /* end of the vblank handler, every frame in every mode */
{
    u32 now = VBLANKS;
#ifdef TEST_INVINCIBLE
    /* verification builds only: keep refilling the invincibility timer the pause-menu cheat
       (0x06033354) sets, player struct *(0x06077A58) + index * 80 + 0x42 */
    if (GAME_MODE == 1) {
        u32 pl = *(volatile u32 *)0x06077A58;
        if (pl >= 0x06000000 && pl < 0x060FF000)
            *(volatile u16 *)(pl + *(volatile u16 *)0x06073474 * 80 + 0x42) = 0x4B0;
    }
#endif
    watch_keyon(now);
    if (scene_live && now - scene_seen > SCENE_GONE) {
        scene_live = 0;
        bar_cur = -1;
        scene_list_end();
        /* nobody set it since, and no stage has taken over: put it back */
        if (cc_cleared >= 0 && CCCTL_COPY == cc_cleared && loaded_kind == 1) {
            CCCTL_COPY = CCCTL_COPY | SPCCEN;
            CCCTL_REG = CCCTL_COPY;
        }
        cc_cleared = -1;
    }
    if (GAME_MODE == 1 && loaded_kind == 2) {
        /* the pause loop stops the voice stream and redraws the lists saved when it began
           (our sprites included): hold the cue clock and leave the texture as it is */
        if (paused(now)) {
            anchor[0]++;
            called[0]++;
            return;
        }
        stg_want = stage_cue_now(now);
    } else {
        stg_want = -1;
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
            stg_n = 0;
            stg_cur = -2;
            stage_name[3] = (char)voice[2];
            if (!load(stage_name, 2, no))
                return;
        }
        start_watch(0);         /* before stage_voice: the vblank handler pairs them */
        const struct stage_header *h = (const struct stage_header *)DATA;
        const char *names = (const char *)(DATA + h->names);
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
    } else {
        /* scenes run in game mode 1 too; in a stage this is a voice without subtitles
           (deadblow.aif, ...) whose key-on must not restart the last dialogue's cues */
        stage_voice = -1;
        if (nplay < MAX_AUDIO) {
            start_watch(nplay);
            nplay++;
        }
    }
}
