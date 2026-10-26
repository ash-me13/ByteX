import React, { useState, forwardRef, useRef, useEffect } from 'react';
import { Mic, ArrowUp, X, Sparkles, MicOff } from 'lucide-react';
import type { OrbState } from '../../types/orb';
import './CommandInput.css';

interface CommandInputProps {
  onSubmit: (command: string) => void;
  onMicToggle: (isListening: boolean) => void;
  isListening: boolean;
  state?: OrbState;
  disabled?: boolean;
  hideMic?: boolean;
}

export const CommandInput = forwardRef<HTMLTextAreaElement, CommandInputProps>(
  ({ onSubmit, onMicToggle, isListening, state = 'idle', disabled = false, hideMic = false }, ref) => {
    const [text, setText] = useState('');
    const internalRef = useRef<HTMLTextAreaElement | null>(null);

    // Auto-adjust textarea height up to 120px for multiline Shift+Enter
    const adjustHeight = () => {
      const el = internalRef.current;
      if (el) {
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
      }
    };

    useEffect(() => {
      adjustHeight();
    }, [text]);

    const handleSubmit = (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const trimmed = text.trim();
      if (!trimmed || disabled) return;
      onSubmit(trimmed);
      setText('');
      if (internalRef.current) {
        internalRef.current.style.height = 'auto';
      }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    };

    const handleClear = () => {
      setText('');
      if (internalRef.current) {
        internalRef.current.style.height = 'auto';
        internalRef.current.focus();
      }
    };

    const isMicActive = isListening || state === 'listening';
    const isVoiceSpeaking = state === 'speaking';
    const isProcessingState = state === 'thinking' || state === 'processing';

    return (
      <div className="bytex-input-wrapper">
        {/* Central Liquid Glass Input Capsule with Embedded Microphone */}
        <form
          className={`bytex-command-container ${isMicActive ? 'listening-state' : ''}`}
          onSubmit={handleSubmit}
        >
          <div className="bytex-command-box">
            <div className="bytex-input-sparkle-icon" title="ByteX Intelligence">
              <Sparkles size={17} />
            </div>

            <textarea
              ref={(node) => {
                internalRef.current = node;
                if (typeof ref === 'function') {
                  ref(node);
                } else if (ref) {
                  ref.current = node;
                }
              }}
              rows={1}
              className="bytex-command-input"
              placeholder="Tell me what you're thinking..."
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              aria-label="Tell me what you're thinking..."
            />

            {text.length > 0 && (
              <button
                type="button"
                className="bytex-clear-btn"
                onClick={handleClear}
                title="Clear input"
                aria-label="Clear input"
              >
                <X size={15} />
              </button>
            )}

            {/* Embedded Microphone INSIDE Composer Bar */}
            {!hideMic && (
              <button
                type="button"
                className={`bytex-composer-mic-btn ${
                  isMicActive
                    ? 'mic-listening'
                    : isVoiceSpeaking
                    ? 'mic-speaking'
                    : isProcessingState
                    ? 'mic-processing'
                    : 'mic-idle'
                }`}
                onClick={() => onMicToggle(!isMicActive)}
                title={isMicActive ? 'Stop listening' : 'Start voice input'}
                aria-label={isMicActive ? 'Stop listening' : 'Start voice input'}
                aria-pressed={isMicActive}
              >
                {isMicActive && (
                  <>
                    <span className="bytex-mic-pulse-ring ring-1" />
                    <span className="bytex-mic-pulse-ring ring-2" />
                  </>
                )}
                <span className="bytex-composer-mic-icon">
                  {isMicActive ? <MicOff size={16} /> : <Mic size={16} />}
                </span>
              </button>
            )}

            <button
              type="submit"
              className="bytex-send-btn"
              disabled={disabled || !text.trim()}
              title="Send command"
              aria-label="Send command"
            >
              <ArrowUp size={17} />
            </button>
          </div>
        </form>
      </div>
    );
  }
);

CommandInput.displayName = 'CommandInput';

export default CommandInput;
