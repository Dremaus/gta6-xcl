import sys

def joaat(s):
    s = s.lower()
    h = 0
    for c in s:
        h = (h + ord(c)) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= (h >> 6)
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= (h >> 11)
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h

targets = {
    0x1141d443, 0x112b5803, 0xb80c6ae8, 0xc261c244, 0xee190b4e, 0x36f410b7,
    0xc63c7f4b, 0x3300c23e, 0xeb939e04, 0x4d0a80ab, 0x8372d0df, 0xfd1f33fa,
    0x4363a460, 0xb02a2016, 0x8342ef5b, 0x112c08e2, 0xa3c8e512, 0xd7019faa,
    0x25584db6, 0x8f12d59c, 0xace30d6c, 0x9c7b93d4, 0xe2e6345e, 0xed198e18,
    0x1b2bda37, 0xcaee6b0a, 0x136de0ae, 0x333bd514, 0x204a3c24, 0x81c34782,
    0xc88b583c, 0xcc88f951, 0xf536180b, 0xf201661a, 0x6fe4acbb, 0x3b763d08,
    0x4aec077e, 0x615e837e, 0x490691e6, 0xe76cda01, 0x6a510681, 0x9c7d4584,
    0x2202fbe1, 0xc44990e6, 0x203e2854, 0x3a6064da, 0x3d5a6716, 0x29b8d65c,
    0xf9ae08c1, 0x9c002b5e, 0xb5374df3, 0xacb7d548, 0xef1089a0, 0xcb20b040,
    0xe093af66, 0x3c30a629, 0xcb0db478, 0xe638e9dd, 0x2e4a3f2c, 0x40db3318,
    0x10d6ddf3, 0x23683a0d, 0xfb387d8b, 0xa28adf98, 0xdf2fa169, 0xdd86be4c,
    0x0db758b2, 0x47b6d29d, 0xa9666ef8, 0x55c189fe, 0xf9713d90, 0xfbb6b1ae,
    0x3a90a545, 0x4f0176b6, 0x316ef516, 0xe08766ba,
}

words = """
versionMajor versionMinor hdr hdrIntensity hdrPeakBrightnessUIDefaultNits
hdrPeakBrightnessGameDefaultNits hdrPeakBrightnessManuallyChanged
hdrPeakBrightness hdrBlackLevels hdrFilmicMode gamma anisotropicFiltering
desiredFPS fsrQuality graphicsQualityPreset asyncComputeEnabled
damageModelsEnabled decorationResolutionShift
directionalScreenSpaceShadowQuality fsrSharpen grassLod lodScale
texLodScale_Global texLodScale_Mat_High texLodScale_Mat_Medium
texLodScale_Mat_Low textureQuality shadingQuality reflectionQuality
waterQuality shadowQuality particleQuality drawDistance lodQuality
frameRateLimit vSync refreshRate numerator denominator resolutionFullscreen
resolutionWindowed width height tripleBuffered videoCardDescription
fpsMode performanceMode fidelity performance qualityMode balanceMode
ultraQualityMode framerate fps displayMode vsyncMode screenMode
resolution windowedMode fullscreenMode antiAliasing txaa msaa
grassQuality treeQuality buildingQuality vehicleQuality pedQuality
skyQuality cloudQuality volumetricQuality rayTracingQuality
dlssQuality fsrVersion fsrMode imageScaling brightness contrast
saturation chromaticAberration motionBlur filmGrain vignette
ambientOcclusion ssao hbao rayTracing reflections globalIllumination
shadowResolution softShadows cascadeShadows contactShadows
textureFiltering anisotropic LOD popIn trafficDensity crowdDensity
drawScale shadowDistance reflectionDistance waterDetail
""".split()

hits = []
for w in words:
    for style, s in [("lower", w.lower()), ("exact", w)]:
        h = joaat(s)
        if h in targets:
            hits.append((hex(h), style, s))
            print(f"MATCH joaat({style}): {s!r} -> 0x{h:08x}")

print(f"\n{len(hits)} matches out of {len(words)*2} trials")
if not hits:
    print("joaat not the hash (or words wrong). Sample joaat:", ", ".join(f"{w}=0x{joaat(w.lower()):08x}" for w in words[:6]))
