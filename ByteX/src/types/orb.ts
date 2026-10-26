export type OrbState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'processing'
  | 'executing'
  | 'success'
  | 'error'
  | 'locked';

export interface OrbStateConfig {
  primaryColor: string;
  secondaryColor: string;
  particleSize: number;
  rotationSpeedX: number;
  rotationSpeedY: number;
  morphSpeed: number;
  pulseSpeed: number;
  pulseAmplitude: number;
  jitter: number;
  glowIntensity: number;
  scale: number;
  label: string;
}

export const ORB_STATE_CONFIGS: Record<OrbState, OrbStateConfig> = {
  idle: {
    primaryColor: '#00f0ff',     // ByteX Electric Cyan
    secondaryColor: '#7000ff',   // Neon Purple
    particleSize: 5.5,           // Balanced particle dot size
    rotationSpeedX: 0.003,
    rotationSpeedY: 0.006,
    morphSpeed: 0.5,
    pulseSpeed: 1.2,
    pulseAmplitude: 0.04,
    jitter: 0.0,
    glowIntensity: 1.0,
    scale: 1.0,
    label: 'Ready when you are.',
  },
  listening: {
    primaryColor: '#00ffee',     // Bright Teal Cyan
    secondaryColor: '#0088ff',   // Deep Blue
    particleSize: 6.5,
    rotationSpeedX: 0.005,
    rotationSpeedY: 0.01,
    morphSpeed: 0.8,
    pulseSpeed: 3.5,
    pulseAmplitude: 0.12,
    jitter: 0.01,
    glowIntensity: 1.3,
    scale: 1.12,
    label: 'Listening...',
  },
  thinking: {
    primaryColor: '#a855f7',     // Energetic Purple
    secondaryColor: '#38bdf8',   // Sky Cyan
    particleSize: 6.0,
    rotationSpeedX: 0.01,
    rotationSpeedY: 0.02,
    morphSpeed: 1.8,
    pulseSpeed: 5.0,
    pulseAmplitude: 0.15,
    jitter: 0.03,
    glowIntensity: 1.4,
    scale: 0.85,
    label: 'Processing command...',
  },
  speaking: {
    primaryColor: '#38bdf8',     // Sky Blue
    secondaryColor: '#00f0ff',   // Electric Cyan
    particleSize: 6.8,
    rotationSpeedX: 0.006,
    rotationSpeedY: 0.012,
    morphSpeed: 1.0,
    pulseSpeed: 6.5,
    pulseAmplitude: 0.22,
    jitter: 0.015,
    glowIntensity: 1.5,
    scale: 1.05,
    label: 'ByteX is speaking...',
  },
  processing: {
    primaryColor: '#00f0ff',     // Cyan Orbit
    secondaryColor: '#a855f7',   // Orbiting Purple
    particleSize: 6.0,
    rotationSpeedX: 0.012,
    rotationSpeedY: 0.022,
    morphSpeed: 1.4,
    pulseSpeed: 4.2,
    pulseAmplitude: 0.1,
    jitter: 0.008,
    glowIntensity: 1.35,
    scale: 0.95,
    label: 'Processing...',
  },
  executing: {
    primaryColor: '#10b981',     // Emerald Matrix Green
    secondaryColor: '#00ffee',   // Cyan Flare
    particleSize: 5.8,
    rotationSpeedX: 0.008,
    rotationSpeedY: 0.016,
    morphSpeed: 1.2,
    pulseSpeed: 2.8,
    pulseAmplitude: 0.08,
    jitter: 0.005,
    glowIntensity: 1.2,
    scale: 1.02,
    label: 'Executing action...',
  },
  success: {
    primaryColor: '#00f0ff',     // Radiant Cyan
    secondaryColor: '#10b981',   // Emerald Green
    particleSize: 6.5,
    rotationSpeedX: 0.005,
    rotationSpeedY: 0.012,
    morphSpeed: 1.0,
    pulseSpeed: 3.5,
    pulseAmplitude: 0.12,
    jitter: 0.005,
    glowIntensity: 1.5,
    scale: 1.08,
    label: 'Action Completed',
  },
  error: {
    primaryColor: '#ef4444',     // Crimson Red
    secondaryColor: '#f97316',   // Flame Orange
    particleSize: 6.2,
    rotationSpeedX: 0.015,
    rotationSpeedY: 0.025,
    morphSpeed: 2.5,
    pulseSpeed: 9.0,
    pulseAmplitude: 0.25,
    jitter: 0.15,
    glowIntensity: 1.6,
    scale: 1.0,
    label: 'System alert / Error',
  },
  locked: {
    primaryColor: '#f59e0b',     // Amber
    secondaryColor: '#b45309',   // Deep Gold
    particleSize: 4.2,
    rotationSpeedX: 0.001,
    rotationSpeedY: 0.002,
    morphSpeed: 0.1,
    pulseSpeed: 0.5,
    pulseAmplitude: 0.01,
    jitter: 0.0,
    glowIntensity: 0.5,
    scale: 0.75,
    label: 'System Locked',
  },
};
