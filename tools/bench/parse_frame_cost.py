import re, sys, statistics as st

pat_long = re.compile(
    r"long frame (\d+) at ([\d.]+) s: (\d+) ms \| render thread: ran (\d+) ms \(user (\d+), kernel (\d+)\)"
)
pat_present = re.compile(r"in the present call ([\d.]+)")
pat_frame = re.compile(
    r"(\d+) fps, ([\d.]+) ms/frame \(([\d.]+) preparing: copies ([\d.]+) ms"
)
pat_draws = re.compile(r"(\d+) draws/frame")

def analyze(path):
    frames = []
    longs = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.replace("\x1b", "")
        line = re.sub(r"\[\d+m", "", line)
        m = pat_long.search(line)
        if m:
            longs.append(dict(
                ms=int(m.group(3)), ran=int(m.group(4)),
                user=int(m.group(5)), kernel=int(m.group(6)),
                present=float(pat_present.search(line).group(1)) if pat_present.search(line) else -1))
        m = pat_frame.search(line) and pat_draws.search(line)
        if m and pat_frame.search(line) and pat_draws.search(line):
            f = pat_frame.search(line); d = pat_draws.search(line)
            fps = float(f.group(1)); ms = float(f.group(2)); prep = float(f.group(3))
            copies = float(f.group(4))
            frames.append(dict(fps=fps, ms=ms, prep=prep, copies=copies,
                               draws=int(d.group(1))))
    print(f"== {path}")
    print(f"   frames logged: {len(frames)}, long frames: {len(longs)}")
    if frames:
        scene = [f for f in frames if f["draws"] > 300]
        menu = [f for f in frames if f["draws"] <= 300]
        for name, s in (("menu", menu), ("3D (draws>300)", scene)):
            if not s:
                continue
            ms = [f["ms"] for f in s]
            prep = [f["prep"] for f in s]
            copies = [f["copies"] for f in s]
            draws = [f["draws"] for f in s]
            print(f"   {name}: n={len(s)} draws med={st.median(draws):.0f} "
                  f"ms/frame med={st.median(ms):.1f} p90={(sorted(ms)[int(len(ms)*0.9)] if len(ms) > 3 else max(ms)):.1f} "
                  f"preparing med={st.median(prep):.1f} copies-part med={st.median(copies):.1f}")
    if longs:
        ran = [l["ran"] for l in longs]
        usr = [l["user"] for l in longs]
        ker = [l["kernel"] for l in longs]
        pre = [l["present"] for l in longs]
        ms = [l["ms"] for l in longs]
        print(f"   long frames n={len(longs)}: total med={st.median(ms):.0f} | "
              f"render-ran med={st.median(ran):.0f} (user {st.median(usr):.0f} + kernel {st.median(ker):.0f}) | "
              f"present med={st.median(pre):.1f}")
        print(f"   non-render remainder med = {st.median([m-r for m,r in zip(ms,ran)]):.0f} ms/frame")

for p in sys.argv[1:]:
    analyze(p)
