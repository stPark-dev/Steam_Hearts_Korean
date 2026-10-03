/* Voice subtitles for the visual scenes (SUB.BIN).

   Timing: each cue is tied to a voice file (the n-th voice play call of the scene) and
   counted in real vblanks, using the game's vblank counter, from the moment that voice
   starts sounding: the sound driver keys on SCSP slot 12 when the stream begins, after the
   CD seek (VIS1A: 39 vblanks after the call, VIS1B: 24).  If no key-on is seen within
   KEYON_WAIT vblanks, the call + KEYON_FALLBACK is used.  The scene's own frame counter is
   not used: it stalls while a picture is decompressed (~21 frames).

   Drawing: the current line goes into the black bar under the picture, VDP2 NBG0 bitmap
   rows 228..239, written by the CPU.  Nothing on VDP1 is touched.

   Built with sh4-linux-gnu-gcc -m4-nofpu -mb; check_sh2.py rejects any opcode the SH-2
   does not have.  No libc, no division, no variable shifts. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define DATA        ((const u8 *)0x06087340)    /* BASE + 0x1000, up to 0x0608E000 */
#define DATA_MAGIC  0x4B485332u                 /* "KHS2" */
#define VRAM        ((volatile u16 *)0x25E00000)
#define STRIDE      1024                        /* bitmap is 1024 x 256, RGB555 */
#define BAR_Y       228
#define BAR_H       12
#define SCREEN_W    640
#define MARK_POS    ((BAR_Y + BAR_H - 1) * STRIDE + SCREEN_W - 1)
#define MARK        0x0001                      /* near-black, tells us the bar is ours */
#define BG          0x0000
#define MAX_AUDIO   4
#define VOICE_SLOT  (*(volatile u16 *)(0x25B00000 + 12 * 0x20))    /* SCSP slot 12, KYONB = 0x0800 */
#define KEYON_WAIT      120
#define KEYON_FALLBACK  39

#define VBLANKS     (*(volatile u32 *)0x060730D0)
#define WAIT_VBLANK ((void (*)(void))0x0604A500)
#define READ_FILE   ((int (*)(const char *, void *))0x06010CD4)

struct header { u32 magic; u16 ncues, nglyphs; u32 cues, glyphs, text, bits; };
struct cue { u8 audio, pad; u16 start, end, text, nchars, x; };
struct glyph { u16 width, bits; };

static int loaded_scene = -1;
static int loaded = 0;
static int cur = -1;            /* cue drawn in the bar, -1 = bar clear */
static int nplay = 0;
static u32 called[MAX_AUDIO] = { 0 };   /* vblank of the play call */
static u32 anchor[MAX_AUDIO] = { 0 };   /* vblank the voice started sounding */
static u8 started[MAX_AUDIO] = { 0 };
static u8 seen_off[MAX_AUDIO] = { 0 };
static char name[] = "SUB1.DAT";

static const u16 pal[4] = { BG, 0x8000 | 10 << 10 | 10 << 5 | 10,
                            0x8000 | 21 << 10 | 21 << 5 | 21, 0xFFFF };

/* gcc for SH-4 turns constant shifts into shad; force SH-2 shift sequences */
static inline int shr2(int x) { __asm__("shlr2 %0" : "+r"(x)); return x; }
static inline int shr4(int x) { __asm__("shlr2 %0\n\tshlr2 %0" : "+r"(x)); return x; }
static inline int shr6(int x) { __asm__("shlr2 %0\n\tshlr2 %0\n\tshlr2 %0" : "+r"(x)); return x; }

static inline void purge_cache(void)
{
    volatile u8 *ccr = (volatile u8 *)0xFFFFFE92;
    *ccr = *ccr | 0x10;
}

void sub_on_load(const char *picture)
{
    /* the scene is the digit in the picture name, "vis3_1s.pxt" -> 3 */
    int scene = picture[3] - '0';
    nplay = 0;                  /* pictures are loaded before the first voice */
    cur = -1;
    if (scene == loaded_scene && loaded)
        return;
    loaded = 0;
    loaded_scene = scene;
    if (scene < 1 || scene > 7)
        return;
    name[3] = (char)('0' + scene);
    if (READ_FILE(name, (void *)DATA) >= 0) {
        purge_cache();
        loaded = ((const struct header *)DATA)->magic == DATA_MAGIC;
    }
}

