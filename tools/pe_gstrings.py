import struct

path = r"D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe"
data = open(path, "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
nsec = struct.unpack_from("<H", data, pe+6)[0]
sizeopt = struct.unpack_from("<H", data, pe+20)[0]
sec_off = pe + 24 + sizeopt
secs = []
for i in range(nsec):
    o = sec_off + i*40
    name = data[o:o+8].rstrip(b"\0").decode()
    va, vsz, rawsz, rawoff = struct.unpack_from("<IIII", data, o+12)
    secs.append((name, va, vsz, rawoff, rawsz))

def rva2off(rva):
    for name, va, vsz, rawoff, rawsz in secs:
        if va <= rva < va + max(vsz, rawsz):
            return rawoff + (rva - va), name
    return None, None

# globals referenced: VA 0x140000000 base
for label, va in [("array_base_global", 0x148982228), ("count_global", 0x148982225),
                  ("str1", 0x14111705d + 7 + 0x786b02c), ("other_calls", None)]:
    if va is None: continue
    rva = va - 0x140000000
    off, sec = rva2off(rva)
    if off is None:
        print(f"{label}: VA {va:#x} not mapped"); continue
    raw = data[off:off+80]
    txt = raw.split(b"\0")[0]
    print(f"{label}: VA {va:#x} sec {sec} bytes {raw[:16].hex()}")
    try:
        s = txt.decode("utf-8")
        if len(s) > 3: print(f"   ascii: {s!r}")
    except: pass
    # also as UTF-16
    try:
        s2 = data[off:off+160].split(b"\0\0")[0].decode("utf-16-le")
        if len(s2) > 3 and all(32 <= ord(c) < 127 for c in s2[:40]):
            print(f"   utf16: {s2!r}")
    except: pass

# call targets — find which functions these are (nearest preceding symbol-ish string? just show bytes)
for tva in [0x145252bd0, 0x144d9c140, 0x145647140]:
    rva = tva - 0x140000000
    off, sec = rva2off(rva)
    if off is not None:
        print(f"call target {tva:#x} in {sec}: {data[off:off+24].hex()}")
