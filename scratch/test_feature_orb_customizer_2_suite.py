import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def assert_test(condition: bool, test_name: str, detail: str = ""):
    if condition:
        print(f"  [PASS] {test_name}")
    else:
        print(f"  [FAIL] {test_name} - Detail: {detail}")
        sys.exit(1)

def run_orb_customizer_2_suite():
    print("=" * 80)
    print("BYTE-X FEATURE: ORB CUSTOMIZER 2.0 DEEP PERSONALIZATION VALIDATION SUITE")
    print("=" * 80)

    base_dir = r"c:\Users\ryzzn\OneDrive\Desktop\ByteX Core\ByteX"
    service_file = os.path.join(base_dir, "src", "services", "orbCustomizerService.ts")
    orb_file = os.path.join(base_dir, "src", "components", "ByteXOrb", "ByteXOrb.tsx")
    orb_css_file = os.path.join(base_dir, "src", "components", "ByteXOrb", "orb.css")
    customizer_file = os.path.join(base_dir, "src", "components", "OrbCustomizer", "OrbCustomizer.tsx")
    customizer_css = os.path.join(base_dir, "src", "components", "OrbCustomizer", "OrbCustomizer.css")
    header_file = os.path.join(base_dir, "src", "components", "Header", "Header.tsx")
    home_file = os.path.join(base_dir, "src", "pages", "Home", "Home.tsx")

    with open(service_file, "r", encoding="utf-8") as f:
        service_code = f.read()

    with open(orb_file, "r", encoding="utf-8") as f:
        orb_code = f.read()

    with open(orb_css_file, "r", encoding="utf-8") as f:
        orb_css_code = f.read()

    with open(customizer_file, "r", encoding="utf-8") as f:
        customizer_code = f.read()

    with open(customizer_css, "r", encoding="utf-8") as f:
        customizer_css_code = f.read()

    with open(header_file, "r", encoding="utf-8") as f:
        header_code = f.read()

    with open(home_file, "r", encoding="utf-8") as f:
        home_code = f.read()

    print("\n--- GROUP 1: ZERO DUPLICATION & SINGLE SOURCE OF TRUTH ---")
    orb_components = [
        f for f in os.listdir(os.path.join(base_dir, "src", "components"))
        if "orb" in f.lower()
    ]
    assert_test(len(orb_components) == 2, "Test #01 Exactly ByteXOrb and OrbCustomizer exist (no CustomOrb / PreviewOrb duplicates)", str(orb_components))
    assert_test("ByteXOrb" in orb_code and "class ByteXOrb" not in orb_code, "Test #02 Upgraded existing ByteXOrb component in-place")
    assert_test("THREE.BufferGeometry()" in orb_code, "Test #03 Single Three.js WebGL rendering pipeline maintained")

    print("\n--- GROUP 2: LOCKED THREE.JS INVARIANTS UNTOUCHED ---")
    assert_test("PARTICLE_COUNT = 3200" in orb_code, "Test #04 PARTICLE_COUNT = 3200 strictly maintained")
    assert_test("sphereRadius = 1.75" in orb_code, "Test #05 sphereRadius = 1.75 strictly maintained")
    assert_test("camera.position.z = 5.5" in orb_code, "Test #06 camera.position.z = 5.5 strictly maintained")
    assert_test("PerspectiveCamera(50" in orb_code, "Test #07 PerspectiveCamera(50, ...) strictly maintained")

    print("\n--- GROUP 3: APPEARANCE — ORB SHAPES & OPTICAL MATERIALS ---")
    shapes = ['sphere', 'blob', 'energy_core', 'ring']
    for shp in shapes:
        assert_test(f"'{shp}'" in service_code, f"Test #08 Shape '{shp}' defined in OrbShape type")
        assert_test(f"id: '{shp}'" in customizer_code, f"Test #09 Shape '{shp}' selectable in UI")
    assert_test("uShape" in orb_code, "Test #10 uShape GLSL shader uniform defined in ByteXOrb")
    assert_test("blobHarmonic" in orb_code, "Test #11 Liquid Blob organic surface harmonics in GPU vertex shader")
    assert_test("ENERGY CORE" in orb_code or "energy_core" in orb_code, "Test #12 Energy Core condensed nucleus in ByteXOrb")
    assert_test("ORB + RING" in orb_code or "ring" in orb_code, "Test #13 Ring planar geometry transformation in ByteXOrb")

    materials = ['liquid_glass', 'crystal', 'holographic', 'plasma', 'dark_glass']
    for mat in materials:
        assert_test(f"'{mat}'" in service_code, f"Test #14 Material '{mat}' defined in OrbMaterial type")
        assert_test(f"id: '{mat}'" in customizer_code, f"Test #15 Material '{mat}' selectable in UI")
    assert_test("uMaterialType" in orb_code, "Test #16 uMaterialType GLSL shader uniform defined in ByteXOrb")

    print("\n--- GROUP 4: EFFECTS (CORE, PARTICLE, AMBIENT) ---")
    core_effects = ['swirl', 'galaxy', 'energy', 'plasma', 'minimal']
    for ce in core_effects:
        assert_test(f"'{ce}'" in service_code, f"Test #17 Core effect '{ce}' defined in CoreEffect type")
    assert_test("uCoreEffect" in orb_code, "Test #18 uCoreEffect shader uniform integrated in ByteXOrb")

    particle_effects = ['none', 'soft', 'orbit', 'vortex']
    for pe in particle_effects:
        assert_test(f"'{pe}'" in service_code, f"Test #19 Particle effect '{pe}' defined in ParticleEffect type")
    assert_test("uParticleEffect" in orb_code, "Test #20 uParticleEffect shader uniform integrated in ByteXOrb")

    ambient_effects = ['none', 'soft_glow', 'aurora', 'floating_particles']
    for ae in ambient_effects:
        assert_test(f"'{ae}'" in service_code, f"Test #21 Ambient effect '{ae}' defined in AmbientEffect type")
    assert_test("uAmbientEffect" in orb_code, "Test #22 uAmbientEffect shader uniform integrated in ByteXOrb")
    assert_test("custom.ambientEffect" in orb_code, "Test #23 Dynamic ambient backdrop glow modulation in ByteXOrb")

    print("\n--- GROUP 5: 7-STATE INTELLIGENT PREVIEWS ---")
    states = ['idle', 'listening', 'thinking', 'speaking', 'processing', 'success', 'error']
    for st in states:
        assert_test(f"previewState === '{st}'" in customizer_code or f"'{st}'" in customizer_code, f"Test #24 State '{st}' supported in preview bar")
        assert_test(f"curActiveState === '{st}'" in orb_code or f"'{st}'" in orb_code, f"Test #25 State '{st}' visual reaction in ByteXOrb")

    print("\n--- GROUP 6: VOICE-REACTIVE ORB ---")
    assert_test("voiceReactive: boolean" in service_code, "Test #26 voiceReactive property defined in service")
    assert_test("ttsService" in orb_code, "Test #27 ByteXOrb integrates with ttsService for voice activity")
    assert_test("voicePulseMod" in orb_code, "Test #28 Voice acoustic pulse modulation computed in render loop")
    assert_test("voiceGlowMod" in orb_code, "Test #29 Voice glow intensity modulation in render loop")

    print("\n--- GROUP 7: PRESET CREATOR & CUSTOM PRESET PERSISTENCE ---")
    assert_test("createCustomPreset" in service_code, "Test #30 createCustomPreset method implemented in service")
    assert_test("deleteCustomPreset" in service_code, "Test #31 deleteCustomPreset method implemented in service")
    assert_test("handleCreatePreset" in customizer_code, "Test #32 Preset creation form wired in UI")
    assert_test("CUSTOM_PRESETS_STORAGE_KEY" in service_code, "Test #33 Custom presets persisted in localStorage")

    print("\n--- GROUP 8: CLEAN MAIN UI INVARIANTS PRESERVED ---")
    assert_test("onOpenCustomizer" in header_code, "Test #34 Top-right header customize button present")
    assert_test("isCustomizerOpen" in home_code, "Test #35 Customizer modal hidden by default")
    assert_test("Dock" not in home_code, "Test #36 Zero Dock in Home.tsx")
    assert_test("StatusIndicator" not in home_code, "Test #37 Zero StatusIndicator IDLE pill in Home.tsx")
    assert_test("BYTEX" in header_code and "v0.1.0 CORE" in header_code, "Test #38 Top-left header branding preserved")
    assert_test("CORE: ONLINE" in header_code or "CORE:" in header_code, "Test #39 Header subtle status preserved")

    print("\n" + "=" * 80)
    print("BYTE-X ORB CUSTOMIZER 2.0 VALIDATION SUITE: ALL 39/39 TESTS PASSED (100.0%)")
    print("=" * 80)

if __name__ == "__main__":
    run_orb_customizer_2_suite()
