/**
 * ByteX — Orb Customizer 2.0 Service
 * 
 * Single source of truth for all orb customization, appearance, effects,
 * material shaders, shapes, animation styles, state previewing, custom presets,
 * and voice-reactivity.
 */

import type { OrbState } from '../types/orb';

export type OrbPresetName = 'default' | 'neon' | 'cyber' | 'aurora' | 'ocean' | 'minimal' | 'custom' | string;
export type OrbAnimationStyle = 'smooth' | 'energetic' | 'calm';
export type OrbShape = 'sphere' | 'blob' | 'energy_core' | 'ring';
export type OrbMaterial = 'liquid_glass' | 'crystal' | 'holographic' | 'plasma' | 'dark_glass';
export type CoreEffect = 'swirl' | 'galaxy' | 'energy' | 'plasma' | 'minimal';
export type ParticleEffect = 'none' | 'soft' | 'orbit' | 'vortex';
export type AmbientEffect = 'none' | 'soft_glow' | 'aurora' | 'floating_particles';

export interface CustomPresetItem {
  id: string;
  name: string;
  settings: OrbCustomizationSettings;
  createdAt: number;
}

export interface OrbCustomizationSettings {
  preset: OrbPresetName;
  primaryColor: string;
  glowColor: string;
  orbSize: number;           // 0.70 to 1.40 (multiplier)
  glowIntensity: number;     // 0.20 to 2.00 (multiplier)
  opacity: number;           // 0.40 to 1.00 (multiplier)
  animationSpeed: number;    // 0.30 to 2.50 (multiplier)
  pulseIntensity: number;    // 0.00 to 2.50 (multiplier)
  animationStyle: OrbAnimationStyle;
  showRing: boolean;
  shape: OrbShape;
  material: OrbMaterial;
  coreEffect: CoreEffect;
  particleEffect: ParticleEffect;
  ambientEffect: AmbientEffect;
  voiceReactive: boolean;
}

export const DEFAULT_ORB_SETTINGS: OrbCustomizationSettings = {
  preset: 'default',
  primaryColor: '#00f0ff',
  glowColor: '#7000ff',
  orbSize: 1.0,
  glowIntensity: 1.0,
  opacity: 1.0,
  animationSpeed: 1.0,
  pulseIntensity: 1.0,
  animationStyle: 'smooth',
  showRing: true,
  shape: 'sphere',
  material: 'liquid_glass',
  coreEffect: 'swirl',
  particleEffect: 'soft',
  ambientEffect: 'soft_glow',
  voiceReactive: true,
};

export const BUILTIN_PRESETS: Record<string, OrbCustomizationSettings> = {
  default: {
    preset: 'default',
    primaryColor: '#00f0ff',
    glowColor: '#7000ff',
    orbSize: 1.0,
    glowIntensity: 1.0,
    opacity: 1.0,
    animationSpeed: 1.0,
    pulseIntensity: 1.0,
    animationStyle: 'smooth',
    showRing: true,
    shape: 'sphere',
    material: 'liquid_glass',
    coreEffect: 'swirl',
    particleEffect: 'soft',
    ambientEffect: 'soft_glow',
    voiceReactive: true,
  },
  neon: {
    preset: 'neon',
    primaryColor: '#ff007f',
    glowColor: '#00f0ff',
    orbSize: 1.08,
    glowIntensity: 1.45,
    opacity: 1.0,
    animationSpeed: 1.25,
    pulseIntensity: 1.35,
    animationStyle: 'energetic',
    showRing: true,
    shape: 'blob',
    material: 'plasma',
    coreEffect: 'energy',
    particleEffect: 'orbit',
    ambientEffect: 'aurora',
    voiceReactive: true,
  },
  cyber: {
    preset: 'cyber',
    primaryColor: '#00ff66',
    glowColor: '#00f0ff',
    orbSize: 1.0,
    glowIntensity: 1.3,
    opacity: 0.96,
    animationSpeed: 1.35,
    pulseIntensity: 1.15,
    animationStyle: 'energetic',
    showRing: true,
    shape: 'energy_core',
    material: 'holographic',
    coreEffect: 'plasma',
    particleEffect: 'vortex',
    ambientEffect: 'soft_glow',
    voiceReactive: true,
  },
  aurora: {
    preset: 'aurora',
    primaryColor: '#00ffcc',
    glowColor: '#8a2be2',
    orbSize: 1.02,
    glowIntensity: 1.2,
    opacity: 0.94,
    animationSpeed: 0.85,
    pulseIntensity: 1.15,
    animationStyle: 'smooth',
    showRing: true,
    shape: 'sphere',
    material: 'crystal',
    coreEffect: 'galaxy',
    particleEffect: 'soft',
    ambientEffect: 'aurora',
    voiceReactive: true,
  },
  ocean: {
    preset: 'ocean',
    primaryColor: '#0099ff',
    glowColor: '#00ffee',
    orbSize: 0.98,
    glowIntensity: 1.12,
    opacity: 0.92,
    animationSpeed: 0.75,
    pulseIntensity: 0.85,
    animationStyle: 'calm',
    showRing: true,
    shape: 'sphere',
    material: 'liquid_glass',
    coreEffect: 'swirl',
    particleEffect: 'soft',
    ambientEffect: 'soft_glow',
    voiceReactive: true,
  },
  minimal: {
    preset: 'minimal',
    primaryColor: '#e2e8f0',
    glowColor: '#38bdf8',
    orbSize: 0.92,
    glowIntensity: 0.65,
    opacity: 0.85,
    animationSpeed: 0.65,
    pulseIntensity: 0.45,
    animationStyle: 'calm',
    showRing: false,
    shape: 'sphere',
    material: 'dark_glass',
    coreEffect: 'minimal',
    particleEffect: 'none',
    ambientEffect: 'none',
    voiceReactive: false,
  },
};

