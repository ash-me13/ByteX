import { SpeechChunker } from '../lib/speechChunker';
import { pickBestVoice } from '../lib/voiceSelection';
import latencyMarks from '../lib/latencyMarks';

export type TTSStateCallback = (isSpeaking: boolean) => void;

export interface SpeakOptions {
  rate?: number;
  volume?: number;
  pitch?: number;
  language?: string;
  voiceURI?: string;
  speakOnlyHighlights?: boolean;
}

class TTSService {
  private isSpeakingState: boolean = false;
  private stateCallbacks: Set<TTSStateCallback> = new Set();

  // Bumped by stop()/new speech; events from older utterances (e.g. fired by speechSynthesis.cancel()) are ignored.
  private sessionId: number = 0;

  // Sentence-level streaming speech
  private chunker: SpeechChunker | null = null;
  private streamOptions: SpeakOptions = {};
  private streamQueue: string[] = [];
  private streamEnded: boolean = false;
  private utteranceActive: boolean = false;

  private voicesReady: Promise<void>;

  constructor() {
    this.voicesReady = this.createVoicesReady();
  }

  public isSupported(): boolean {
    return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  }

  /** Resolves once the browser has loaded its voice list (it is empty on first use in Chrome until voiceschanged). */
  private createVoicesReady(): Promise<void> {
    if (typeof window === 'undefined' || !this.isSupported()) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const synth = window.speechSynthesis;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        synth.removeEventListener?.('voiceschanged', onChange);
        resolve();
      };
      const onChange = () => {
        if (synth.getVoices().length > 0) finish();
      };
      if (synth.getVoices().length > 0) {
        finish();
        return;
      }
      synth.addEventListener?.('voiceschanged', onChange);
      window.setTimeout(finish, 1500); // never block speech longer than this
    });
  }

  public getAvailableVoices(): SpeechSynthesisVoice[] {
    if (!this.isSupported()) return [];
    return window.speechSynthesis.getVoices();
  }

  /**
   * Automatic voice choice: the original ByteX priority order (see lib/voiceSelection.ts).
   */
  public getBestVoice(targetLang: string = 'en-US'): SpeechSynthesisVoice | null {
    return pickBestVoice(this.getAvailableVoices(), targetLang);
  }

  /**
   * Extracts ONLY the concise highlighted bullet points & key summary sentences for speech output.
   */
  public extractHighlightedSummary(text: string): string {
    if (!text || !text.trim()) return '';

    // Strip internal reasoning or protocol tags before speech extraction
    const rawSanitized = text
      .replace(/<think>[\s\S]*?<\/think>/gi, '')
      .replace(/<tool>[\s\S]*?<\/tool>/gi, '')
      .replace(/<\/?think>/gi, '')
      .replace(/<\/?tool>/gi, '')
      .replace(/\{"thought"[\s\S]*?\}/gi, '')
      .trim();

    if (!rawSanitized) return '';

    // Strip raw code blocks and replace with brief speech summary
    const codeBlockReplaced = rawSanitized.replace(/```[a-zA-Z0-9_\+\#]*\s*[\s\S]*?```/gi, "I've generated the code and displayed it on screen.");

    const lines = codeBlockReplaced.split('\n').map((l) => l.trim()).filter(Boolean);

    // 1. Extract top bullet points or numbered highlights if present
    const bulletLines = lines.filter((l) => /^[•*\-\d+\.]\s+/.test(l));
    if (bulletLines.length > 0) {
      const keyHighlights = bulletLines.slice(0, 3).map((l) =>
        l.replace(/^[•*\-\d+\.]\s+/, '').replace(/[*_~`#\[\]()]/g, '').trim()
      );
      const summary = keyHighlights.join('. ');
      return summary.length > 500 ? summary.slice(0, 497) + '...' : summary;
    }

    // 2. Otherwise extract first 2 key sentences
    const clean = codeBlockReplaced
      .replace(/[*_~`#\[\]()]/g, '')
      .replace(/https?:\/\/\S+/g, 'link')
      .trim();

    const sentences = clean.split(/(?<=[.!?])\s+/).filter(Boolean);
    const summary = sentences.slice(0, 2).join(' ');
    return summary.length > 500 ? summary.slice(0, 497) + '...' : summary;
  }

  private speechStartTime: number = 0;
  private currentAmplitude: number = 0;
  private boundaryBurst: number = 0;
  private currentVolumeLevel: number = 1.0;

  public onStateChange(callback: TTSStateCallback): () => void {
    this.stateCallbacks.add(callback);
    return () => this.stateCallbacks.delete(callback);
  }

  private notifyState(speaking: boolean) {
    this.isSpeakingState = speaking;
    if (speaking) {
      this.speechStartTime = performance.now();
      this.boundaryBurst = 0.6;
    } else {
      this.boundaryBurst = 0.0;
    }
    this.stateCallbacks.forEach((fn) => fn(speaking));
  }

  public isSpeaking(): boolean {
    return this.isSpeakingState || (this.isSupported() && window.speechSynthesis.speaking);
  }

  /** True while a streamed answer is being spoken (or waiting for more text to speak). */
  public isStreaming(): boolean {
    return this.chunker !== null;
  }

  /**
   * Returns organic real-time vocal amplitude for the orb's speech breathing.
   * Quiet volume = gentle breathing, loud volume = expansive breathing.
   */
  public getAudioAmplitude(): number {
    if (!this.isSpeaking()) {
      this.currentAmplitude *= 0.85; // smooth release
      return Math.max(0, this.currentAmplitude);
    }

    const now = performance.now();
    const elapsed = (now - this.speechStartTime) / 1000;

    // Organic vocal formant modulation across harmonic frequencies
    const vocalWave =
      Math.sin(elapsed * 12.0) * 0.35 +
      Math.sin(elapsed * 22.0) * 0.22 +
      Math.cos(elapsed * 6.5) * 0.25;

    const cadence = Math.max(0.12, Math.abs(vocalWave));

    if (this.boundaryBurst > 0) {
      this.boundaryBurst *= 0.88;
    }

    const rawTarget = (cadence + this.boundaryBurst * 0.45) * this.currentVolumeLevel;
    const target = Math.min(1.0, Math.max(0.08, rawTarget));

    // Attack / Release envelope smoothing
    const alpha = target > this.currentAmplitude ? 0.35 : 0.08;
    this.currentAmplitude += (target - this.currentAmplitude) * alpha;

    return this.currentAmplitude;
  }

  /** Stops speech immediately and clears any queued sentences / streaming state. */
  public stop() {
    this.sessionId += 1;
    this.chunker = null;
    this.streamQueue = [];
    this.streamEnded = false;
    this.utteranceActive = false;
    if (this.isSupported()) {
      try {
        window.speechSynthesis.cancel();
      } catch (e) {
        console.warn('[ByteX TTS] Cancel error:', e);
      }
    }
    this.notifyState(false);
  }

  private resolveVoice(options: SpeakOptions): { voice: SpeechSynthesisVoice | null; lang: string } {
    const lang = options.language === 'auto' ? 'en-US' : (options.language === 'hi-IN-hinglish' ? 'hi-IN' : (options.language || 'en-US'));
    const voices = this.getAvailableVoices();
    let voice: SpeechSynthesisVoice | null = null;
    if (options.voiceURI) {
      voice = voices.find((v) => v.voiceURI === options.voiceURI) || null;
    }
    if (!voice) {
      voice = this.getBestVoice(lang);
    }
    return { voice, lang };
  }

  private buildUtterance(spokenText: string, options: SpeakOptions): SpeechSynthesisUtterance {
    const utterance = new SpeechSynthesisUtterance(spokenText);
    const vol = options.volume ?? 1.0;
    utterance.rate = options.rate ?? 1.0;
    utterance.volume = vol;
    this.currentVolumeLevel = Math.max(0.4, Math.min(1.6, vol));
    utterance.pitch = options.pitch ?? 1.0;
    const { voice, lang } = this.resolveVoice(options);
    utterance.lang = lang;
    if (voice) {
      utterance.voice = voice;
      console.log(`[ByteX TTS] Speaking with: '${voice.name}'`);
    }
    return utterance;
  }

  public speak(text: string, options: SpeakOptions = {}) {
    if (!this.isSupported() || !text || !text.trim()) {
      return;
    }

    // Stop any ongoing audio immediately before speaking new text
    this.stop();
    const session = this.sessionId;

    // Speak only the highlighted summary if enabled (default True)
    const spokenText = options.speakOnlyHighlights !== false
      ? this.extractHighlightedSummary(text)
      : text.replace(/[*_~`#\[\]()]/g, '').replace(/https?:\/\/\S+/g, 'link').trim();

    if (!spokenText) return;

    // The voice list can be empty on the very first call; wait (bounded) for it so the intended voice is used.
    void this.voicesReady.then(() => {
      if (session !== this.sessionId) return; // stopped or superseded while waiting
      try {
        const utterance = this.buildUtterance(spokenText, options);
        utterance.onstart = () => {
          if (session !== this.sessionId) return;
          latencyMarks.markFirstSpeech();
          this.notifyState(true);
        };
        utterance.onboundary = () => {
          if (session === this.sessionId) this.boundaryBurst = 0.75;
        };
        utterance.onend = () => {
          if (session === this.sessionId) this.notifyState(false);
        };
        utterance.onerror = (e) => {
          console.warn('[ByteX TTS] Synthesis error:', e);
          if (session === this.sessionId) this.notifyState(false);
        };
        window.speechSynthesis.speak(utterance);
      } catch (e) {
        console.warn('[ByteX TTS] Speak exception:', e);
        if (session === this.sessionId) this.notifyState(false);
      }
    });
  }

  // ---- Sentence-level streaming speech ---------------------------------------------------------------------

  /** Start speaking a streamed answer. Any previous speech is stopped and its queue cleared. */
  public beginStream(options: SpeakOptions = {}) {
    if (!this.isSupported()) return;
    this.stop();
    this.streamOptions = options;
    this.chunker = new SpeechChunker({ unlimited: options.speakOnlyHighlights === false });
    this.streamQueue = [];
    this.streamEnded = false;
  }

  /** Feed an ASSISTANT_DELTA text chunk; complete sentences are queued and spoken while generation continues. */
  public pushStream(delta: string) {
    if (!this.chunker) return;
    for (const sentence of this.chunker.push(delta)) {
      this.streamQueue.push(sentence);
    }
    this.pumpStream();
  }

  /**
   * The answer is complete: queue the last partial sentence and let the queue drain.
   * Returns true if streaming speech was active (the caller must then NOT speak the full text again).
   */
  public endStream(): boolean {
    if (!this.chunker) return false;
    for (const sentence of this.chunker.flush()) {
      this.streamQueue.push(sentence);
    }
    this.streamEnded = true;
    this.pumpStream();
    return true;
  }

  private pumpStream() {
    if (!this.chunker || this.utteranceActive) return;
    const next = this.streamQueue.shift();
    if (next === undefined) {
      if (this.streamEnded) {
        // Everything spoken: leave streaming mode.
        this.chunker = null;
        this.streamEnded = false;
        this.notifyState(false);
      }
      return;
    }
    const session = this.sessionId;
    this.utteranceActive = true;
    void this.voicesReady.then(() => {
      if (session !== this.sessionId) return;
      try {
        const utterance = this.buildUtterance(next, this.streamOptions);
        utterance.onstart = () => {
          if (session !== this.sessionId) return;
          latencyMarks.markFirstSpeech();
          if (!this.isSpeakingState) this.notifyState(true);
        };
        utterance.onboundary = () => {
          if (session === this.sessionId) this.boundaryBurst = 0.75;
        };
        const done = () => {
          if (session !== this.sessionId) return;
          this.utteranceActive = false;
          this.pumpStream();
        };
        utterance.onend = done;
        utterance.onerror = (e) => {
          console.warn('[ByteX TTS] Synthesis error:', e);
          done();
        };
        window.speechSynthesis.speak(utterance);
      } catch (e) {
        console.warn('[ByteX TTS] Speak exception:', e);
        if (session === this.sessionId) {
          this.utteranceActive = false;
          this.pumpStream();
        }
      }
    });
  }
}

export const ttsService = new TTSService();
export default ttsService;
