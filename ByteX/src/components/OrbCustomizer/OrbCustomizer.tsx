import React, { useState, useEffect } from 'react';
import {
  X,
  RotateCcw,
  Check,
  Sparkles,
  Sliders,
  Palette,
  Activity,
  Eye,
  Volume2,
  Mic,
  BrainCircuit,
  CircleDot,
  Wand2,
  Trash2,
  Plus,
  Radio,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import {
  orbCustomizerService,
  BUILTIN_PRESETS,
  type OrbCustomizationSettings,
  type OrbShape,
  type OrbMaterial,
  type CoreEffect,
  type ParticleEffect,
  type AmbientEffect,
  type OrbAnimationStyle,
  type CustomPresetItem,
} from '../../services/orbCustomizerService';
import type { OrbState } from '../../types/orb';
import './OrbCustomizer.css';

interface OrbCustomizerProps {
  isOpen: boolean;
  onClose: () => void;
  onPreviewStateChange?: (state: OrbState) => void;
}

type TabKey = 'appearance' | 'effects' | 'animation' | 'states' | 'presets';

const SHAPE_OPTIONS: { id: OrbShape; name: string }[] = [
  { id: 'sphere', name: 'Sphere' },
  { id: 'blob', name: 'Liquid Blob' },
  { id: 'energy_core', name: 'Energy Core' },
  { id: 'ring', name: 'Orb + Ring' },
];

const MATERIAL_OPTIONS: { id: OrbMaterial; name: string }[] = [
  { id: 'liquid_glass', name: 'Liquid Glass' },
  { id: 'crystal', name: 'Crystal' },
  { id: 'holographic', name: 'Holographic' },
  { id: 'plasma', name: 'Plasma' },
  { id: 'dark_glass', name: 'Dark Glass' },
];

const CORE_EFFECT_OPTIONS: { id: CoreEffect; name: string }[] = [
  { id: 'swirl', name: 'Fluid Swirl' },
  { id: 'galaxy', name: 'Galaxy' },
  { id: 'energy', name: 'Energy' },
  { id: 'plasma', name: 'Plasma' },
  { id: 'minimal', name: 'Minimal' },
];

const PARTICLE_EFFECT_OPTIONS: { id: ParticleEffect; name: string }[] = [
  { id: 'none', name: 'None' },
  { id: 'soft', name: 'Soft' },
  { id: 'orbit', name: 'Orbit' },
  { id: 'vortex', name: 'Vortex' },
];

const AMBIENT_EFFECT_OPTIONS: { id: AmbientEffect; name: string }[] = [
  { id: 'none', name: 'None' },
  { id: 'soft_glow', name: 'Soft Glow' },
  { id: 'aurora', name: 'Aurora' },
  { id: 'floating_particles', name: 'Floating Particles' },
];

const BUILTIN_PRESET_CARDS: { id: string; name: string; primary: string; secondary: string }[] = [
  { id: 'default', name: 'Default', primary: '#00f0ff', secondary: '#7000ff' },
  { id: 'neon', name: 'Neon', primary: '#ff007f', secondary: '#00f0ff' },
  { id: 'cyber', name: 'Cyber', primary: '#00ff66', secondary: '#00f0ff' },
  { id: 'aurora', name: 'Aurora', primary: '#00ffcc', secondary: '#8a2be2' },
  { id: 'ocean', name: 'Ocean', primary: '#0099ff', secondary: '#00ffee' },
  { id: 'minimal', name: 'Minimal', primary: '#e2e8f0', secondary: '#38bdf8' },
];

export const OrbCustomizer: React.FC<OrbCustomizerProps> = ({
  isOpen,
  onClose,
  onPreviewStateChange,
}) => {
  const [settings, setSettings] = useState<OrbCustomizationSettings>(() => orbCustomizerService.getSavedSettings());
  const [customPresets, setCustomPresets] = useState<CustomPresetItem[]>(() => orbCustomizerService.getCustomPresets());
  const [newPresetName, setNewPresetName] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('appearance');
  const [previewState, setPreviewState] = useState<OrbState>('idle');
  const [isSaved, setIsSaved] = useState(false);

  useEffect(() => {
    if (isOpen) {
      const current = orbCustomizerService.getSavedSettings();
      setSettings(current);
      setCustomPresets(orbCustomizerService.getCustomPresets());
      orbCustomizerService.setPreview(current);
      setPreviewState('idle');
      orbCustomizerService.setPreviewState('idle');
      onPreviewStateChange?.('idle');
    } else {
      orbCustomizerService.setPreview(null);
      orbCustomizerService.setPreviewState(null);
      onPreviewStateChange?.('idle');
    }
  }, [isOpen]);

  const updateSetting = <K extends keyof OrbCustomizationSettings>(key: K, value: OrbCustomizationSettings[K]) => {
    const updated = {
      ...settings,
      [key]: value,
      preset: key === 'preset' ? (value as string) : 'custom',
    };
    setSettings(updated);
    orbCustomizerService.setPreview(updated);
    setIsSaved(false);
  };

  const handleSelectBuiltinPreset = (presetId: string) => {
    const presetConfig = BUILTIN_PRESETS[presetId];
    if (presetConfig) {
      setSettings(presetConfig);
      orbCustomizerService.setPreview(presetConfig);
      setIsSaved(false);
    }
  };

  const handleSelectCustomPreset = (preset: CustomPresetItem) => {
    setSettings(preset.settings);
    orbCustomizerService.setPreview(preset.settings);
    setIsSaved(false);
  };

  const handleCreatePreset = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPresetName.trim()) return;
    const created = orbCustomizerService.createCustomPreset(newPresetName.trim(), settings);
    setCustomPresets(orbCustomizerService.getCustomPresets());
    setSettings(created.settings);
    setNewPresetName('');
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const handleDeleteCustomPreset = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    orbCustomizerService.deleteCustomPreset(id);
    setCustomPresets(orbCustomizerService.getCustomPresets());
  };

  const handleSave = () => {
    orbCustomizerService.save(settings);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const handleReset = () => {
    const def = orbCustomizerService.resetToDefaults();
    setSettings(def);
    setPreviewState('idle');
    orbCustomizerService.setPreviewState('idle');
    onPreviewStateChange?.('idle');
    setIsSaved(false);
  };

  const handleStatePreview = (st: OrbState) => {
    setPreviewState(st);
    orbCustomizerService.setPreviewState(st);
    onPreviewStateChange?.(st);
  };

  if (!isOpen) return null;

  return (
    <div className="bytex-orb-customizer-overlay" onClick={onClose}>
      <div className="bytex-orb-customizer-panel" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="bytex-customizer-header">
          <div className="bytex-customizer-title-wrap">
            <Sparkles size={16} className="bytex-customizer-icon" />
            <h3 className="bytex-customizer-title">Orb Customizer 2.0</h3>
          </div>
          <button className="bytex-customizer-close-btn" onClick={onClose} title="Close Panel">
            <X size={15} />
          </button>
        </div>

        {/* Quick State Preview Bar */}
        <div className="bytex-state-preview-top-bar">
          <div className="bytex-preview-label-group">
            <Eye size={12} />
            <span>State Preview:</span>
          </div>
          <div className="bytex-state-chips">
            <button
              className={`bytex-state-chip ${previewState === 'idle' ? 'active' : ''}`}
              onClick={() => handleStatePreview('idle')}
              title="Idle state"
            >
              <CircleDot size={11} />
              <span>Idle</span>
            </button>
            <button
              className={`bytex-state-chip state-listening ${previewState === 'listening' ? 'active' : ''}`}
              onClick={() => handleStatePreview('listening')}
              title="Listening state"
            >
              <Mic size={11} />
              <span>Listening</span>
            </button>
            <button
              className={`bytex-state-chip state-thinking ${previewState === 'thinking' ? 'active' : ''}`}
              onClick={() => handleStatePreview('thinking')}
              title="Thinking state"
            >
              <BrainCircuit size={11} />
              <span>Thinking</span>
            </button>
            <button
              className={`bytex-state-chip state-speaking ${previewState === 'speaking' ? 'active' : ''}`}
              onClick={() => handleStatePreview('speaking')}
              title="Speaking state"
            >
              <Volume2 size={11} />
              <span>Speaking</span>
            </button>
            <button
              className={`bytex-state-chip state-processing ${previewState === 'processing' ? 'active' : ''}`}
              onClick={() => handleStatePreview('processing')}
              title="Processing state"
            >
              <Radio size={11} />
              <span>Process</span>
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="bytex-customizer-tabs">
          <button
            className={`bytex-customizer-tab ${activeTab === 'appearance' ? 'active' : ''}`}
            onClick={() => setActiveTab('appearance')}
          >
            <Palette size={12} />
            Appearance
          </button>
          <button
            className={`bytex-customizer-tab ${activeTab === 'effects' ? 'active' : ''}`}
            onClick={() => setActiveTab('effects')}
          >
            <Wand2 size={12} />
            Effects
          </button>
          <button
            className={`bytex-customizer-tab ${activeTab === 'animation' ? 'active' : ''}`}
            onClick={() => setActiveTab('animation')}
          >
            <Activity size={12} />
            Animation
          </button>
          <button
            className={`bytex-customizer-tab ${activeTab === 'states' ? 'active' : ''}`}
            onClick={() => setActiveTab('states')}
          >
            <Eye size={12} />
            States
          </button>
          <button
            className={`bytex-customizer-tab ${activeTab === 'presets' ? 'active' : ''}`}
            onClick={() => setActiveTab('presets')}
          >
            <Sliders size={12} />
            Presets
          </button>
        </div>

        {/* Tab Content */}
        <div className="bytex-customizer-body">
          {/* TAB 1: APPEARANCE */}
          {activeTab === 'appearance' && (
            <div className="bytex-customizer-section">
              {/* Shape Selector */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Orb Shape</span>
                  <span className="bytex-customizer-desc">Spherical particle geometric topology</span>
                </div>
                <div className="bytex-customizer-chip-grid">
                  {SHAPE_OPTIONS.map((shp) => (
                    <button
                      key={shp.id}
                      className={`bytex-choice-chip ${settings.shape === shp.id ? 'active' : ''}`}
                      onClick={() => updateSetting('shape', shp.id)}
                    >
                      {shp.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Material Selector */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Orb Material</span>
                  <span className="bytex-customizer-desc">Optical shader bloom & dispersion</span>
                </div>
                <div className="bytex-customizer-chip-grid">
                  {MATERIAL_OPTIONS.map((mat) => (
                    <button
                      key={mat.id}
                      className={`bytex-choice-chip ${settings.material === mat.id ? 'active' : ''}`}
                      onClick={() => updateSetting('material', mat.id)}
                    >
                      {mat.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Primary Color */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Primary Color</span>
                  <span className="bytex-customizer-desc">Core particle emission tone</span>
                </div>
                <div className="bytex-customizer-color-control">
                  <input
                    type="color"
                    value={settings.primaryColor}
                    onChange={(e) => updateSetting('primaryColor', e.target.value)}
                    className="bytex-color-picker"
                  />
                  <input
                    type="text"
                    value={settings.primaryColor}
                    onChange={(e) => updateSetting('primaryColor', e.target.value)}
                    className="bytex-color-input"
                    maxLength={7}
                  />
                </div>
              </div>

              {/* Glow Color */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Glow Color</span>
                  <span className="bytex-customizer-desc">Atmospheric outer halo hue</span>
                </div>
                <div className="bytex-customizer-color-control">
                  <input
                    type="color"
                    value={settings.glowColor}
                    onChange={(e) => updateSetting('glowColor', e.target.value)}
                    className="bytex-color-picker"
                  />
                  <input
                    type="text"
                    value={settings.glowColor}
                    onChange={(e) => updateSetting('glowColor', e.target.value)}
                    className="bytex-color-input"
                    maxLength={7}
                  />
                </div>
              </div>

              {/* Orb Scale */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <div className="bytex-customizer-label-with-val">
                    <span className="bytex-customizer-label">Orb Scale</span>
                    <span className="bytex-customizer-val">{Math.round(settings.orbSize * 100)}%</span>
                  </div>
                </div>
                <input
                  type="range"
                  min="0.70"
                  max="1.35"
                  step="0.05"
                  value={settings.orbSize}
                  onChange={(e) => updateSetting('orbSize', parseFloat(e.target.value))}
                  className="bytex-customizer-slider"
                />
              </div>

              {/* Glow Intensity */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <div className="bytex-customizer-label-with-val">
                    <span className="bytex-customizer-label">Glow & Bloom Intensity</span>
                    <span className="bytex-customizer-val">{Math.round(settings.glowIntensity * 100)}%</span>
                  </div>
                </div>
                <input
                  type="range"
                  min="0.20"
                  max="2.00"
                  step="0.10"
                  value={settings.glowIntensity}
                  onChange={(e) => updateSetting('glowIntensity', parseFloat(e.target.value))}
                  className="bytex-customizer-slider"
                />
              </div>

              {/* Opacity */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <div className="bytex-customizer-label-with-val">
                    <span className="bytex-customizer-label">Particle Opacity</span>
                    <span className="bytex-customizer-val">{Math.round(settings.opacity * 100)}%</span>
                  </div>
                </div>
                <input
                  type="range"
                  min="0.40"
                  max="1.00"
                  step="0.05"
                  value={settings.opacity}
                  onChange={(e) => updateSetting('opacity', parseFloat(e.target.value))}
                  className="bytex-customizer-slider"
                />
              </div>
            </div>
          )}

          {/* TAB 2: EFFECTS */}
          {activeTab === 'effects' && (
            <div className="bytex-customizer-section">
              {/* Core Effect */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Core Effect</span>
                  <span className="bytex-customizer-desc">Internal vortex & energy discharge</span>
                </div>
                <div className="bytex-customizer-chip-grid">
                  {CORE_EFFECT_OPTIONS.map((c) => (
                    <button
                      key={c.id}
                      className={`bytex-choice-chip ${settings.coreEffect === c.id ? 'active' : ''}`}
                      onClick={() => updateSetting('coreEffect', c.id)}
                    >
                      {c.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Particle Effect */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Particle Dynamics</span>
                  <span className="bytex-customizer-desc">Outer trajectory distribution</span>
                </div>
                <div className="bytex-customizer-chip-grid">
                  {PARTICLE_EFFECT_OPTIONS.map((p) => (
                    <button
                      key={p.id}
                      className={`bytex-choice-chip ${settings.particleEffect === p.id ? 'active' : ''}`}
                      onClick={() => updateSetting('particleEffect', p.id)}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Ambient Effect */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Ambient Atmosphere</span>
                  <span className="bytex-customizer-desc">Outer atmospheric backdrop aura</span>
                </div>
                <div className="bytex-customizer-chip-grid">
                  {AMBIENT_EFFECT_OPTIONS.map((a) => (
                    <button
                      key={a.id}
                      className={`bytex-choice-chip ${settings.ambientEffect === a.id ? 'active' : ''}`}
                      onClick={() => updateSetting('ambientEffect', a.id)}
                    >
                      {a.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: ANIMATION */}
          {activeTab === 'animation' && (
            <div className="bytex-customizer-section">
              {/* Animation Speed */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <div className="bytex-customizer-label-with-val">
                    <span className="bytex-customizer-label">Rotation & Flow Speed</span>
                    <span className="bytex-customizer-val">{settings.animationSpeed.toFixed(2)}x</span>
                  </div>
                  <span className="bytex-customizer-desc">Orbit rotation and particle wave speed</span>
                </div>
                <input
                  type="range"
                  min="0.30"
                  max="2.20"
                  step="0.10"
                  value={settings.animationSpeed}
                  onChange={(e) => updateSetting('animationSpeed', parseFloat(e.target.value))}
                  className="bytex-customizer-slider"
                />
              </div>

              {/* Pulse Intensity */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <div className="bytex-customizer-label-with-val">
                    <span className="bytex-customizer-label">Pulse & Breathing Amplitude</span>
                    <span className="bytex-customizer-val">{Math.round(settings.pulseIntensity * 100)}%</span>
                  </div>
                  <span className="bytex-customizer-desc">Dynamic expansion and contraction range</span>
                </div>
                <input
                  type="range"
                  min="0.00"
                  max="2.20"
                  step="0.10"
                  value={settings.pulseIntensity}
                  onChange={(e) => updateSetting('pulseIntensity', parseFloat(e.target.value))}
                  className="bytex-customizer-slider"
                />
              </div>

              {/* Animation Style */}
              <div className="bytex-customizer-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Animation Style</span>
                  <span className="bytex-customizer-desc">Harmonic wave distribution</span>
                </div>
                <div className="bytex-style-selector">
                  {(['smooth', 'energetic', 'calm'] as OrbAnimationStyle[]).map((st) => (
                    <button
                      key={st}
                      className={`bytex-style-btn ${settings.animationStyle === st ? 'active' : ''}`}
                      onClick={() => updateSetting('animationStyle', st)}
                    >
                      {st.charAt(0).toUpperCase() + st.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Voice Reactive Toggle */}
              <div className="bytex-customizer-row bytex-toggle-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Voice-Reactive Dynamics</span>
                  <span className="bytex-customizer-desc">Modulate scale & glow to speech amplitude</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={settings.voiceReactive}
                    onChange={(e) => updateSetting('voiceReactive', e.target.checked)}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              {/* Ambient Ring Toggle */}
              <div className="bytex-customizer-row bytex-toggle-row">
                <div className="bytex-customizer-label-group">
                  <span className="bytex-customizer-label">Ambient Equatorial Ring</span>
                  <span className="bytex-customizer-desc">Subtle perimeter orbit</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={settings.showRing}
                    onChange={(e) => updateSetting('showRing', e.target.checked)}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>
            </div>
          )}

          {/* TAB 4: STATES PREVIEW */}
          {activeTab === 'states' && (
            <div className="bytex-customizer-section">
              <div className="bytex-states-grid">
                <button
                  className={`bytex-state-card ${previewState === 'idle' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('idle')}
                >
                  <CircleDot size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">IDLE</span>
                    <span className="bytex-state-desc">Steady breathing pulse</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-listening ${previewState === 'listening' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('listening')}
                >
                  <Mic size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">LISTENING</span>
                    <span className="bytex-state-desc">Receptive radial expansion</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-thinking ${previewState === 'thinking' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('thinking')}
                >
                  <BrainCircuit size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">THINKING</span>
                    <span className="bytex-state-desc">Fast spin & contracted core</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-speaking ${previewState === 'speaking' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('speaking')}
                >
                  <Volume2 size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">SPEAKING</span>
                    <span className="bytex-state-desc">Rhythmic acoustic flutter</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-processing ${previewState === 'processing' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('processing')}
                >
                  <Radio size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">PROCESSING</span>
                    <span className="bytex-state-desc">Orbiting energy cadence</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-success ${previewState === 'success' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('success')}
                >
                  <CheckCircle2 size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">SUCCESS</span>
                    <span className="bytex-state-desc">Radiant confirmation ripple</span>
                  </div>
                </button>
                <button
                  className={`bytex-state-card state-error ${previewState === 'error' ? 'active' : ''}`}
                  onClick={() => handleStatePreview('error')}
                >
                  <AlertTriangle size={16} className="state-icon" />
                  <div className="bytex-state-info">
                    <span className="bytex-state-name">ERROR</span>
                    <span className="bytex-state-desc">Warning flutter alert</span>
                  </div>
                </button>
              </div>
            </div>
          )}

          {/* TAB 5: PRESETS & CREATOR */}
          {activeTab === 'presets' && (
            <div className="bytex-customizer-section">
              {/* Create Preset Form */}
              <form className="bytex-preset-create-form" onSubmit={handleCreatePreset}>
                <input
                  type="text"
                  placeholder="New preset name (e.g. My Cyber Orb)..."
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                  className="bytex-preset-input"
                />
                <button type="submit" className="bytex-preset-create-btn" disabled={!newPresetName.trim()}>
                  <Plus size={13} />
                  <span>Create</span>
                </button>
              </form>

              {/* Custom Presets */}
              {customPresets.length > 0 && (
                <div className="bytex-custom-presets-wrap">
                  <span className="bytex-preset-group-title">Your Custom Presets</span>
                  <div className="bytex-presets-grid">
                    {customPresets.map((p) => {
                      const isSelected = settings.preset === p.id;
                      return (
                        <div
                          key={p.id}
                          className={`bytex-preset-card ${isSelected ? 'active' : ''}`}
                          onClick={() => handleSelectCustomPreset(p)}
                        >
                          <div className="bytex-preset-swatch">
                            <span
                              className="bytex-swatch-dot"
                              style={{ background: p.settings.primaryColor, boxShadow: `0 0 8px ${p.settings.primaryColor}` }}
                            />
                            <span
                              className="bytex-swatch-dot"
                              style={{ background: p.settings.glowColor, boxShadow: `0 0 8px ${p.settings.glowColor}` }}
                            />
                          </div>
                          <span className="bytex-preset-name">{p.name}</span>
                          <button
                            type="button"
                            className="bytex-preset-delete-btn"
                            onClick={(e) => handleDeleteCustomPreset(e, p.id)}
                            title="Delete preset"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Built-in Presets */}
              <div className="bytex-builtin-presets-wrap">
                <span className="bytex-preset-group-title">Built-in Presets</span>
                <div className="bytex-presets-grid">
                  {BUILTIN_PRESET_CARDS.map((p) => {
                    const isSelected = settings.preset === p.id;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        className={`bytex-preset-card ${isSelected ? 'active' : ''}`}
                        onClick={() => handleSelectBuiltinPreset(p.id)}
                      >
                        <div className="bytex-preset-swatch">
                          <span
                            className="bytex-swatch-dot"
                            style={{ background: p.primary, boxShadow: `0 0 8px ${p.primary}` }}
                          />
                          <span
                            className="bytex-swatch-dot"
                            style={{ background: p.secondary, boxShadow: `0 0 8px ${p.secondary}` }}
                          />
                        </div>
                        <span className="bytex-preset-name">{p.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="bytex-customizer-footer">
          <button className="bytex-btn-reset" onClick={handleReset} title="Reset to ByteX Default">
            <RotateCcw size={13} />
            <span>Reset Default</span>
          </button>
          <button className={`bytex-btn-save ${isSaved ? 'saved' : ''}`} onClick={handleSave}>
            <Check size={14} />
            <span>{isSaved ? 'Saved!' : 'Save Changes'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default OrbCustomizer;
