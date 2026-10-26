import { debugLog } from '../lib/debug';
import { useState, useEffect, useCallback, useRef } from 'react';
import sttService from '../services/sttService';
import ttsService from '../services/ttsService';
import wakeWordService from '../services/wakeWordService';
import type { WakeWordState } from '../services/wakeWordService';
import voiceSettingsService from '../services/voiceSettingsService';
import type { VoiceSettings } from '../services/voiceSettingsService';

export const useVoice = (
  onTranscriptReceived: (text: string) => void,
  onSystemMessage: (text: string) => void
) => {
  const [settings, setSettings] = useState<VoiceSettings>(voiceSettingsService.getSettings());
  const [isListening, setIsListening] = useState<boolean>(false);
  const [isSpeaking, setIsSpeaking] = useState<boolean>(false);
  const [wakeWordState, setWakeWordState] = useState<WakeWordState>(wakeWordService.getState());

  const onTranscriptRef = useRef(onTranscriptReceived);
  const onSystemMsgRef = useRef(onSystemMessage);
  const settingsRef = useRef(settings);

  useEffect(() => {
    onTranscriptRef.current = onTranscriptReceived;
    onSystemMsgRef.current = onSystemMessage;
    settingsRef.current = settings;
  }, [onTranscriptReceived, onSystemMessage, settings]);

  // Sync settings when updated
  const updateSettings = useCallback((newSettings: Partial<VoiceSettings>) => {
    const updated = voiceSettingsService.save(newSettings);
    const continuousActive = updated.continuousListeningEnabled ?? updated.continuous ?? false;
    debugLog('[WakeDebug] updateSettings called: wakeWordEnabled =', updated.wakeWordEnabled, 'continuous =', continuousActive);
    setSettings(updated);
    sttService.setLanguage(updated.language);
    wakeWordService.setContinuousListening(continuousActive);

    if (updated.wakeWordEnabled) {
      wakeWordService.start();
    } else {
      wakeWordService.stop();
    }
  }, []);

  // Reset to default settings
  const resetSettings = useCallback(() => {
    const reset = voiceSettingsService.resetToDefaults();
    setSettings(reset);
    sttService.setLanguage(reset.language);
    wakeWordService.setContinuousListening(reset.continuousListeningEnabled);
    if (reset.wakeWordEnabled) {
      wakeWordService.start();
    } else {
      wakeWordService.stop();
    }
  }, []);

  // Sync WakeWordService on mount & settings change
  useEffect(() => {
    const continuousActive = settings.continuousListeningEnabled ?? settings.continuous ?? false;
    debugLog('[WakeDebug] useEffect settings.wakeWordEnabled =', settings.wakeWordEnabled, 'continuous =', continuousActive);
    wakeWordService.setContinuousListening(continuousActive);
    if (settings.wakeWordEnabled) {
      wakeWordService.start();
    } else {
      wakeWordService.stop();
    }
  }, [settings.wakeWordEnabled, settings.continuousListeningEnabled, settings.continuous]);

  // Listen to STT, TTS, and WakeWord events
  useEffect(() => {
    sttService.setLanguage(settings.language);

    const unsubSTTState = sttService.onStateChange((listening) => {
      debugLog('[WakeDebug] useVoice STT state change:', listening);
      setIsListening(listening);
      if (listening) {
        wakeWordService.pause();
      } else if (settings.wakeWordEnabled && !ttsService.isSpeaking()) {
        wakeWordService.onCommandFinished();
      }
    });

    const unsubSTTResult = sttService.onResult((transcript) => {
      debugLog('[WakeDebug] useVoice STT result length:', transcript.length);
      if (onTranscriptRef.current) {
        onTranscriptRef.current(transcript);
      }
    });

    const unsubSTTError = sttService.onError((errorMsg) => {
      console.warn('[WakeDebug] useVoice STT error:', errorMsg);
      if (onSystemMsgRef.current) {
        onSystemMsgRef.current(errorMsg);
      }
    });

    const unsubTTSState = ttsService.onStateChange((speaking) => {
      debugLog('[WakeDebug] useVoice TTS speaking change:', speaking);
      setIsSpeaking(speaking);
      if (speaking) {
        wakeWordService.pause();
      } else if (settings.wakeWordEnabled && !sttService.getIsListening()) {
        wakeWordService.onTTSFinished();
      }
    });

    const unsubWakeState = wakeWordService.onStateChange((state) => {
      debugLog('[WakeDebug] useVoice wakeWordState received:', state);
      setWakeWordState(state);
    });

    const unsubWakeWord = wakeWordService.onWakeWord((commandText) => {
      // If user supplied pure wake word without command (e.g. just "Hey ByteX")
      if (!commandText || !commandText.trim()) {
        const cur = settingsRef.current;
        let phrase = 'Yes?';
        if (cur.wakeResponse === 'listening') phrase = "I'm listening.";
        else if (cur.wakeResponse === 'ready') phrase = 'Ready.';
        else if (cur.wakeResponse === 'help') phrase = 'How can I help?';
        else if (cur.wakeResponse === 'go_ahead') phrase = 'Go ahead.';
        else if (cur.wakeResponse === 'custom') phrase = cur.customWakeResponse?.trim() || 'At your service.';

        if (cur.enabled && phrase) {
          ttsService.speak(phrase, {
            rate: cur.rate,
            volume: cur.volume,
            pitch: cur.pitch,
            language: cur.language,
            voiceURI: cur.voiceURI,
            speakOnlyHighlights: false,
          });
        }
      }
    });

    const unsubWakeCommand = wakeWordService.onCommandCaptured((commandText) => {
      debugLog('[WakeDebug] useVoice onCommandCaptured length:', commandText.length);
      if (commandText && commandText.trim() && onTranscriptRef.current) {
        onTranscriptRef.current(commandText.trim());
      }
    });

    const unsubWakeError = wakeWordService.onError((errorMsg) => {
      console.warn('[WakeDebug] useVoice wakeWordError:', errorMsg);
      if (onSystemMsgRef.current) {
        onSystemMsgRef.current(errorMsg);
      }
    });

    return () => {
      unsubSTTState();
      unsubSTTResult();
      unsubSTTError();
      unsubTTSState();
      unsubWakeState();
      unsubWakeWord();
      unsubWakeCommand();
      unsubWakeError();
    };
  }, [settings.language, settings.wakeWordEnabled]);

  // Handle TTS output for assistant response
  const speakResponse = useCallback(
    (text: string) => {
      if (settings.enabled && text) {
        wakeWordService.pause();
        ttsService.speak(text, {
          rate: settings.rate,
          volume: settings.volume,
          pitch: settings.pitch,
          language: settings.language,
          voiceURI: settings.voiceURI,
        });
      } else if (settings.wakeWordEnabled) {
        wakeWordService.onCommandFinished();
      }
    },
    [settings]
  );

  // Streaming speech: speak complete sentences from ASSISTANT_DELTA text while the answer is still being generated.
  const speakStreamDelta = useCallback(
    (delta: string) => {
      if (!settings.enabled || !delta) return;
      if (!ttsService.isStreaming()) {
        wakeWordService.pause();
        ttsService.beginStream({
          rate: settings.rate,
          volume: settings.volume,
          pitch: settings.pitch,
          language: settings.language,
          voiceURI: settings.voiceURI,
        });
      }
      ttsService.pushStream(delta);
    },
    [settings]
  );

  // Answer complete: returns true when streaming speech handled it (the full text must not be spoken again).
  const finishSpeechStream = useCallback((): boolean => ttsService.endStream(), []);

  // Stop ongoing speech output immediately (User Interruption)
  const stopSpeaking = useCallback(() => {
    ttsService.stop();
    setIsSpeaking(false);
    if (settings.wakeWordEnabled) {
      wakeWordService.onTTSFinished();
    }
  }, [settings.wakeWordEnabled]);

  // Test voice preview (Safety: zero command execution)
  const testVoice = useCallback(() => {
    if (settings.enabled) {
      ttsService.speak("Hello, I'm ByteX.", {
        rate: settings.rate,
        volume: settings.volume,
        pitch: settings.pitch,
        language: settings.language,
        voiceURI: settings.voiceURI,
        speakOnlyHighlights: false,
      });
    }
  }, [settings]);

  // Toggle manual microphone listening input (push-to-talk)
  const toggleListening = useCallback(async () => {
    // 1. If ByteX is speaking, interrupt TTS output immediately!
    if (ttsService.isSpeaking() || isSpeaking) {
      stopSpeaking();
      return;
    }

    // 2. If listening, cancel STT
    if (isListening) {
      sttService.cancel();
      setIsListening(false);
      if (settings.wakeWordEnabled) {
        wakeWordService.onCommandFinished();
      }
      return;
    }

    // 3. Otherwise start manual STT
    wakeWordService.pause();
    const started = await sttService.start();
    if (!started) {
      setIsListening(false);
      if (settings.wakeWordEnabled) {
        wakeWordService.onCommandFinished();
      }
    }
  }, [isListening, isSpeaking, stopSpeaking, settings.wakeWordEnabled]);

  const cancelVoice = useCallback(() => {
    sttService.cancel();
    ttsService.stop();
    setIsListening(false);
    setIsSpeaking(false);
    if (settings.wakeWordEnabled) {
      wakeWordService.onCommandFinished();
    } else {
      wakeWordService.stop();
    }
  }, [settings.wakeWordEnabled]);

  return {
    settings,
    updateSettings,
    resetSettings,
    isListening,
    isSpeaking,
    wakeWordState,
    toggleListening,
    speakResponse,
    speakStreamDelta,
    finishSpeechStream,
    stopSpeaking,
    cancelVoice,
    testVoice,
  };
};

export default useVoice;
