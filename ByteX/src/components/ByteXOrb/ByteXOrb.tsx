import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { OrbState } from '../../types/orb';
import { ORB_STATE_CONFIGS } from '../../types/orb';
import {
  orbCustomizerService,
  type OrbCustomizationSettings
} from '../../services/orbCustomizerService';
import ttsService from '../../services/ttsService';
import sttService from '../../services/sttService';
import './orb.css';

interface ByteXOrbProps {
  state?: OrbState;
  onClick?: () => void;
  customization?: Partial<OrbCustomizationSettings>;
}

export const ByteXOrb: React.FC<ByteXOrbProps> = ({ state = 'idle', onClick, customization }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<OrbState>(state);
  const previewStateRef = useRef<OrbState | null>(orbCustomizerService.getPreviewState());
  const backdropRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const customSettingsRef = useRef<OrbCustomizationSettings>({
    ...orbCustomizerService.getSettings(),
    ...(customization || {}),
  });

  const updateBackdropGlow = () => {
    if (!backdropRef.current) return;
    const activeState = previewStateRef.current || stateRef.current || 'idle';
    const config = ORB_STATE_CONFIGS[activeState] || ORB_STATE_CONFIGS.idle;
    const custom = customSettingsRef.current;

    let pColor = custom.primaryColor || config.primaryColor;
    let sColor = custom.glowColor || config.secondaryColor;

    if (activeState === 'listening') {
      pColor = '#00ffee';
      sColor = custom.glowColor || '#0088ff';
    } else if (activeState === 'thinking') {
      pColor = '#a855f7';
      sColor = '#38bdf8';
    } else if (activeState === 'speaking') {
      pColor = '#38bdf8';
      sColor = custom.primaryColor || '#00f0ff';
    } else if (activeState === 'processing') {
      pColor = '#00f0ff';
      sColor = '#a855f7';
    } else if (activeState === 'success') {
      pColor = '#00f0ff';
      sColor = '#10b981';
    } else if (activeState === 'error') {
      pColor = '#ef4444';
      sColor = '#f97316';
    }

    const glowMult = custom.glowIntensity || 1.0;
    const opacityMult = custom.opacity !== undefined ? custom.opacity : 1.0;

    // Handle Ambient Effect in Backdrop
    if (custom.ambientEffect === 'none') {
      backdropRef.current.style.opacity = '0';
    } else if (custom.ambientEffect === 'aurora') {
      backdropRef.current.style.background = `radial-gradient(circle, ${pColor} 0%, #8a2be2 40%, ${sColor} 70%, transparent 88%)`;
      backdropRef.current.style.opacity = `${config.glowIntensity * 0.52 * glowMult * opacityMult}`;
    } else {
      backdropRef.current.style.background = `radial-gradient(circle, ${pColor} 0%, #0066ff 38%, ${sColor} 68%, transparent 85%)`;
      backdropRef.current.style.opacity = `${config.glowIntensity * 0.46 * glowMult * opacityMult}`;
    }

    if (ringRef.current) {
      const showRing = custom.showRing || custom.shape === 'ring';
      ringRef.current.style.display = showRing ? 'block' : 'none';
      ringRef.current.style.borderColor = activeState === 'idle' ? `${pColor}33` : `${config.primaryColor}44`;
    }
  };

  useEffect(() => {
    stateRef.current = state;
    updateBackdropGlow();
  }, [state]);

  useEffect(() => {
    if (customization) {
      customSettingsRef.current = {
        ...customSettingsRef.current,
        ...customization,
      };
      updateBackdropGlow();
    }
  }, [customization]);

  useEffect(() => {
    const unsub = orbCustomizerService.subscribe((settings, previewState) => {
      customSettingsRef.current = {
        ...settings,
        ...(customization || {}),
      };
      previewStateRef.current = previewState;
      updateBackdropGlow();
    });
    return unsub;
  }, [customization]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || 600;
    const height = container.clientHeight || 520;

    // --- 1. Scene, Camera, Renderer Setup (LOCKED) ---
    const scene = new THREE.Scene();
    scene.background = null;

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
    camera.position.z = 5.5;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Main rotating group
    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // --- 2. Pure Spherical Formation (LOCKED DIMENSIONS) ---
    const PARTICLE_COUNT = 3200;
    const geometry = new THREE.BufferGeometry();

    const spherePositions = new Float32Array(PARTICLE_COUNT * 3);
    const randomOffsets = new Float32Array(PARTICLE_COUNT);
    const isCoreArray = new Float32Array(PARTICLE_COUNT);
    const particleColors = new Float32Array(PARTICLE_COUNT * 3);

    const sphereRadius = 1.75;

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);

      // Layered spherical orb distribution: 25% core nodes, 75% surface shell
      const isCoreNode = i % 4 === 0;
      const r = isCoreNode
        ? sphereRadius * (0.25 + Math.random() * 0.5)
        : sphereRadius * (0.85 + Math.random() * 0.25);

      const sx = r * Math.sin(phi) * Math.cos(theta);
      const sy = r * Math.sin(phi) * Math.sin(theta);
      const sz = r * Math.cos(phi);

      spherePositions[i * 3] = sx;
      spherePositions[i * 3 + 1] = sy;
      spherePositions[i * 3 + 2] = sz;

      randomOffsets[i] = Math.random();
      isCoreArray[i] = isCoreNode ? 1.0 : 0.0;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(spherePositions, 3));
    geometry.setAttribute('aRandomOffset', new THREE.BufferAttribute(randomOffsets, 1));
    geometry.setAttribute('aIsCore', new THREE.BufferAttribute(isCoreArray, 1));
    geometry.setAttribute('aColor', new THREE.BufferAttribute(particleColors, 3));

    // --- 3. Custom GLSL ShaderMaterial with Atmospheric Particle Bloom & Material Shaders ---
    const activeState = previewStateRef.current || stateRef.current || 'idle';
    const initialConfig = ORB_STATE_CONFIGS[activeState] || ORB_STATE_CONFIGS.idle;
    const initialCustom = customSettingsRef.current;

    const particleMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uParticleSize: { value: initialConfig.particleSize },
        uGlowIntensity: { value: initialConfig.glowIntensity * initialCustom.glowIntensity },
        uOpacity: { value: initialCustom.opacity },
        uMaterialType: { value: 0.0 },   // 0: liquid_glass, 1: crystal, 2: holographic, 3: plasma, 4: dark_glass
        uShape: { value: 0.0 },          // 0: sphere, 1: blob, 2: energy_core, 3: ring
        uCoreEffect: { value: 0.0 },     // 0: swirl, 1: galaxy, 2: energy, 3: plasma, 4: minimal
        uParticleEffect: { value: 1.0 }, // 0: none, 1: soft, 2: orbit, 3: vortex
        uAmbientEffect: { value: 1.0 },  // 0: none, 1: soft_glow, 2: aurora, 3: floating_particles
        uVoiceMod: { value: 0.0 },
      },
      vertexShader: `
        uniform float uTime;
        uniform float uParticleSize;
        uniform float uMaterialType;
        uniform float uShape;
        uniform float uCoreEffect;
        uniform float uParticleEffect;
        uniform float uAmbientEffect;
        uniform float uVoiceMod;
        
        attribute float aRandomOffset;
        attribute float aIsCore;
        attribute vec3 aColor;

        varying vec3 vColor;
        varying float vDepthFactor;
        varying float vIsCore;
        varying float vHoloPhase;
        varying float vDispersal;

        void main() {
            vIsCore = aIsCore;
            vec3 basePos = position;
            float r = length(basePos);
            float theta = atan(basePos.y, basePos.x);
            float phi = acos(clamp(basePos.z / max(r, 0.001), -1.0, 1.0));

            // --- 1. SHAPE TRANSFORMATIONS ---
            if (uShape > 0.5 && uShape < 1.5) {
                // LIQUID BLOB: Organic multi-harmonic surface displacement
                float blobHarmonic = sin(theta * 3.0 + uTime * 2.2) * cos(phi * 2.5 + uTime * 1.8) * 0.45
                                   + sin(phi * 4.0 - uTime * 2.0) * 0.28;
                basePos += normalize(basePos) * blobHarmonic * (1.1 + 0.6 * aRandomOffset);
            } else if (uShape > 1.5 && uShape < 2.5) {
                // ENERGY CORE: High-density condensed nucleus + energetic burst rays
                if (aIsCore > 0.5 || aRandomOffset < 0.65) {
                    basePos *= 0.38;
                } else {
                    float rayPulse = sin(uTime * 6.0 + aRandomOffset * 25.0);
                    basePos *= (1.35 + rayPulse * 0.55);
                }
            } else if (uShape > 2.5 && uShape < 3.5) {
                // ORB + RING: Equatorial orbital disk + central sphere
                if (aRandomOffset > 0.40) {
                    basePos.y *= 0.06;
                    basePos.xz = normalize(basePos.xz) * (2.3 + aRandomOffset * 1.1);
                    float ringAngle = uTime * 0.8 + aRandomOffset * 6.28;
                    float rx = basePos.x * cos(ringAngle) - basePos.z * sin(ringAngle);
                    float rz = basePos.x * sin(ringAngle) + basePos.z * cos(ringAngle);
                    basePos.x = rx;
                    basePos.z = rz;
                } else {
                    basePos *= 0.62;
                }
            }

            // --- 2. CORE EFFECT MODULATIONS ---
            if (uCoreEffect > 0.5 && uCoreEffect < 1.5) {
                // GALAXY: Spiral Galactic Arms (Pinwheel)
                float distXZ = length(basePos.xz);
                float spiralAngle = distXZ * 3.2 - uTime * 2.0;
                float sx = basePos.x * cos(spiralAngle) - basePos.z * sin(spiralAngle);
                float sz = basePos.x * sin(spiralAngle) + basePos.z * cos(spiralAngle);
                basePos.x = sx;
                basePos.z = sz;
                basePos.y *= 0.55;
            } else if (uCoreEffect > 1.5 && uCoreEffect < 2.5) {
                // ENERGY: Explosive periodic energy bursts
                float burst = sin(uTime * 7.5 + aRandomOffset * 16.0) * 0.32;
                basePos += normalize(basePos + vec3(0.001)) * burst;
            } else if (uCoreEffect > 2.5 && uCoreEffect < 3.5) {
                // PLASMA: High frequency electric arc filament jitter
                vec3 jit = vec3(
                    sin(uTime * 22.0 + aRandomOffset * 35.0) * 0.16,
                    cos(uTime * 19.0 + aRandomOffset * 30.0) * 0.16,
                    sin(uTime * 24.0 + aRandomOffset * 40.0) * 0.16
                );
                basePos += jit;
            } else if (uCoreEffect > 3.5) {
                // MINIMAL: Ultra-tight clean distribution, zero jitter
                basePos *= 0.92;
            } else {
                // SWIRL: Tangential fluid vortex
                float swirlAngle = uTime * 1.4 + (basePos.y * 1.8);
                float sx = basePos.x * cos(swirlAngle) - basePos.z * sin(swirlAngle);
                float sz = basePos.x * sin(swirlAngle) + basePos.z * cos(swirlAngle);
                basePos.x = sx * 0.95;
                basePos.z = sz * 0.95;
            }

            // --- 3. PARTICLE EFFECT MODULATIONS ---
            if (uParticleEffect > 1.5 && uParticleEffect < 2.5) {
                // ORBIT: Satellite orbiting streams
                if (aRandomOffset > 0.50) {
                    float orbAngle = uTime * 2.2 + aRandomOffset * 6.28;
                    float orbR = 2.8 + aRandomOffset * 0.6;
                    basePos = vec3(cos(orbAngle) * orbR, sin(orbAngle * 1.2 + aRandomOffset * 3.14) * 0.9, sin(orbAngle) * orbR);
                }
            } else if (uParticleEffect > 2.5 && uParticleEffect < 3.5) {
                // VORTEX: Inward spiral vortex funnel
                float vDist = mod(r - uTime * 1.2 + aRandomOffset * 2.5, 3.0);
                float vAng = uTime * 4.0 + aRandomOffset * 6.28;
                basePos = vec3(cos(vAng) * vDist, (basePos.y * 0.5) + (vDist * 0.25 - 0.4), sin(vAng) * vDist);
            }

            // --- 4. AMBIENT EFFECT MODULATIONS ---
            if (uAmbientEffect > 2.5 && uAmbientEffect < 3.5) {
                // FLOATING PARTICLES: Stardust motes drifting outward into space
                if (aRandomOffset > 0.65) {
                    basePos += vec3(
                        sin(uTime * 0.6 + aRandomOffset * 14.0) * 1.4,
                        cos(uTime * 0.7 + aRandomOffset * 16.0) * 1.4,
                        sin(uTime * 0.5 + aRandomOffset * 10.0) * 1.4
                    );
                }
            }

            // Organic floating wave (suppressed in minimal mode)
            float waveScale = (uCoreEffect > 3.5) ? 0.01 : 0.04;
            vec3 wave = vec3(
                sin(uTime * 1.6 + aRandomOffset * 10.0) * waveScale,
                cos(uTime * 1.4 + aRandomOffset * 12.0) * waveScale,
                sin(uTime * 1.8 + aRandomOffset * 8.0) * waveScale
            );

            vec3 finalPos = basePos + wave;
            vec4 mvPosition = modelViewMatrix * vec4(finalPos, 1.0);
            gl_Position = projectionMatrix * mvPosition;

            float dist = -mvPosition.z;
            float coreMultiplier = (aIsCore > 0.5) ? 1.25 : 1.0;

            // Material size adjustments
            if (uMaterialType > 0.5 && uMaterialType < 1.5) {
                // Crystal: Sharp faceted gem points
                coreMultiplier *= 0.70;
            } else if (uMaterialType > 2.5 && uMaterialType < 3.5) {
                // Plasma: High energy discharge
                coreMultiplier *= 1.65;
            } else if (uMaterialType > 3.5) {
                // Dark Glass: Luminous rim points
                coreMultiplier *= 1.15;
            }

            gl_PointSize = (uParticleSize + uVoiceMod * 2.8) * coreMultiplier * (5.2 / dist);

            vDepthFactor = clamp((7.5 - dist) / 4.5, 0.35, 1.0);
            vHoloPhase = sin(mvPosition.z * 2.2 + uTime * 3.0);
            vDispersal = aRandomOffset;
            vColor = aColor;
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        varying float vDepthFactor;
        varying float vIsCore;
        varying float vHoloPhase;
        varying float vDispersal;
        uniform float uGlowIntensity;
        uniform float uOpacity;
        uniform float uMaterialType;

        void main() {
            vec2 coord = gl_PointCoord - vec2(0.5);
            float dist = length(coord);
            if (dist > 0.5) discard;

            float core = smoothstep(0.5, 0.0, dist);
            float bloom = pow(core, 1.25);
            float innerSpike = pow(core, 3.2);

            vec3 matColor = vColor;

            // 1. LIQUID GLASS (uMaterialType = 0)
            if (uMaterialType < 0.5) {
                float specular = pow(core, 4.5) * 1.8;
                bloom = pow(core, 1.15) * 1.5;
                matColor += vec3(specular * 0.75);
            }
            // 2. CRYSTAL (uMaterialType = 1)
            else if (uMaterialType > 0.5 && uMaterialType < 1.5) {
                innerSpike = pow(core, 6.5) * 3.2;
                bloom = pow(core, 3.0) * 0.55;
                matColor = mix(matColor * 0.75, vec3(1.0, 1.0, 1.0), innerSpike * 0.85);
            }
            // 3. HOLOGRAPHIC (uMaterialType = 2)
            else if (uMaterialType > 1.5 && uMaterialType < 2.5) {
                vec3 rainbow = vec3(
                    sin(vHoloPhase * 3.14 + vDispersal * 6.28) * 0.5 + 0.5,
                    sin(vHoloPhase * 3.14 + vDispersal * 6.28 + 2.09) * 0.5 + 0.5,
                    sin(vHoloPhase * 3.14 + vDispersal * 6.28 + 4.18) * 0.5 + 0.5
                );
                matColor = mix(matColor, rainbow, 0.85);
                bloom = pow(core, 1.05) * 1.6;
            }
            // 4. PLASMA (uMaterialType = 3)
            else if (uMaterialType > 2.5 && uMaterialType < 3.5) {
                bloom = pow(core, 0.75) * 2.3;
                innerSpike = pow(core, 1.8) * 2.2;
                matColor = mix(matColor, vec3(1.0, 0.92, 0.45), innerSpike * 0.65);
            }
            // 5. DARK GLASS (uMaterialType = 4)
            else if (uMaterialType > 3.5) {
                float rim = smoothstep(0.48, 0.25, dist) * smoothstep(0.08, 0.35, dist);
                bloom = rim * 3.4 + pow(core, 6.0) * 0.25;
                innerSpike = pow(core, 7.5) * 0.5;
                matColor = mix(vec3(0.02, 0.02, 0.06), vColor * 2.4, rim);
            }

            vec3 finalColor = matColor * (bloom * 1.65 + innerSpike * 0.85 + 0.25) * uGlowIntensity;
            float alpha = (bloom * 0.88 + innerSpike * 0.12) * vDepthFactor * 0.98 * uOpacity;

            gl_FragColor = vec4(finalColor, alpha);
        }
      `,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particleSystem = new THREE.Points(geometry, particleMaterial);
    mainGroup.add(particleSystem);

    // --- 4. Mouse Rotation Parallax ---
    let mouseX = 0;
    let mouseY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      mouseX = (x / (rect.width / 2)) * 0.6;
      mouseY = (y / (rect.height / 2)) * 0.6;
    };

    container.addEventListener('mousemove', handleMouseMove);

    // --- 5. Render Loop & Voice Reactivity Envelope Followers ---
    const clock = new THREE.Clock();
    let animationFrameId: number;

    const targetPrimaryColor = new THREE.Color(initialCustom.primaryColor || initialConfig.primaryColor);
    const targetSecondaryColor = new THREE.Color(initialCustom.glowColor || initialConfig.secondaryColor);
    const currentPrimaryColor = new THREE.Color(initialCustom.primaryColor || initialConfig.primaryColor);
    const currentSecondaryColor = new THREE.Color(initialCustom.glowColor || initialConfig.secondaryColor);

    // Continuous smoothed amplitude envelope followers (attack/release)
    let smoothedVoiceAmp = 0.0;
    let smoothedMicAmp = 0.0;

    // Premium Color Spectrum constants
    const deepBlue = new THREE.Color('#0066ff');
    const brightWhiteCyan = new THREE.Color('#e0ffff');

    const renderLoop = () => {
      animationFrameId = requestAnimationFrame(renderLoop);

      const elapsedTime = clock.getElapsedTime();
      const curActiveState = previewStateRef.current || stateRef.current || 'idle';
      const config = ORB_STATE_CONFIGS[curActiveState] || ORB_STATE_CONFIGS.idle;
      const custom = customSettingsRef.current;

      // Real-time audio amplitude monitoring
      const micRaw = sttService.getAudioAmplitude();
      const ttsRaw = ttsService.getAudioAmplitude();

      // Attack / Release envelope smoothing
      const micAlpha = micRaw > smoothedMicAmp ? 0.35 : 0.08;
      smoothedMicAmp += (micRaw - smoothedMicAmp) * micAlpha;

      const ttsAlpha = ttsRaw > smoothedVoiceAmp ? 0.35 : 0.08;
      smoothedVoiceAmp += (ttsRaw - smoothedVoiceAmp) * ttsAlpha;

      // Baseline low-frequency autonomous breathing (never static)
      const baselineBreathing = Math.sin(elapsedTime * 1.35) * 0.035;

      // Check real voice activity (is real TTS speaking or preview speaking with voiceReactive active)
      const isVoiceSpeaking = ttsService.isSpeaking() || curActiveState === 'speaking';
      let voicePulseMod = 0.0;
      let voiceGlowMod = 1.0;

      if (curActiveState === 'speaking' || isVoiceSpeaking) {
        // SPEAKING: Real-time TTS voice amplitude continuously drives scale, glow, and particle burst
        const speechAmp = ttsService.isSpeaking() ? smoothedVoiceAmp : (smoothedVoiceAmp || 0.45);
        voicePulseMod = speechAmp * 0.18 + Math.sin(elapsedTime * 18.0) * (speechAmp * 0.04);
        voiceGlowMod = 1.0 + speechAmp * 0.65;
      } else if (curActiveState === 'listening') {
        // LISTENING: Real-time microphone amplitude drives attentive organic breathing
        const inputAmp = smoothedMicAmp;
        voicePulseMod = inputAmp * 0.14 + Math.sin(elapsedTime * 4.0) * 0.05;
        voiceGlowMod = 1.0 + inputAmp * 0.45;
      }

      // Dynamic Uniform Mappings
      const shapeMap: Record<string, number> = {
        sphere: 0.0,
        blob: 1.0,
        energy_core: 2.0,
        ring: 3.0,
      };
      particleMaterial.uniforms.uShape.value = shapeMap[custom.shape] ?? 0.0;

      const materialMap: Record<string, number> = {
        liquid_glass: 0.0,
        crystal: 1.0,
        holographic: 2.0,
        plasma: 3.0,
        dark_glass: 4.0,
      };
      particleMaterial.uniforms.uMaterialType.value = materialMap[custom.material] ?? 0.0;

      const coreEffectMap: Record<string, number> = {
        swirl: 0.0,
        galaxy: 1.0,
        energy: 2.0,
        plasma: 3.0,
        minimal: 4.0,
      };
      particleMaterial.uniforms.uCoreEffect.value = coreEffectMap[custom.coreEffect] ?? 0.0;

      const particleEffectMap: Record<string, number> = {
        none: 0.0,
        soft: 1.0,
        orbit: 2.0,
        vortex: 3.0,
      };
      particleMaterial.uniforms.uParticleEffect.value = particleEffectMap[custom.particleEffect] ?? 0.0;

      const ambientEffectMap: Record<string, number> = {
        none: 0.0,
        soft_glow: 1.0,
        aurora: 2.0,
        floating_particles: 3.0,
      };
      particleMaterial.uniforms.uAmbientEffect.value = ambientEffectMap[custom.ambientEffect] ?? 0.0;

      // GPU vertex displacement reacts organically to voice amplitude
      particleMaterial.uniforms.uVoiceMod.value = voicePulseMod;

      // Speed multipliers based on style
      let styleSpeedMult = 1.0;
      let styleWaveMult = 1.0;
      if (custom.animationStyle === 'energetic') {
        styleSpeedMult = 1.25;
        styleWaveMult = 1.35;
      } else if (custom.animationStyle === 'calm') {
        styleSpeedMult = 0.75;
        styleWaveMult = 0.65;
      }

      const effectiveSpeed = (custom.animationSpeed || 1.0) * styleSpeedMult;
      const effectivePulseIntensity = (custom.pulseIntensity || 1.0);

      // State-specific time wave acceleration (Thinking runs faster, Speaking pulses rhythmically)
      const stateTimeMult = (curActiveState === 'thinking' || curActiveState === 'processing') 
        ? 2.2 
        : (curActiveState === 'speaking' ? 1.6 : 1.0);

      // Smooth state color transition
      let activePrimary = custom.primaryColor || config.primaryColor;
      let activeSecondary = custom.glowColor || config.secondaryColor;

      if (curActiveState === 'listening') {
        activePrimary = '#00ffee';
        activeSecondary = custom.glowColor || '#0088ff';
      } else if (curActiveState === 'thinking') {
        activePrimary = '#a855f7';
        activeSecondary = '#38bdf8';
      } else if (curActiveState === 'speaking') {
        activePrimary = '#38bdf8';
        activeSecondary = custom.primaryColor || '#00f0ff';
      } else if (curActiveState === 'processing') {
        activePrimary = '#00f0ff';
        activeSecondary = '#a855f7';
      } else if (curActiveState === 'success') {
        activePrimary = '#00f0ff';
        activeSecondary = '#10b981';
      } else if (curActiveState === 'error') {
        activePrimary = '#ef4444';
        activeSecondary = '#f97316';
      }

      targetPrimaryColor.set(activePrimary);
      targetSecondaryColor.set(activeSecondary);
      currentPrimaryColor.lerp(targetPrimaryColor, 0.08);
      currentSecondaryColor.lerp(targetSecondaryColor, 0.08);

      // Update particle color buffer with custom gradient
      const colorAttr = geometry.attributes.aColor as THREE.BufferAttribute;
      const colorArray = colorAttr.array as Float32Array;

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const isCore = i % 4 === 0;
        const ratio = (i % 90) / 90.0;

        let pColor = new THREE.Color();
        if (isCore) {
          pColor.lerpColors(brightWhiteCyan, currentPrimaryColor, 0.45);
        } else if (ratio < 0.5) {
          pColor.lerpColors(currentPrimaryColor, deepBlue, ratio / 0.5);
        } else {
          pColor.lerpColors(deepBlue, currentSecondaryColor, (ratio - 0.5) / 0.5);
        }

        colorArray[i * 3] = pColor.r;
        colorArray[i * 3 + 1] = pColor.g;
        colorArray[i * 3 + 2] = pColor.b;
      }
      colorAttr.needsUpdate = true;

      // Uniform updates
      particleMaterial.uniforms.uTime.value = elapsedTime * effectiveSpeed * styleWaveMult * stateTimeMult;
      particleMaterial.uniforms.uParticleSize.value = THREE.MathUtils.lerp(
        particleMaterial.uniforms.uParticleSize.value,
        config.particleSize,
        0.08
      );
      particleMaterial.uniforms.uGlowIntensity.value = THREE.MathUtils.lerp(
        particleMaterial.uniforms.uGlowIntensity.value,
        config.glowIntensity * 1.12 * (custom.glowIntensity || 1.0) * voiceGlowMod,
        0.08
      );
      particleMaterial.uniforms.uOpacity.value = THREE.MathUtils.lerp(
        particleMaterial.uniforms.uOpacity.value,
        custom.opacity !== undefined ? custom.opacity : 1.0,
        0.08
      );

      // Pulse Scale with user orbSize multiplier & pulseIntensity & state-specific dynamics + voiceReactive
      let stateScale = config.scale * (custom.orbSize || 1.0);

      if (curActiveState === 'speaking') {
        // Continuous voice-driven breathing during speech
        stateScale += baselineBreathing + voicePulseMod * (custom.pulseIntensity || 1.0);
      } else if (curActiveState === 'listening') {
        // Continuous microphone-driven attentive breathing during listening
        stateScale += baselineBreathing + voicePulseMod * (custom.pulseIntensity || 1.0);
      } else if (curActiveState === 'thinking') {
        stateScale += Math.sin(elapsedTime * 14.0) * 0.04;
      } else if (curActiveState === 'processing') {
        stateScale += Math.sin(elapsedTime * 10.0) * 0.035;
      } else if (curActiveState === 'success') {
        stateScale += Math.sin(elapsedTime * 6.0) * 0.06;
      } else {
        // Subtle autonomous breathing during idle
        stateScale += Math.sin(elapsedTime * config.pulseSpeed * effectiveSpeed) * (config.pulseAmplitude * effectivePulseIntensity);
      }

      particleSystem.scale.set(stateScale, stateScale, stateScale);

      // 3D Continuous Rotation + Mouse Influence (Thinking & Processing spin significantly faster)
      const isThinking = curActiveState === 'thinking' || curActiveState === 'processing';
      const rotY = (isThinking ? config.rotationSpeedY * 1.8 : config.rotationSpeedY) * effectiveSpeed;
      const rotX = (isThinking ? config.rotationSpeedX * 1.8 : config.rotationSpeedX) * effectiveSpeed;
      mainGroup.rotation.y += rotY + (mouseX * 0.8 - mainGroup.rotation.y) * 0.05;
      mainGroup.rotation.x += rotX + (mouseY * 0.8 - mainGroup.rotation.x) * 0.05;

      renderer.render(scene, camera);
    };

    renderLoop();

    // --- 6. Resize Handler with ResizeObserver ---
    const updateSize = (w: number, h: number) => {
      if (w > 0 && h > 0) {
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }
    };

    const handleResize = () => {
      if (!container) return;
      updateSize(container.clientWidth, container.clientHeight);
    };

    window.addEventListener('resize', handleResize);

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width || container.clientWidth;
        const h = entry.contentRect.height || container.clientHeight;
        updateSize(w, h);
      }
    });
    resizeObserver.observe(container);

    // --- 7. Cleanup ---
    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      resizeObserver.disconnect();
      container.removeEventListener('mousemove', handleMouseMove);

      geometry.dispose();
      particleMaterial.dispose();
      renderer.dispose();

      if (renderer.domElement && container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div className="bytex-orb-container" onClick={onClick}>
      <div ref={backdropRef} className="bytex-orb-glow-backdrop" />
      <div ref={ringRef} className="bytex-orb-ring" />
      <div ref={containerRef} className="bytex-orb-canvas" />
    </div>
  );
};

export default ByteXOrb;