void sub_on_play(void)
{
    if (nplay < MAX_AUDIO) {
        called[nplay] = VBLANKS;
        started[nplay] = seen_off[nplay] = 0;
        nplay++;
    }
}

/* the newest voice starts when slot 12 goes from key-off to key-on after its play call */
static void watch_keyon(u32 now)
{
    int a = nplay - 1;
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

static void draw(int idx)
{
    const struct header *h = (const struct header *)DATA;
    volatile u32 *row32 = (volatile u32 *)(VRAM + BAR_Y * STRIDE);
    for (int y = 0; y < BAR_H; y++, row32 += STRIDE / 2)
        for (int x = 0; x < SCREEN_W / 2; x++)
            row32[x] = BG << 16 | BG;
    if (idx >= 0) {
        const struct cue *c = (const struct cue *)(DATA + h->cues) + idx;
        const u16 *text = (const u16 *)(DATA + h->text) + c->text;
        const struct glyph *gl = (const struct glyph *)(DATA + h->glyphs);
        int x = c->x;
        for (int i = 0; i < c->nchars; i++) {
            const struct glyph *g = gl + text[i];
            int w = g->width, pitch = (w + 3) >> 2;
            const u8 *bits = DATA + h->bits + g->bits;
            volatile u16 *dst = VRAM + BAR_Y * STRIDE + x;
            for (int y = 0; y < BAR_H; y++, bits += pitch, dst += STRIDE) {
                /* 4 pixels per byte, MSB first */
                for (int bx = 0; bx < pitch; bx++) {
                    int b = bits[bx];
                    volatile u16 *d = dst + (bx << 2);
                    if (b & 0xC0) d[0] = pal[shr6(b) & 3];
                    if (b & 0x30) d[1] = pal[shr4(b) & 3];
                    if (b & 0x0C) d[2] = pal[shr2(b) & 3];
                    if (b & 0x03) d[3] = pal[b & 3];
                }
            }
            x += w;
        }
    }
    VRAM[MARK_POS] = MARK;
    cur = idx;
}

#ifdef SUBLOG
/* diagnostic: per frame after each play call, the key-on state of all 32 SCSP slots */
struct logrec { u16 dt, reg0_12; u32 keyon; };
#define LOG ((volatile struct logrec *)0x0608C800)
#define LOG_N 100
static void log_frame(u32 now)
{
    for (int a = 0; a < nplay && a < 2; a++) {
        u32 dt = now - called[a];
        if (dt >= LOG_N)
            continue;
        u32 mask = 0, bit = 1;
        for (int s = 0; s < 32; s++, bit += bit)
            if (*(volatile u16 *)(0x25B00000 + s * 0x20) & 0x0800)
                mask |= bit;
        volatile struct logrec *r = LOG + a * LOG_N + dt;
        r->dt = (u16)dt;
        r->reg0_12 = *(volatile u16 *)(0x25B00000 + 12 * 0x20);
        r->keyon = mask;
    }
}
#endif

void sub_on_frame(void)
{
    WAIT_VBLANK();
    u32 now = VBLANKS;
#ifdef SUBLOG
    log_frame(now);
#endif
    watch_keyon(now);
    if (!loaded)
        return;
    const struct header *h = (const struct header *)DATA;
    const struct cue *c = (const struct cue *)(DATA + h->cues);
    int idx = -1;
    for (int i = 0; i < h->ncues; i++) {
        if (c[i].audio >= nplay || !started[c[i].audio])
            continue;
        u32 t = now - anchor[c[i].audio];
        if (t >= c[i].start && t < c[i].end) {
            idx = i;
            break;
        }
    }
    /* redraw when the line changes, or when something repainted the bar */
    if (idx != cur || (cur >= 0 && VRAM[MARK_POS] != MARK))
        draw(idx);
}
