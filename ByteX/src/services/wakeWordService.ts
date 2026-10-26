import { debugLog } from '../lib/debug';
export type WakeWordState =
  | 'DISABLED'
  | 'IDLE'
  | 'LISTENING_FOR_WAKE_WORD'
  | 'WAKE_DETECTED'
  | 'LISTENING_FOR_COMMAND'
  | 'PROCESSING'
  | 'SPEAKING'
  | 'CONTINUOUS_LISTENING'
  | 'ERROR';

export type WakeWordStateCallback = (state: WakeWordState) => void;
export type WakeWordEventCallback = (commandText: string) => void;
export type WakeWordErrorCallback = (error: string) => void;

const INSTANCE_ID = `WAKE_SRV_${Math.random().toString(36).substring(2, 7).toUpperCase()}`;

export function normalizeWakeTranscript(text: string): string {
  if (!text) return '';
  let clean = text.toLowerCase();
  clean = clean.replace(/['’]/g, '');
  clean = clean.replace(/[^a-z0-9\s]/g, ' ');
  clean = clean.replace(/\s+/g, ' ').trim();
  return clean;
}

const BYTEX_ALIASES = [
  'byte\\s*axe',
  'bite\\s*axe',
  'byte\\s*ex',
  'bite\\s*ex',
  'byte\\s*x',
  'bite\\s*x',
  'bit\\s*x',
  'b\\s*t\\s*x',
  'bytex',
  'bitex',
  'byteks',
  'bytes',
  'bites',
  'byte',
  'bite',
  'btx'
];

const PREFIX_PHRASES = [
  'hey\\s+there',
  'hi\\s+there',
  'hello\\s+there',
  'whats\\s+up',
  'whats\\s+happening',
  'how\\s+are\\s+you',
  'hello',
  'hey',
  'hi',
  'yo',
  'a'
];

const STANDALONE_ALIASES = [
  'bytex',
  'byte\\s*x',
  'bitex',
  'a\\s+bytex',
  'a\\s+byte\\s*x'
];

const aliasPattern = BYTEX_ALIASES.join('|');
const prefixPattern = PREFIX_PHRASES.join('|');
const standalonePattern = STANDALONE_ALIASES.join('|');

const WAKE_REGEX = new RegExp(
  `^(?:(?:(?:${prefixPattern})\\s+)(?:${aliasPattern})|(?:${standalonePattern}))\\b\\s*(.*)$`,
  'i'
);

export function matchWakeWord(transcript: string): { isMatch: boolean; commandText: string; matchedAlias: string } {
  if (!transcript || !transcript.trim()) {
    return { isMatch: false, commandText: '', matchedAlias: '' };
  }

  const raw = transcript.trim();
  const norm = normalizeWakeTranscript(raw);

  const match = norm.match(WAKE_REGEX);
  if (match) {
    const remNorm = match[1] ? match[1].trim() : '';
    let remaining = '';

    if (remNorm) {
      const rawWords = raw.split(/\s+/);
      const normWords = norm.split(/\s+/);
      const remWordsCount = remNorm.split(/\s+/).length;
      const consumedCount = normWords.length - remWordsCount;
      if (consumedCount >= 0 && consumedCount < rawWords.length) {
        remaining = rawWords.slice(consumedCount).join(' ').trim();
      } else {
        remaining = remNorm;
      }
    }

    remaining = remaining.replace(/^[.!?,\s:]+/, '').replace(/[.!?,\s:]+$/, '').trim();
    const matchedAlias = norm.slice(0, norm.length - remNorm.length).trim();

    return {
      isMatch: true,
      commandText: remaining,
      matchedAlias,
    };
  }

  return { isMatch: false, commandText: '', matchedAlias: '' };
}

export function isStopPhrase(text: string): boolean {
  if (!text || !text.trim()) return false;
  const norm = normalizeWakeTranscript(text);
  const stopPhrases = [
    'stop',
    'stop listening',
    'never mind',
    'nevermind',
    'cancel',
    'thats all',
    'that is all',
    'goodbye',
    'bye bytex',
    'bye byte',
    'exit'
  ];
  return stopPhrases.includes(norm);
}

class WakeWordService {
  public readonly instanceId: string = INSTANCE_ID;
  private state: WakeWordState = 'DISABLED';
  private keyword: string = 'Hey ByteX';
  private recognition: any = null;
  private isPaused: boolean = false;
  private isEnabled: boolean = false;
  private continuousListeningEnabled: boolean = false;
  private commandTimeoutMs: number = 7000;
  private conversationTimeoutMs: number = 15000;

  private wakeResultIndex: number = -1;
  private lastError: string = '';

  private lastTranscript: string = '';
  private lastNormalizedTranscript: string = '';
  private lastMatchedAlias: string = '';
  private lastIsFinal: boolean = false;
  private lastResultIndex: number = -1;
  private lastEventTime: string = 'N/A';
  private permissionState: string = 'UNKNOWN';

  private recognitionRunning: boolean = false;
  private startingRecognition: boolean = false;
  private restartTimer: any = null;

  private retryCount: number = 0;
  private maxRetries: number = 5;
  private commandTimeoutTimer: any = null;
  private continuousTimeoutTimer: any = null;

  private stateCallbacks: Set<WakeWordStateCallback> = new Set();
  private wakeWordCallbacks: Set<WakeWordEventCallback> = new Set();
  private commandCallbacks: Set<WakeWordEventCallback> = new Set();
  private errorCallbacks: Set<WakeWordErrorCallback> = new Set();

  constructor() {
    debugLog(`[WakeDebug] WakeWordService instance = ${this.instanceId} initializing`);
    this.initRecognition();
  }

  public isSupported(): boolean {
    const supported =
      typeof window !== 'undefined' &&
      ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
    debugLog(`[WakeDebug] isSupported = ${supported} (SpeechRecognition: ${typeof (window as any).SpeechRecognition}, webkitSpeechRecognition: ${typeof (window as any).webkitSpeechRecognition})`);
    return supported;
  }

  public setContinuousListening(enabled: boolean) {
    debugLog(`[WakeDebug] setContinuousListening = ${enabled} on instance ${this.instanceId}`);
    this.continuousListeningEnabled = enabled;
  }

  public getContinuousListening(): boolean {
    return this.continuousListeningEnabled;
  }

  public setTimeouts(commandSec: number = 7, conversationSec: number = 15) {
    this.commandTimeoutMs = commandSec * 1000;
    this.conversationTimeoutMs = conversationSec * 1000;
  }

  public getKeyword(): string {
    return this.keyword;
  }

  public getState(): WakeWordState {
    return this.state;
  }

  public getLastError(): string {
    return this.lastError;
  }

  public getDiagnosticData() {
    return {
      instanceId: this.instanceId,
      speechRecognitionSupported: typeof (window as any).SpeechRecognition !== 'undefined',
      webkitSpeechRecognitionSupported: typeof (window as any).webkitSpeechRecognition !== 'undefined',
      enabled: this.isEnabled,
      continuousListeningEnabled: this.continuousListeningEnabled,
      state: this.state,
      recognitionInstanceExists: !!this.recognition,
      recognitionRunning: this.recognitionRunning || this.startingRecognition,
      permissionState: this.permissionState,
      lastTranscript: this.lastTranscript,
      lastNormalizedTranscript: this.lastNormalizedTranscript,
      lastMatchedAlias: this.lastMatchedAlias,
      lastIsFinal: this.lastIsFinal,
      lastResultIndex: this.lastResultIndex,
      lastEventTime: this.lastEventTime,
      lastError: this.lastError,
    };
  }

  public isListening(): boolean {
    return (
      this.state === 'LISTENING_FOR_WAKE_WORD' ||
      this.state === 'WAKE_DETECTED' ||
      this.state === 'LISTENING_FOR_COMMAND' ||
      this.state === 'CONTINUOUS_LISTENING'
    );
  }

  public isRunning(): boolean {
    return this.recognitionRunning || this.startingRecognition;
  }

  private setState(newState: WakeWordState) {
    if (this.state !== newState) {
      debugLog(`[WakeDebug] state transition: ${this.state} -> ${newState} (instance: ${this.instanceId})`);
      this.state = newState;
      this.notifyState();
    }
  }

  private initRecognition() {
    if (!this.isSupported()) {
      console.warn(`[WakeDebug] SpeechRecognition API unavailable in this browser.`);
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    this.recognition = new SpeechRecognition();
    debugLog(`[WakeDebug] recognition created on instance ${this.instanceId}`);

    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.maxAlternatives = 3;
    this.recognition.lang = 'en-US';

    this.recognition.onstart = () => {
      debugLog(`[WakeDebug] ONSTART (instance: ${this.instanceId})`);
      this.startingRecognition = false;
      this.recognitionRunning = true;
      this.retryCount = 0;
      if (this.state === 'DISABLED' || this.state === 'ERROR' || this.state === 'IDLE') {
        this.setState('LISTENING_FOR_WAKE_WORD');
      }
    };

    this.recognition.onresult = (event: any) => {
      if (this.isPaused || !this.isEnabled) {
        debugLog(`[WakeDebug] ONRESULT ignored (isPaused: ${this.isPaused}, isEnabled: ${this.isEnabled})`);
        return;
      }

      const resultIndex = event.resultIndex;
      debugLog(`[WakeDebug] ONRESULT fired (resultIndex: ${resultIndex}, totalResults: ${event.results.length})`);

      for (let i = resultIndex; i < event.results.length; i++) {
        const resultObj = event.results[i];
        if (!resultObj) continue;

        const transcript = resultObj[0].transcript;
        const isFinal = resultObj.isFinal;
        if (!transcript || !transcript.trim()) continue;

        const normTranscript = normalizeWakeTranscript(transcript);
        this.lastTranscript = transcript;
        this.lastNormalizedTranscript = normTranscript;
        this.lastIsFinal = isFinal;
        this.lastResultIndex = i;
        this.lastEventTime = new Date().toLocaleTimeString();

        debugLog(`[WakeDebug] raw transcript length: ${transcript.length}`);
        debugLog(`[WakeDebug] normalized transcript length: ${normTranscript.length}`);

        // 1. In LISTENING_FOR_WAKE_WORD state
        if (this.state === 'LISTENING_FOR_WAKE_WORD') {
          const matchRes = matchWakeWord(transcript);
          debugLog(`[WakeDebug] match result: matched=${matchRes.isMatch}`);

          if (matchRes.isMatch) {
            debugLog(`[WakeDebug] wake alias matched`);
            debugLog(`[WakeDebug] wake detected; command length: ${matchRes.commandText?.length ?? 0}`);
            this.lastMatchedAlias = matchRes.matchedAlias;
            this.wakeResultIndex = i;

            if (matchRes.commandText && matchRes.commandText.length > 0) {
              if (isStopPhrase(matchRes.commandText)) {
                debugLog(`[WakeDebug] Stop phrase detected during wake extraction`);
                this.handleStopPhrase();
                break;
              }
              // Utterance contained both wake phrase and command (e.g. "Hey ByteX, open Chrome")
              this.setState('WAKE_DETECTED');
              this.notifyWakeWord(matchRes.commandText);
              this.handleCommandCaptured(matchRes.commandText);
            } else {
              // User only said "Hey ByteX", transition to LISTENING_FOR_COMMAND
              debugLog('[WakeDebug] entering command listening');
              this.setState('WAKE_DETECTED');
              this.notifyWakeWord('');
              this.setState('LISTENING_FOR_COMMAND');
              this.startCommandTimeout();
            }
            break;
          }
        }
        // 2. In LISTENING_FOR_COMMAND or CONTINUOUS_LISTENING state
        else if (this.state === 'LISTENING_FOR_COMMAND' || this.state === 'CONTINUOUS_LISTENING') {
          // Ignore duplicate finalization event of the wake word phrase itself on wakeResultIndex
          if (i === this.wakeResultIndex) {
            const matchRes = matchWakeWord(transcript);
            if (matchRes.isMatch && matchRes.commandText && matchRes.commandText.length > 0) {
              if (isStopPhrase(matchRes.commandText)) {
                this.handleStopPhrase();
                break;
              }
              debugLog(`[WakeDebug] command extracted from wake stream (length ${matchRes.commandText?.length ?? 0})`);
              this.clearCommandTimeout();
              this.clearContinuousTimeout();
              this.handleCommandCaptured(matchRes.commandText);
              break;
            }
            debugLog(`[WakeDebug] ignoring finalization of wake phrase at idx ${i}`);
            continue;
          }

          const matchRes = matchWakeWord(transcript);
          const finalCommand = matchRes.isMatch ? matchRes.commandText : transcript.trim();
          const cleanCmd = finalCommand.replace(/^[.!?,\s:]+/, '').replace(/[.!?,\s:]+$/, '').trim();

          if (cleanCmd && cleanCmd.length > 0) {
            if (isStopPhrase(cleanCmd)) {
              debugLog(`[WakeDebug] Stop phrase captured in state ${this.state}`);
              this.handleStopPhrase();
              break;
            }

            if (isFinal || cleanCmd.length >= 3) {
              debugLog(`[WakeDebug] command captured in ${this.state} state (length ${cleanCmd.length})`);
              this.clearCommandTimeout();
              this.clearContinuousTimeout();
              this.handleCommandCaptured(cleanCmd);
              break;
            }
          }
        }
      }
    };

    this.recognition.onerror = (event: any) => {
      const err = event.error;
      console.warn(`[WakeDebug] recognition error: ${err} (instance: ${this.instanceId})`);
      this.startingRecognition = false;
      this.lastError = err;

      if (err === 'no-speech' || err === 'aborted') {
        return;
      }

      if (err === 'audio-capture') {
        console.error('[WakeDebug] microphone audio-capture error');
        this.permissionState = 'BUSY';
        this.lastError = 'Microphone is unavailable or being used by another application.';
        this.setState('ERROR');
        this.notifyError(this.lastError);
        this.stop();
        return;
      }

      if (err === 'not-allowed' || err === 'service-not-allowed') {
        console.error('[WakeDebug] microphone permission denied or service blocked');
        this.permissionState = 'DENIED';
        this.lastError = 'Microphone permission is required for wake-word activation.';
        this.setState('ERROR');
        this.notifyError(this.lastError);
        this.stop();
        return;
      }

      this.lastError = `Speech recognition error: ${err}`;
      this.handleBoundedRetry();
    };

    this.recognition.onend = () => {
      debugLog(`[WakeDebug] recognition onend (state=${this.state}, enabled=${this.isEnabled}, paused=${this.isPaused})`);
      this.recognitionRunning = false;
      this.startingRecognition = false;

      if (this.isEnabled && !this.isPaused && this.state !== 'ERROR' && this.state !== 'DISABLED') {
        debugLog('[WakeDebug] scheduling restart after onend');
        this.scheduleRestart(300);
      }
    };
  }

  private handleStopPhrase() {
    debugLog('[WakeDebug] Continuous session ended by user stop phrase.');
    this.clearCommandTimeout();
    this.clearContinuousTimeout();
    this.resetToListening();
    this.notifyError('Okay.');
  }

  private handleCommandCaptured(commandText: string) {
    debugLog(`[WakeDebug] handleCommandCaptured (length ${commandText.length})`);
    this.setState('PROCESSING');
    this.notifyCommand(commandText);
  }

  private startCommandTimeout() {
    this.clearCommandTimeout();
    this.commandTimeoutTimer = setTimeout(() => {
      if (this.state === 'LISTENING_FOR_COMMAND') {
        debugLog('[WakeDebug] Command window timed out with no speech. Returning to LISTENING_FOR_WAKE_WORD.');
        this.notifyError("I didn't hear a command.");
        this.resetToListening();
      }
    }, this.commandTimeoutMs);
  }

  private clearCommandTimeout() {
    if (this.commandTimeoutTimer) {
      clearTimeout(this.commandTimeoutTimer);
      this.commandTimeoutTimer = null;
    }
  }

  public startContinuousTimeout() {
    this.clearContinuousTimeout();
    this.continuousTimeoutTimer = setTimeout(() => {
      if (this.state === 'CONTINUOUS_LISTENING') {
        debugLog('[WakeDebug] Continuous listening session timed out (15s). Returning to LISTENING_FOR_WAKE_WORD.');
        this.resetToListening();
      }
    }, this.conversationTimeoutMs);
  }

  private clearContinuousTimeout() {
    if (this.continuousTimeoutTimer) {
      clearTimeout(this.continuousTimeoutTimer);
      this.continuousTimeoutTimer = null;
    }
  }

  private clearRestartTimer() {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
  }

  private scheduleRestart(delayMs: number = 300) {
    this.clearRestartTimer();
    if (!this.isEnabled || this.isPaused || this.state === 'ERROR' || this.state === 'DISABLED') {
      return;
    }
    debugLog(`[WakeDebug] Scheduling recognition restart in ${delayMs}ms...`);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      this.restartRecognition();
    }, delayMs);
  }

  public resetToListening() {
    this.clearCommandTimeout();
    this.clearContinuousTimeout();
    this.wakeResultIndex = -1;
    if (this.isEnabled && !this.isPaused) {
      this.setState('LISTENING_FOR_WAKE_WORD');
    } else {
      this.setState('IDLE');
    }
  }

  public onTTSFinished() {
    debugLog(`[WakeDebug] onTTSFinished called (continuous: ${this.continuousListeningEnabled}, state: ${this.state})`);
    if (!this.isEnabled) return;

    if (this.continuousListeningEnabled) {
      debugLog('[WakeDebug] Continuous listening mode active. Entering CONTINUOUS_LISTENING state.');
      this.isPaused = false;
      this.setState('CONTINUOUS_LISTENING');
      this.startContinuousTimeout();
      this.scheduleRestart(200);
    } else {
      this.resetToListening();
      this.resume();
    }
  }

  public onCommandFinished() {
    debugLog(`[WakeDebug] onCommandFinished called (continuous: ${this.continuousListeningEnabled})`);
    if (!this.isEnabled) return;

    if (this.continuousListeningEnabled) {
      debugLog('[WakeDebug] Continuous listening active post-command. Entering CONTINUOUS_LISTENING.');
      this.isPaused = false;
      this.setState('CONTINUOUS_LISTENING');
      this.startContinuousTimeout();
      this.scheduleRestart(200);
    } else {
      this.resetToListening();
      this.resume();
    }
  }

  private restartRecognition() {
    if (!this.recognition || !this.isEnabled || this.isPaused) {
      debugLog(`[WakeDebug] restartRecognition skipped (rec: ${!!this.recognition}, enabled: ${this.isEnabled}, paused: ${this.isPaused})`);
      return;
    }

    if (this.recognitionRunning || this.startingRecognition) {
      debugLog(`[WakeDebug] restartRecognition skipped (already running or starting)`);
      return;
    }

    try {
      debugLog(`[WakeDebug] recognition start on instance ${this.instanceId}`);
      this.startingRecognition = true;
      this.recognition.start();
    } catch (e: any) {
      this.startingRecognition = false;
      if (e.name === 'InvalidStateError' || (e.message && e.message.includes('already started'))) {
        debugLog('[WakeDebug] recognition already started cleanly (InvalidStateError)');
        this.recognitionRunning = true;
        return;
      }
      console.warn('[WakeDebug] recognition start exception:', e);
      this.handleBoundedRetry();
    }
  }

  private handleBoundedRetry() {
    if (this.retryCount < this.maxRetries) {
      this.retryCount++;
      const delay = Math.min(1000 * Math.pow(2, this.retryCount - 1), 5000);
      debugLog(`[WakeDebug] Retrying recognition (${this.retryCount}/${this.maxRetries}) in ${delay}ms...`);
      this.scheduleRestart(delay);
    } else {
      console.warn('[WakeDebug] Maximum restart attempts reached. Returning to ERROR/IDLE.');
      this.lastError = 'Wake-word recognition stopped after repeated connection errors.';
      this.setState('ERROR');
      this.notifyError(this.lastError);
    }
  }

  public async start() {
    debugLog(`[WakeDebug] START_CALLED on instance ${this.instanceId}`);

    if (!this.isSupported()) {
      this.lastError = 'Wake-word voice activation is unavailable (speech recognition unsupported by this browser).';
      this.setState('ERROR');
      this.notifyError(this.lastError);
      return;
    }

    // Explicitly request microphone permission first via getUserMedia and immediately release stream tracks
    if (typeof navigator !== 'undefined' && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        debugLog('[WakeDebug] requesting microphone permission via getUserMedia...');
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.permissionState = 'GRANTED';
        debugLog('[WakeDebug] microphone permission granted. Releasing permission test MediaStream tracks.');
        // CRITICAL FIX: Release MediaStream tracks immediately so microphone hardware is not held locked!
        stream.getTracks().forEach((track) => track.stop());
      } catch (err: any) {
        console.error('[WakeDebug] microphone permission denied by user or device:', err);
        this.permissionState = 'DENIED';
        this.lastError = 'Microphone permission denied. Please allow microphone access in browser settings.';
        this.setState('ERROR');
        this.notifyError(this.lastError);
        return;
      }
    }

    this.isEnabled = true;
    this.isPaused = false;
    this.retryCount = 0;
    this.wakeResultIndex = -1;
    this.setState('LISTENING_FOR_WAKE_WORD');
    this.restartRecognition();
  }

  public stop() {
    debugLog(`[WakeDebug] stop() called on instance ${this.instanceId}`);
    this.isEnabled = false;
    this.isPaused = false;
    this.wakeResultIndex = -1;
    this.recognitionRunning = false;
    this.startingRecognition = false;
    this.clearCommandTimeout();
    this.clearContinuousTimeout();
    this.clearRestartTimer();

    if (this.recognition) {
      try {
        this.recognition.abort();
      } catch (e) {
        // Ignore
      }
    }
    this.setState('DISABLED');
  }

  public pause() {
    debugLog(`[WakeDebug] pause() called on instance ${this.instanceId}`);
    this.isPaused = true;
    this.recognitionRunning = false;
    this.startingRecognition = false;
    this.clearCommandTimeout();
    this.clearContinuousTimeout();
    this.clearRestartTimer();

    if (this.recognition) {
      try {
        this.recognition.abort();
      } catch (e) {
        // Ignore
      }
    }
    if (this.state !== 'DISABLED') {
      this.setState('IDLE');
    }
  }

  public resume() {
    debugLog(`[WakeDebug] resume() called on instance ${this.instanceId}`);
    if (!this.isEnabled) return;
    this.isPaused = false;
    this.retryCount = 0;
    this.wakeResultIndex = -1;
    this.setState('LISTENING_FOR_WAKE_WORD');
    this.scheduleRestart(200);
  }

  // Subscriptions
  public onStateChange(callback: WakeWordStateCallback): () => void {
    this.stateCallbacks.add(callback);
    return () => this.stateCallbacks.delete(callback);
  }

  public onWakeWord(callback: WakeWordEventCallback): () => void {
    this.wakeWordCallbacks.add(callback);
    return () => this.wakeWordCallbacks.delete(callback);
  }

  public onCommandCaptured(callback: WakeWordEventCallback): () => void {
    this.commandCallbacks.add(callback);
    return () => this.commandCallbacks.delete(callback);
  }

  public onError(callback: WakeWordErrorCallback): () => void {
    this.errorCallbacks.add(callback);
    return () => this.errorCallbacks.delete(callback);
  }

  private notifyState() {
    this.stateCallbacks.forEach((fn) => fn(this.state));
  }

  private notifyWakeWord(commandText: string) {
    this.wakeWordCallbacks.forEach((fn) => fn(commandText));
  }

  private notifyCommand(commandText: string) {
    this.commandCallbacks.forEach((fn) => fn(commandText));
  }

  private notifyError(error: string) {
    this.errorCallbacks.forEach((fn) => fn(error));
  }

  // Diagnostic helper for raw mic test (Step 2)
  public async runRawMicTest(onLog: (m: string) => void) {
    debugLog('[WakeDebug] RAW_MIC_TEST requested');
    if (!this.isSupported()) {
      onLog('RAW_MIC_ERROR: Unsupported browser');
      return;
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      }
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      const rec = new SR();
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = 'en-US';

      rec.onstart = () => {
        debugLog('[WakeDebug] RAW_MIC_START');
        onLog('RAW_MIC_START');
      };
      rec.onresult = (event: any) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const tr = event.results[i][0].transcript;
          const fin = event.results[i].isFinal;
          debugLog('[WakeDebug] RAW_MIC_RESULT', { length: tr.length, isFinal: fin });
          onLog(`RAW_MIC_RESULT: "${tr}" (isFinal: ${fin})`);
        }
      };
      rec.onerror = (event: any) => {
        debugLog('[WakeDebug] RAW_MIC_ERROR: ' + event.error);
        onLog(`RAW_MIC_ERROR: ${event.error}`);
      };
      rec.onend = () => {
        debugLog('[WakeDebug] RAW_MIC_END');
        onLog('RAW_MIC_END');
      };
      rec.start();
    } catch (e: any) {
      onLog(`RAW_MIC_EXCEPTION: ${e.message}`);
    }
  }

  // Diagnostic helper to test microphone audio capture in browser UI
  public async testMicrophoneAudio(onTranscript: (t: string) => void, onErrorMsg: (e: string) => void) {
    debugLog('[WakeDebug] Running testMicrophoneAudio...');
    if (!this.isSupported()) {
      onErrorMsg('SpeechRecognition is unsupported in this browser.');
      return;
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      }
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      const testRec = new SR();
      testRec.continuous = false;
      testRec.interimResults = false;
      testRec.onstart = () => debugLog('[WakeDebug] Diagnostic Mic Test listening...');
      testRec.onresult = (evt: any) => {
        const tr = evt.results[0][0].transcript;
        debugLog('[WakeDebug] Diagnostic Mic Test heard:', tr);
        onTranscript(tr);
      };
      testRec.onerror = (evt: any) => {
        console.warn('[WakeDebug] Diagnostic Mic Test error:', evt.error);
        onErrorMsg(`Mic test error: ${evt.error}`);
      };
      testRec.start();
    } catch (e: any) {
      onErrorMsg(`Mic test exception: ${e.message}`);
    }
  }

  // Method to manually trigger wake word (used by unit tests)
  public triggerWakeWord(transcript: string = 'Hey ByteX') {
    const { isMatch, commandText } = matchWakeWord(transcript);
    if (isMatch) {
      this.setState('WAKE_DETECTED');
      this.notifyWakeWord(commandText);
      if (commandText) {
        this.handleCommandCaptured(commandText);
      } else {
        this.setState('LISTENING_FOR_COMMAND');
        this.startCommandTimeout();
      }
    }
  }
}

export const wakeWordService = new WakeWordService();
export default wakeWordService;
