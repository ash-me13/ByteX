import { debugLog } from '../lib/debug';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { ChatMessage, OrbState, SystemNotification } from '../types';
import bytexApi from '../services/bytexApi';
import type { ConnectionStatus, WSEventPayload } from '../services/bytexApi';
import useVoice from './useVoice';
import wakeWordService from '../services/wakeWordService';
import latencyMarks from '../lib/latencyMarks';

export const useCommand = () => {
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [notifications, setNotifications] = useState<SystemNotification[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('offline');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);

  const activeMsgIdRef = useRef<string | null>(null);
  const currentStreamContentRef = useRef<string>('');

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const handleCommandSubmit = useCallback(async (commandText: string) => {
    const text = commandText.trim();
    if (!text || isProcessing) return;

    debugLog('[WakeDebug] command received in handleCommandSubmit, length:', text.length);

    // Pause wake-word engine during command execution & interrupt TTS
    wakeWordService.pause();
    stopSpeaking();
    latencyMarks.markSubmit();

    activeMsgIdRef.current = null;
    currentStreamContentRef.current = '';

    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}_usr`,
      role: 'user',
      content: text,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsProcessing(true);
    setOrbState('thinking');

    await bytexApi.sendMessage(text);
  }, [isProcessing]);

  const handleTranscriptReceived = useCallback((text: string) => {
    if (text && text.trim()) {
      handleCommandSubmit(text.trim());
    }
  }, [handleCommandSubmit]);

  const handleSystemMessage = useCallback((text: string) => {
    const errorMsg: ChatMessage = {
      id: `msg_${Date.now()}_sys`,
      role: 'system',
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, errorMsg]);
  }, []);

  const {
    settings: voiceSettings,
    updateSettings: updateVoiceSettings,
    resetSettings: resetVoiceSettings,
    testVoice,
    isListening: isVoiceListening,
    isSpeaking: isVoiceSpeaking,
    wakeWordState,
    toggleListening: toggleVoiceListening,
    speakResponse,
    speakStreamDelta,
    finishSpeechStream,
    stopSpeaking,
    cancelVoice,
  } = useVoice(handleTranscriptReceived, handleSystemMessage);

  // Subscribe to backend API events & connection status
  useEffect(() => {
    const unsubStatus = bytexApi.onStatusChange((newStatus) => {
      setConnectionStatus(newStatus);
    });

    const unsubEvents = bytexApi.onEvent((event: WSEventPayload) => {
      if (event.state) {
        setOrbState(event.state);
        const processing = event.state === 'thinking';
        setIsProcessing(processing);

        if (processing) {
          wakeWordService.pause();
        } else if (voiceSettings.wakeWordEnabled && !isVoiceSpeaking) {
          wakeWordService.resume();
        }
      }

      // 1. Non-streaming complete message
      if (event.type === 'ASSISTANT_MESSAGE') {
        const fullText = event.message || event.content || '';
        if (fullText) {
          const msgId = activeMsgIdRef.current || `msg_${Date.now()}_ast`;
          
          setMessages((prev) => {
            const exists = prev.some((m) => m.id === msgId);
            if (exists) {
              return prev.map((m) => (m.id === msgId ? { ...m, content: fullText } : m));
            } else {
              return [
                ...prev,
                {
                  id: msgId,
                  role: 'assistant',
                  content: fullText,
                  timestamp: new Date(),
                },
              ];
            }
          });
          
          speakResponse(fullText);
        }
        setIsProcessing(false);
        activeMsgIdRef.current = null;
        currentStreamContentRef.current = '';
        if (voiceSettings.wakeWordEnabled && !isVoiceSpeaking) {
          wakeWordService.resume();
        }
      }

      // 2. Streaming delta token
      if (event.type === 'ASSISTANT_DELTA') {
        const chunk = event.content !== undefined ? event.content : (event.message !== undefined ? event.message : '');
        if (chunk) {
          latencyMarks.markFirstText();
          speakStreamDelta(chunk);
          currentStreamContentRef.current += chunk;
          const text = currentStreamContentRef.current;

          if (!activeMsgIdRef.current) {
            activeMsgIdRef.current = `msg_${Date.now()}_ast`;
          }

          const msgId = activeMsgIdRef.current;

          setMessages((prev) => {
            const exists = prev.some((m) => m.id === msgId);
            if (exists) {
              return prev.map((m) => (m.id === msgId ? { ...m, content: text } : m));
            } else {
              return [
                ...prev,
                {
                  id: msgId,
                  role: 'assistant',
                  content: text,
                  timestamp: new Date(),
                },
              ];
            }
          });
        }
      }

      // 3. Streaming completion
      if (event.type === 'ASSISTANT_COMPLETE') {
        const rawContent = (event.message && event.message.trim()) ? event.message : (event.content && event.content.trim()) ? event.content : currentStreamContentRef.current;
        let finalContent = rawContent ? rawContent.trim() : '';
        
        // Strip any residual protocol tags
        finalContent = finalContent
          .replace(/<think>[\s\S]*?<\/think>/gi, '')
          .replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '')
          .replace(/<tool>[\s\S]*?<\/tool>/gi, '')
          .replace(/<\/?think>/gi, '')
          .replace(/<\/?tool_call>/gi, '')
          .replace(/<\/?tool>/gi, '')
          .trim();
        
        latencyMarks.markFirstText();
        // If sentences were already spoken from the deltas, just let the queue finish (no duplicate speech).
        const spokenFromStream = finishSpeechStream();

        if (finalContent) {
          const msgId = activeMsgIdRef.current || `msg_${Date.now()}_ast`;
          setMessages((prev) => {
            const exists = prev.some((m) => m.id === msgId);
            if (exists) {
              return prev.map((m) => (m.id === msgId ? { ...m, content: finalContent } : m));
            } else {
              return [
                ...prev,
                {
                  id: msgId,
                  role: 'assistant',
                  content: finalContent,
                  timestamp: new Date(),
                },
              ];
            }
          });
          
          if (!spokenFromStream) speakResponse(finalContent);
        }

        setIsProcessing(false);
        activeMsgIdRef.current = null;
        currentStreamContentRef.current = '';
        if (voiceSettings.wakeWordEnabled && !isVoiceSpeaking) {
          wakeWordService.resume();
        }
      }

      // 4. Live System Monitor Notification
      if (event.type === 'SYSTEM_NOTIFICATION' && event.data) {
        const notifData = event.data;
        const newNotif: SystemNotification = {
          id: `notif_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
          eventType: notifData.event_type || 'SYSTEM_EVENT',
          severity: notifData.severity || 'info',
          message: notifData.message || event.message || 'System notification',
          timestamp: notifData.timestamp || new Date().toISOString(),
          value: notifData.value,
          threshold: notifData.threshold,
        };

        setNotifications((prev) => [...prev.slice(-2), newNotif]);

        // Auto-dismiss after 6 seconds
        setTimeout(() => {
          setNotifications((current) => current.filter((n) => n.id !== newNotif.id));
        }, 6000);
      }

      // 5. System error
      if (event.type === 'ERROR' && event.message) {
        const errorMsg: ChatMessage = {
          id: `msg_${Date.now()}_err`,
          role: 'system',
          content: event.message,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
        activeMsgIdRef.current = null;
        currentStreamContentRef.current = '';
        setIsProcessing(false);
        stopSpeaking(); // an errored turn must not leave queued speech behind
        if (voiceSettings.wakeWordEnabled) {
          wakeWordService.resume();
        }
      }
    });

    return () => {
      unsubStatus();
      unsubEvents();
    };
  }, [speakResponse, speakStreamDelta, finishSpeechStream, stopSpeaking, voiceSettings.wakeWordEnabled, isVoiceSpeaking]);

  const toggleListening = useCallback(() => {
    if (isProcessing) return;
    toggleVoiceListening();
  }, [isProcessing, toggleVoiceListening]);

  const cancelAction = useCallback(() => {
    cancelVoice();
    setIsProcessing(false);
    setOrbState('idle');
    activeMsgIdRef.current = null;
    currentStreamContentRef.current = '';
    if (voiceSettings.wakeWordEnabled) {
      wakeWordService.resume();
    }
  }, [cancelVoice, voiceSettings.wakeWordEnabled]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    activeMsgIdRef.current = null;
    currentStreamContentRef.current = '';
  }, []);

  // Compute actual composite orb state & indicators
  let effectiveOrbState: OrbState = orbState;
  let customStatusMessage: string | undefined = undefined;

  if (wakeWordState === 'CONTINUOUS_LISTENING') {
    effectiveOrbState = 'listening';
    customStatusMessage = '🎤 Listening for your next command...';
  } else if (isVoiceListening || wakeWordState === 'LISTENING_FOR_COMMAND' || wakeWordState === 'WAKE_DETECTED') {
    effectiveOrbState = 'listening';
    customStatusMessage = '🎤 Listening...';
  } else if (isVoiceSpeaking) {
    effectiveOrbState = 'speaking';
    customStatusMessage = 'ByteX is speaking...';
  } else if (isProcessing || wakeWordState === 'PROCESSING') {
    effectiveOrbState = 'thinking';
    customStatusMessage = '✨ Thinking...';
  } else if (wakeWordState === 'LISTENING_FOR_WAKE_WORD') {
    effectiveOrbState = 'idle';
    customStatusMessage = '🎤 Listening for "Hey ByteX"';
  } else if (wakeWordState === 'ERROR') {
    effectiveOrbState = 'error';
    const err = wakeWordService.getLastError().toLowerCase();
    if (err.includes('permission') || err.includes('not-allowed')) {
      customStatusMessage = '⚠ Microphone permission required';
    } else if (err.includes('unsupported') || !wakeWordService.isSupported()) {
      customStatusMessage = "⚠ Wake Word isn't supported in this browser";
    } else if (err.includes('unavailable') || err.includes('busy') || err.includes('audio-capture')) {
      customStatusMessage = '⚠ Microphone is being used by another application';
    } else {
      customStatusMessage = '⚠ Wake Word Error';
    }
  } else if (orbState === 'idle') {
    effectiveOrbState = 'idle';
    customStatusMessage = '● Ready';
  }

  return {
    orbState: effectiveOrbState,
    customStatusMessage,
    wakeWordState,
    setOrbState,
    messages,
    notifications,
    dismissNotification,
    connectionStatus,
    isListening: isVoiceListening,
    isProcessing,
    isSpeaking: isVoiceSpeaking,
    voiceSettings,
    updateVoiceSettings,
    resetVoiceSettings,
    testVoice,
    handleCommandSubmit,
    toggleListening,
    cancelAction,
    clearMessages,
  };
};

export default useCommand;
