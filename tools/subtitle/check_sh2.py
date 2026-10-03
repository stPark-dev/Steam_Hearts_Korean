"""Reject SH-3/SH-4-only instructions in an objdump listing (SH-2 has none of these)."""
import re, sys
BAD = {"shad", "shld", "pref", "movca.l", "ocbi", "ocbp", "ocbwb", "ldtlb", "clrs", "sets",
       "fmov", "fmov.s", "fadd", "fsub", "fmul", "fdiv", "flds", "fsts", "float", "ftrc", "fschg",
       "frchg", "lds.l", "sts.l"}
OK_LDS = re.compile(r"(lds|sts)(\.l)?\s+(@r\d+\+,\s*)?(pr|mach|macl|r\d+)(,\s*(pr|mach|macl|@-r\d+|r\d+))?$")
bad = []
for line in open(sys.argv[1]):
    m = re.match(r"\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} ){2}\s*(\S+)\s*(.*)", line)
    if not m:
        continue
    op, args = m.group(2), m.group(3).split("!")[0].strip()
    if op in ("lds", "lds.l", "sts", "sts.l"):
        if re.search(r"fpul|fpscr", args):
            bad.append(line.strip())
        continue
    if op in BAD or op.startswith("f") and op not in ():
        bad.append(line.strip())
    if re.search(r"\b(r\d_bank|ssr|spc|sgr|dbr)\b", args):
        bad.append(line.strip())
print("\n".join(bad) if bad else "SH-2 check: ok")
sys.exit(1 if bad else 0)
