export type STTResultCallback = (transcript: string) => void;
export type STTErrorCallback = (error: string) => void;
export type STTStateCallback = (isListening: boolean) => void;

class STTService {
  private recognition: any = null;
  private isListening: boolean = false;
  private currentLanguage: string = 'en-US';

  private resultCallbacks: Set<STTResultCallback> = new Set();
  private errorCallbacks: Set<STTErrorCallback> = new Set();
  private stateCallbacks: Set<STTStateCallback> = new Set();

  // Audio Amplitude Tracking
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private micStream: MediaStream | null = null;
  private dataArray: Uint8Array | null = null;
  private currentAmplitude: number = 0;

  constructor() {
    this.initRecognition();
  }

  public isSupported(): boolean {
    return 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window;
  }

  public getIsListening(): boolean {
    return this.isListening;
  }

  private isBrave(): boolean {
    return (navigator as any).brave !== undefined || navigator.userAgent.includes('Brave');
  }

  private async startAudioMonitoring() {
    try {
      if (!this.micStream && navigator.mediaDevices?.getUserMedia) {
        this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
        if (AudioContextClass) {
          this.audioContext = new AudioContextClass();
          const source = this.audioContext.createMediaStreamSource(this.micStream);
          this.analyser = this.audioContext.createAnalyser();
          this.analyser.fftSize = 256;
          this.analyser.smoothingTimeConstant = 0.5;
          source.connect(this.analyser);
          this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        }
      }
    } catch (e) {
      // Graceful fallback if permission or audio context is unavailable
    }
  }

  private stopAudioMonitoring() {
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop());
      this.micStream = null;
    }
    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    this.analyser = null;
    this.dataArray = null;
    this.currentAmplitude = 0;
  }

  public getAudioAmplitude(): number {
    if (!this.isListening) {
      this.currentAmplitude *= 0.85;
      return Math.max(0, this.currentAmplitude);
    }
    if (this.analyser && this.dataArray) {
      (this.analyser as any).getByteTimeDomainData(this.dataArray);
      let sum = 0;
      for (let i = 0; i < this.dataArray.length; i++) {
        const val = (this.dataArray[i] - 128) / 128;
        sum += val * val;
      }
      const rawRms = Math.sqrt(sum / this.dataArray.length);
      // Noise gate: ignore background noise below 0.03
      const gated = Math.max(0, rawRms - 0.03) * 3.5;
      const target = Math.min(1.0, gated);
      const alpha = target > this.currentAmplitude ? 0.4 : 0.12;
      this.currentAmplitude += (target - this.currentAmplitude) * alpha;
      return this.currentAmplitude;
    }
    return 0;
  }

  private initRecognition() {
    if (!this.isSupported()) return;

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    this.recognition = new SpeechRecognition();
    this.recognition.continuous = false;
    this.recognition.interimResults = false;
    this.recognition.lang = this.currentLanguage;

    this.recognition.onstart = () => {
      this.isListening = true;
      this.startAudioMonitoring();
      this.notifyState(true);
    };

    this.recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      if (transcript && transcript.trim()) {
        this.notifyResult(transcript.trim());
      }
      this.isListening = false;
      this.stopAudioMonitoring();
      this.notifyState(false);
    };

    this.recognition.onerror = (event: any) => {
      this.isListening = false;
      this.stopAudioMonitoring();
      this.notifyState(false);
      
      const err = event.error;
      // Silently ignore normal user pauses or user cancellations
      if (err === 'no-speech' || err === 'aborted') {
        return;
      }

      let msg = 'Microphone input error.';
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        msg = 'Microphone permission is required. Please grant microphone access in your browser address bar.';
      } else if (err === 'audio-capture') {
        msg = 'No working microphone detected or hardware device is busy.';
      } else if (err === 'network') {
        if (this.isBrave()) {
          msg = "Brave Browser blocks speech recognition by default for privacy. Enable 'Use Google Services for Speech Recognition' in brave://settings/privacy or use Chrome/Edge.";
        } else {
          msg = 'Browser speech recognition service is unreachable (network error). Please check internet connection or VPN settings.';
        }
      }

      this.notifyError(msg);
    };

    this.recognition.onend = () => {
      this.isListening = false;
      this.stopAudioMonitoring();
      this.notifyState(false);
    };
  }

  public setLanguage(lang: string) {
    this.currentLanguage = lang === 'auto' ? 'en-US' : (lang === 'hi-IN-hinglish' ? 'hi-IN' : lang);
    if (this.recognition) {
      this.recognition.lang = this.currentLanguage;
    }
  }

  public onResult(callback: STTResultCallback): () => void {
    this.resultCallbacks.add(callback);
    return () => this.resultCallbacks.delete(callback);
  }

  public onError(callback: STTErrorCallback): () => void {
    this.errorCallbacks.add(callback);
    return () => this.errorCallbacks.delete(callback);
  }

  public onStateChange(callback: STTStateCallback): () => void {
    this.stateCallbacks.add(callback);
    return () => this.stateCallbacks.delete(callback);
  }

  private notifyResult(transcript: string) {
    this.resultCallbacks.forEach((fn) => fn(transcript));
  }

  private notifyError(error: string) {
    this.errorCallbacks.forEach((fn) => fn(error));
  }

  private notifyState(listening: boolean) {
    this.stateCallbacks.forEach((fn) => fn(listening));
  }

  public async start(): Promise<boolean> {
    if (!this.isSupported()) {
      this.notifyError('Speech recognition is not supported in this browser.');
      return false;
    }

    if (this.isListening) {
      this.stop();
    }

    try {
      if (this.recognition) {
        this.recognition.lang = this.currentLanguage;
        this.recognition.start();
        this.startAudioMonitoring();
        return true;
      }
    } catch (e: any) {
      console.warn('[ByteX STT] Start exception:', e);
      if (e.name === 'InvalidStateError' || (e.message && e.message.includes('already started'))) {
        try {
          this.recognition.abort();
          setTimeout(() => {
            try { 
              this.recognition.start(); 
              this.startAudioMonitoring();
            } catch (err) {}
          }, 100);
          return true;
        } catch (err) {}
      }
      this.notifyError('Microphone input busy. Please click again.');
    }
    return false;
  }

  public stop() {
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch (e) {
        console.warn('[ByteX STT] Stop exception:', e);
      }
    }
    this.isListening = false;
    this.stopAudioMonitoring();
    this.notifyState(false);
  }

  public cancel() {
    if (this.recognition) {
      try {
        this.recognition.abort();
      } catch (e) {
        console.warn('[ByteX STT] Cancel exception:', e);
      }
    }
    this.isListening = false;
    this.stopAudioMonitoring();
    this.notifyState(false);
  }
}

export const sttService = new STTService();
export default sttService;
