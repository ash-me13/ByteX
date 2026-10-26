export type VoicePersonality = 'friendly' | 'professional' | 'casual' | 'concise' | 'custom';
export type ResponseLength = 'short' | 'balanced' | 'detailed';
export type WakeResponseType = 'yes' | 'listening' | 'ready' | 'help' | 'go_ahead' | 'custom';

export interface VoiceSettings {
  enabled: boolean;
  rate: number;
  volume: number;
  pitch: number;
  language: 'auto' | 'en-US' | 'hi-IN' | 'hi-IN-hinglish';
  voiceURI: string;
  continuous: boolean;
  continuousListeningEnabled: boolean;
  commandTimeoutSeconds: number;
  conversationTimeoutSeconds: number;
  wakeWordEnabled: boolean;
  wakePhrase: string;
  personality: VoicePersonality;
  customPersonality: string;
  responseLength: ResponseLength;
  wakeResponse: WakeResponseType;
  customWakeResponse: string;
}

export const DEFAULT_SETTINGS: VoiceSettings = {
  enabled: true,
  rate: 1.0,
  volume: 1.0,
  pitch: 1.0,
  language: 'auto',
  voiceURI: '',
  continuous: false,
  continuousListeningEnabled: false,
  commandTimeoutSeconds: 7,
  conversationTimeoutSeconds: 15,
  wakeWordEnabled: false,
  wakePhrase: 'Hey ByteX',
  personality: 'friendly',
  customPersonality: '',
  responseLength: 'balanced',
  wakeResponse: 'yes',
  customWakeResponse: 'At your service.',
};

const STORAGE_KEY = 'bytex_voice_settings';

class VoiceSettingsService {
  private settings: VoiceSettings;

  constructor() {
    this.settings = this.load();
  }

  public getSettings(): VoiceSettings {
    return { ...this.settings };
  }

  public save(newSettings: Partial<VoiceSettings>): VoiceSettings {
    // Sanitize custom string inputs
    if (newSettings.customWakeResponse !== undefined) {
      newSettings.customWakeResponse = newSettings.customWakeResponse.slice(0, 100).replace(/[<>{}]/g, '').trim();
    }
    if (newSettings.customPersonality !== undefined) {
      newSettings.customPersonality = newSettings.customPersonality.slice(0, 300).replace(/[<>{}]/g, '').trim();
    }
    if (newSettings.rate !== undefined) {
      newSettings.rate = Math.max(0.5, Math.min(2.5, Number(newSettings.rate) || 1.0));
    }
    if (newSettings.volume !== undefined) {
      newSettings.volume = Math.max(0.0, Math.min(1.0, Number(newSettings.volume) || 1.0));
    }
    if (newSettings.pitch !== undefined) {
      newSettings.pitch = Math.max(0.5, Math.min(2.0, Number(newSettings.pitch) || 1.0));
    }

    this.settings = { ...this.settings, ...newSettings };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.settings));
    } catch (e) {
      console.warn('[ByteX VoiceSettings] Failed to save settings to localStorage:', e);
    }
    return this.getSettings();
  }

  public resetToDefaults(): VoiceSettings {
    this.settings = { ...DEFAULT_SETTINGS };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.settings));
    } catch (e) {
      console.warn('[ByteX VoiceSettings] Failed to reset settings in localStorage:', e);
    }
    return this.getSettings();
  }

  private load(): VoiceSettings {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
      }
    } catch (e) {
      console.warn('[ByteX VoiceSettings] Failed to load settings from localStorage:', e);
    }
    return { ...DEFAULT_SETTINGS };
  }
}

export const voiceSettingsService = new VoiceSettingsService();
export default voiceSettingsService;
