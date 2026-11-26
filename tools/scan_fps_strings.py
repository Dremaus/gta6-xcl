import re, sys

path = r"D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe"
data = open(path, "rb").read()
print("size", len(data))

terms = [
    "fidelity", "performance", "framelimit", "frame_limit", "fpslimit",
    "maxfps", "targetfps", "desiredfps", "vsync", "refreshrate",
    "qualitymode", "performancemode", "fpsmode", "30fps", "60fps",
]

def find_bytes(hay, needle, label):
    out = []
    start = 0
    while True:
        i = hay.find(needle, start)
        if i < 0:
            break
        out.append(i)
        start = i + 1
        if len(out) > 40:
            break
    return out

for t in terms:
    a = find_bytes(data, t.encode(), t + ":ascii")
    u = find_bytes(data, t.encode("utf-16-le"), t + ":utf16")
    if a or u:
        print(f"{t:16s} ascii={len(a)} utf16={len(u)} first={([hex(x) for x in a[:4]] + [hex(x) for x in u[:4]])}")
    else:
        print(f"{t:16s} none")

# dump contexts for fidelity-like hits
for t in ["fidelity", "performancemode", "framelimit", "maxfps", "targetfps"]:
    for enc, tag in [(None, "ascii"), ("utf-16-le", "utf16")]:
        needle = t.encode(enc) if enc else t.encode()
        idxs = find_bytes(data, needle, t)
        for i in idxs[:8]:
            lo = max(0, i - 60); hi = min(len(data), i + 90)
            ctx = data[lo:hi]
            txt = ctx.decode("latin-1", "replace")
            txt = "".join(c if 32 <= ord(c) < 127 else "." for c in txt)
            print(f"[{t}/{tag}] @{hex(i)}: {txt}")
