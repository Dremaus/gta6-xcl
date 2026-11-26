import struct, sys

path = r"D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe"
data = open(path, "rb").read()

# minimal PE parse
pe_off = struct.unpack_from("<I", data, 0x3C)[0]
assert data[pe_off:pe_off+4] == b"PE\0\0"
nsec = struct.unpack_from("<H", data, pe_off+6)[0]
sizeopt = struct.unpack_from("<H", data, pe_off+20)[0]
image_base = struct.unpack_from("<Q", data, pe_off+24+48+104)[0]  # OptionalHeader+DataDirectory... safer below
# standard: OptionalHeader magic at pe_off+24; for PE32+ ImageBase at +24+24
magic = struct.unpack_from("<H", data, pe_off+24)[0]
assert magic == 0x20b, hex(magic)
image_base = struct.unpack_from("<Q", data, pe_off+24+24)[0]
sec_off = pe_off + 24 + sizeopt
sections = []
for i in range(nsec):
    o = sec_off + i*40
    name = data[o:o+8].rstrip(b"\0").decode()
    va, vsz = struct.unpack_from("<II", data, o+12)
    rawsz, rawoff = struct.unpack_from("<II", data, o+16)
    sections.append((name, va, vsz, rawoff, rawsz))

target_rva = 0x11170ae
for name, va, vsz, rawoff, rawsz in sections:
    if va <= target_rva < va + max(vsz, rawsz):
        off = rawoff + (target_rva - va)
        print(f"section {name} va=0x{va:x} rawoff=0x{rawoff:x} file_off=0x{off:x}")
        break
else:
    print("RVA not in any section"); sys.exit(1)

print(f"image_base=0x{image_base:x}  fault VA=0x{image_base+target_rva:x}")

# dump surrounding bytes for disassembly
start = off - 0x120
end = off + 0x120
chunk = data[max(0,start):min(len(data),end)]
open(r"D:\git\gta6-30fps\research\crash_region.bin", "wb").write(chunk)
print("wrote crash_region.bin, VA of chunk start:", hex(image_base + target_rva - (off-start)))
# hexdump the immediate area (64 bytes before, 32 after fault)
lo = off-96; hi = off+48
b = data[lo:hi]
print(" ".join(f"{x:02x}" for x in b))
