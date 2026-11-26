import zlib, sys

# observed hashed keys from the ASAV settings container
targets = {
    0x1141d443, 0x112b5803, 0xb80c6ae8, 0xc261c244, 0xee190b4e, 0x36f410b7,
    0xc63c7f4b, 0x3300c23e, 0xeb939e04, 0x4d0a80ab, 0x8372d0df, 0xfd1f33fa,
    0x4363a460, 0xb02a2016, 0x8342ef5b, 0x112c08e2, 0xa3c8e512, 0xd7019faa,
    0x25584db6, 0x8f12d59c, 0xace30d6c, 0x9c7b93d4, 0xe2e6345e, 0xed198e18,
    0x1b2bda37, 0xcaee6b0a, 0x136de0ae, 0x333bd514, 0x204a3c24, 0x81c34782,
}

words = [
    "versionMajor", "versionMinor", "hdr", "hdrIntensity", "gamma",
    "anisotropicFiltering", "desiredFPS", "fsrQuality", "graphicsQualityPreset",
    "frameRateLimit", "vSync", "refreshRate", "numerator", "denominator",
    "resolutionFullscreen", "tripleBuffered", "asyncComputeEnabled",
    "lodScale", "texLodScale_Global", "grassLod", "damageModelsEnabled",
    "fsrSharpen", "hdrPeakBrightness", "hdrBlackLevels", "hdrFilmicMode",
    # plausible fps-mode names
    "fpsMode", "performanceMode", "fidelity", "performance", "qualityMode",
    "framerate", "frameRate", "fps", "graphicsMode", "displayMode",
]

def fnv1a(s):
    h = 0x811C9DC5
    for c in s.encode():
        h ^= c
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h

def fnv1(s):
    h = 0x811C9DC5
    for c in s.encode():
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= c
    return h

def djb2(s):
    h = 5381
    for c in s.encode():
        h = ((h * 33) + c) & 0xFFFFFFFF
    return h

def sdbm(s):
    h = 0
    for c in s.encode():
        h = (c + (h << 6) + (h << 16) - h) & 0xFFFFFFFF
    return h

def murmur_like(s):
    # simple x32-style
    h = 0x9DC5
    for c in s.encode():
        h ^= c
        h = (h * 0x5BD1E995) & 0xFFFFFFFF
        h ^= (h >> 15)
    return h

algos = {
    "crc32": lambda s: zlib.crc32(s.encode()) & 0xFFFFFFFF,
    "adler32": lambda s: zlib.adler32(s.encode()) & 0xFFFFFFFF,
    "fnv1a": fnv1a,
    "fnv1": fnv1,
    "djb2": djb2,
    "sdbm": sdbm,
    "murmurx": murmur_like,
}

hits = []
for name, f in algos.items():
    for w in words:
        for variant, v in [("lower", w.lower()), ("exact", w), ("upper", w.upper())]:
            h = f(v)
            if h in targets:
                hits.append((name, variant, v, hex(h)))
print("HITS:", hits if hits else "none")
