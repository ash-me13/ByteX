import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X, ArrowRight, Mic, MicOff } from 'lucide-react';
import type { OrbState } from '../../types/orb';
import './SearchDock.css';

interface SearchDockProps {
  isOpen: boolean;
  onClose: () => void;
  onSearch: (query: string) => void;
  isListening?: boolean;
  onMicToggle?: (isListening: boolean) => void;
  state?: OrbState;
}

const DEFAULT_TAG_CHIPS = ['SIH', 'OpenAI', 'Web Dev', 'Docker'];

export const SearchDock: React.FC<SearchDockProps> = ({
  isOpen,
  onClose,
  onSearch,
  isListening = false,
  onMicToggle,
  state = 'idle',
}) => {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);

  // Autofocus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    } else {
      setQuery('');
    }
  }, [isOpen]);

  // Click-outside listener
  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node;
      if (
        dockRef.current &&
        !dockRef.current.contains(target) &&
        !(target as HTMLElement).closest('.bytex-header-btn')
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [isOpen, onClose]);

  const handleSubmit = useCallback((e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    let finalCommand = trimmed;
    if (!trimmed.toLowerCase().startsWith('search:') && !trimmed.toLowerCase().startsWith('web:')) {
      finalCommand = `search: ${trimmed}`;
    }

    onSearch(finalCommand);
  }, [query, onSearch]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSubmit();
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  const handleSelectChip = (chip: string) => {
    onSearch(chip);
  };

  if (!isOpen) return null;

  const isMicActive = isListening || state === 'listening';
  const isVoiceSpeaking = state === 'speaking';
  const isProcessingState = state === 'thinking' || state === 'processing';

  return (
    <div className="bytex-search-dock-overlay" aria-modal="true" role="dialog">
      <div ref={dockRef} className="bytex-search-dock-panel">
        {/* 1. Top Search Input Bar */}
        <form className="bytex-search-panel-form" onSubmit={handleSubmit}>
          <div className="bytex-search-panel-input-box">
            <Search size={16} className="bytex-search-panel-icon" />
            <input
              ref={inputRef}
              type="text"
              className="bytex-search-panel-input"
              placeholder="Search the web..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label="Search the web"
            />
            {query.length > 0 && (
              <button
                type="button"
                className="bytex-search-panel-clear-btn"
                onClick={() => {
                  setQuery('');
                  inputRef.current?.focus();
                }}
                title="Clear search"
                aria-label="Clear search"
              >
                <X size={13} />
              </button>
            )}
            <button
              type="submit"
              className="bytex-search-panel-submit-btn"
              disabled={!query.trim()}
              title="Search (Enter)"
              aria-label="Search"
            >
              <ArrowRight size={15} />
            </button>
          </div>
        </form>

        {/* 2. Small Recent Search Chips */}
        <div className="bytex-search-chips-row">
          {DEFAULT_TAG_CHIPS.map((chip) => (
            <button
              key={chip}
              type="button"
              className="bytex-search-tag-chip"
              onClick={() => handleSelectChip(chip)}
            >
              {chip}
            </button>
          ))}
        </div>

        {/* 3. Existing Microphone INSIDE the bottom-center of the Search Panel */}
        {onMicToggle && (
          <div className="bytex-search-dock-mic-center">
            <button
              type="button"
              className={`bytex-search-panel-mic-btn ${
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
              <span className="bytex-search-panel-mic-icon">
                {isMicActive ? <MicOff size={18} /> : <Mic size={18} />}
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchDock;