const STORAGE_KEY = 'bytex_orb_customization';
const CUSTOM_PRESETS_STORAGE_KEY = 'bytex_orb_custom_presets';
const EVENT_NAME = 'bytex_orb_customization_change';

export interface OrbCustomizerEventDetail {
  settings: OrbCustomizationSettings;
  previewState: OrbState | null;
}

class OrbCustomizerService {
  private settings: OrbCustomizationSettings;
  private previewSettings: OrbCustomizationSettings | null = null;
  private previewState: OrbState | null = null;
  private customPresets: CustomPresetItem[] = [];

  constructor() {
    this.settings = this.load();
    this.customPresets = this.loadCustomPresets();
  }

  private load(): OrbCustomizationSettings {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        return {
          ...DEFAULT_ORB_SETTINGS,
          ...parsed,
        };
      }
    } catch (e) {
      console.warn('[ByteX OrbCustomizer] Error reading stored settings:', e);
    }
    return { ...DEFAULT_ORB_SETTINGS };
  }

  private loadCustomPresets(): CustomPresetItem[] {
    try {
      const raw = localStorage.getItem(CUSTOM_PRESETS_STORAGE_KEY);
      if (raw) {
        return JSON.parse(raw);
      }
    } catch (e) {
      console.warn('[ByteX OrbCustomizer] Error reading custom presets:', e);
    }
    return [];
  }

  public getSettings(): OrbCustomizationSettings {
    return this.previewSettings ? { ...this.previewSettings } : { ...this.settings };
  }

  public getSavedSettings(): OrbCustomizationSettings {
    return { ...this.settings };
  }

  public getCustomPresets(): CustomPresetItem[] {
    return [...this.customPresets];
  }

  public getPreviewState(): OrbState | null {
    return this.previewState;
  }

  public setPreviewState(state: OrbState | null) {
    this.previewState = state;
    this.notify(this.getSettings(), this.previewState);
  }

  public save(newSettings: Partial<OrbCustomizationSettings>): OrbCustomizationSettings {
    this.settings = {
      ...this.settings,
      ...newSettings,
    };
    this.previewSettings = null;

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.settings));
    } catch (e) {
      console.warn('[ByteX OrbCustomizer] Error saving settings:', e);
    }

    this.notify(this.settings, this.previewState);
    return { ...this.settings };
  }

  public setPreview(preview: OrbCustomizationSettings | null) {
    this.previewSettings = preview;
    this.notify(preview || this.settings, this.previewState);
  }

  public createCustomPreset(name: string, customSettings?: OrbCustomizationSettings): CustomPresetItem {
    const cleanName = name.trim() || 'My Custom Orb';
    const settingsToSave = customSettings ? { ...customSettings } : { ...this.getSettings() };
    const id = `custom_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;

    const newItem: CustomPresetItem = {
      id,
      name: cleanName,
      settings: {
        ...settingsToSave,
        preset: id,
      },
      createdAt: Date.now(),
    };

    this.customPresets.push(newItem);
    try {
      localStorage.setItem(CUSTOM_PRESETS_STORAGE_KEY, JSON.stringify(this.customPresets));
    } catch (e) {
      console.warn('[ByteX OrbCustomizer] Error saving custom presets:', e);
    }

    this.save(newItem.settings);
    return newItem;
  }

  public deleteCustomPreset(id: string): boolean {
    const initialLen = this.customPresets.length;
    this.customPresets = this.customPresets.filter((p) => p.id !== id);
    if (this.customPresets.length !== initialLen) {
      try {
        localStorage.setItem(CUSTOM_PRESETS_STORAGE_KEY, JSON.stringify(this.customPresets));
      } catch (e) {
        console.warn('[ByteX OrbCustomizer] Error updating custom presets:', e);
      }
      return true;
    }
    return false;
  }

  public resetToDefaults(): OrbCustomizationSettings {
    this.settings = { ...DEFAULT_ORB_SETTINGS };
    this.previewSettings = null;
    this.previewState = null;
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      console.warn('[ByteX OrbCustomizer] Error resetting settings:', e);
    }
    this.notify(this.settings, null);
    return { ...this.settings };
  }

  public getPreset(name: string): OrbCustomizationSettings {
    if (BUILTIN_PRESETS[name]) {
      return { ...BUILTIN_PRESETS[name] };
    }
    const custom = this.customPresets.find((p) => p.id === name);
    if (custom) {
      return { ...custom.settings };
    }
    return { ...DEFAULT_ORB_SETTINGS };
  }

  private notify(settings: OrbCustomizationSettings, previewState: OrbState | null) {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent<OrbCustomizerEventDetail>(EVENT_NAME, {
          detail: { settings, previewState }
        })
      );
    }
  }

  public subscribe(callback: (settings: OrbCustomizationSettings, previewState: OrbState | null) => void): () => void {
    const handler = (e: Event) => {
      const customEvent = e as CustomEvent<OrbCustomizerEventDetail>;
      if (customEvent.detail && customEvent.detail.settings) {
        callback(customEvent.detail.settings, customEvent.detail.previewState !== undefined ? customEvent.detail.previewState : null);
      }
    };

    if (typeof window !== 'undefined') {
      window.addEventListener(EVENT_NAME, handler);
    }

    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener(EVENT_NAME, handler);
      }
    };
  }
}

export const orbCustomizerService = new OrbCustomizerService();
export default orbCustomizerService;
