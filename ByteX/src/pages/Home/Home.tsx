import React, { useState, useRef, useCallback, useEffect } from 'react';
import Header from '../../components/Header/Header';
import ByteXOrb from '../../components/ByteXOrb/ByteXOrb';
import CommandInput from '../../components/CommandInput/CommandInput';
import ChatHistory from '../../components/Chat/ChatHistory';
import SettingsModal from '../../components/Settings/SettingsModal';
import OrbCustomizer from '../../components/OrbCustomizer/OrbCustomizer';
import QuickActions from '../../components/QuickActions/QuickActions';
import SearchDock from '../../components/SearchDock/SearchDock';
import { useCommand } from '../../hooks/useCommand';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';
import { orbCustomizerService } from '../../services/orbCustomizerService';
import type { OrbState } from '../../types/orb';
import './Home.css';

export const Home: React.FC = () => {
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);
  const [isCustomizerOpen, setIsCustomizerOpen] = useState<boolean>(false);
  const [isQuickActionsOpen, setIsQuickActionsOpen] = useState<boolean>(false);
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);
  const [customizerPreviewState, setCustomizerPreviewState] = useState<OrbState | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const {
    orbState,
    messages,
    connectionStatus,
    isListening,
    isProcessing,
    handleCommandSubmit,
    toggleListening,
    cancelAction,
  } = useCommand();

  const handleFocusInput = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const handleEscapeKey = useCallback(() => {
    if (isSearchOpen) {
      setIsSearchOpen(false);
    } else if (isCustomizerOpen) {
      setIsCustomizerOpen(false);
      setCustomizerPreviewState(null);
    } else if (isSettingsOpen) {
      setIsSettingsOpen(false);
    } else if (isQuickActionsOpen) {
      setIsQuickActionsOpen(false);
    } else {
      cancelAction();
    }
  }, [isSearchOpen, isCustomizerOpen, isSettingsOpen, isQuickActionsOpen, cancelAction]);

  // Global Keyboard Shortcuts
  useKeyboardShortcuts({
    onFocusInput: handleFocusInput,
    onEscape: handleEscapeKey,
  });

  // Clear preview state on any real active assistant state transition
  useEffect(() => {
    if (isListening || isProcessing || orbState !== 'idle') {
      if (!isCustomizerOpen && customizerPreviewState !== null) {
        setCustomizerPreviewState(null);
        orbCustomizerService.setPreviewState(null);
      }
    }
  }, [isListening, isProcessing, orbState, isCustomizerOpen, customizerPreviewState]);

  const onCommandSubmit = useCallback((commandText: string) => {
    setCustomizerPreviewState(null);
    orbCustomizerService.setPreviewState(null);
    handleCommandSubmit(commandText);
  }, [handleCommandSubmit]);

  const onToggleListening = useCallback(() => {
    setCustomizerPreviewState(null);
    orbCustomizerService.setPreviewState(null);
    toggleListening();
  }, [toggleListening]);

  const activeOrbDisplayState = (isCustomizerOpen && customizerPreviewState) ? customizerPreviewState : (customizerPreviewState || orbState);
  const hasMessages = messages.length > 0;

  return (
    <div className="bytex-home-layout">
      {/* --- ATMOSPHERIC AMBIENT ENVIRONMENT --- */}
      <div className="bytex-atmospheric-backdrop" aria-hidden="true">
        {/* Subtle Radial Glow Nodes */}
        <div className="bytex-ambient-glow-core" />
        <div className="bytex-ambient-glow-secondary" />

        {/* Fluid Light Trail Filaments */}
        <svg className="bytex-ambient-light-trails" viewBox="0 0 1440 900" fill="none" preserveAspectRatio="none">
          <path
            d="M-100,520 C300,480 500,280 720,310 C940,340 1100,560 1540,500"
            stroke="url(#trailGrad1)"
            strokeWidth="1.2"
            strokeOpacity="0.32"
          />
          <path
            d="M-50,380 C350,300 550,500 720,460 C890,420 1150,260 1500,340"
            stroke="url(#trailGrad2)"
            strokeWidth="1.0"
            strokeOpacity="0.25"
          />
          <defs>
            <linearGradient id="trailGrad1" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#00f0ff" stopOpacity="0" />
              <stop offset="30%" stopColor="#00f0ff" stopOpacity="0.45" />
              <stop offset="50%" stopColor="#7000ff" stopOpacity="0.6" />
              <stop offset="70%" stopColor="#00f0ff" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="trailGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#8a2be2" stopOpacity="0" />
              <stop offset="40%" stopColor="#8a2be2" stopOpacity="0.5" />
              <stop offset="60%" stopColor="#38bdf8" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#8a2be2" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>

        {/* Sparse Ambient Stardust Motes */}
        <div className="bytex-ambient-mote mote-1" />
        <div className="bytex-ambient-mote mote-2" />
        <div className="bytex-ambient-mote mote-3" />
        <div className="bytex-ambient-mote mote-4" />

        {/* Floor Horizon Glow */}
        <div className="bytex-ambient-floor-glow" />
      </div>

      {/* --- 1. TOP HEADER --- */}
      <Header
        connectionStatus={connectionStatus}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenCustomizer={() => setIsCustomizerOpen(true)}
        onOpenSearch={() => setIsSearchOpen(true)}
        onOpenAiMenu={() => setIsQuickActionsOpen(true)}
      />

      {/* --- 2. MAIN VIEWPORT EXPERIENCE (OrbStage -> ConversationStage -> ComposerStage) --- */}
      <main className={`bytex-main-stage bytex-home-content ${hasMessages ? 'mode-conversation conversation-state has-messages' : 'mode-empty empty-state no-messages'}`}>
        {/* Stage 1: Orb Stage */}
        <section className="bytex-orb-stage bytex-orb-section">
          <ByteXOrb
            state={activeOrbDisplayState}
            onClick={onToggleListening}
          />
        </section>

        {/* Stage 2: Conversation Stage */}
        {hasMessages && (
          <section className="bytex-conversation-stage bytex-chat-section">
            <ChatHistory messages={messages} />
          </section>
        )}

        {/* Stage 3: Composer Stage */}
        <section className="bytex-composer-stage bytex-input-section">
          <CommandInput
            ref={inputRef}
            onSubmit={onCommandSubmit}
            onMicToggle={onToggleListening}
            isListening={isListening}
            state={activeOrbDisplayState}
            disabled={isProcessing}
            hideMic={isSearchOpen}
          />
        </section>
      </main>

      {/* Modals & Drawers */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />

      <OrbCustomizer
        isOpen={isCustomizerOpen}
        onClose={() => {
          setIsCustomizerOpen(false);
          setCustomizerPreviewState(null);
        }}
        onPreviewStateChange={(st) => setCustomizerPreviewState(st)}
      />

      <QuickActions
        isOpen={isQuickActionsOpen}
        onClose={() => setIsQuickActionsOpen(false)}
        onActionClick={(cmd) => {
          setIsQuickActionsOpen(false);
          handleCommandSubmit(cmd);
        }}
      />

      <SearchDock
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onSearch={(cmd) => {
          setIsSearchOpen(false);
          handleCommandSubmit(cmd);
        }}
        isListening={isListening}
        onMicToggle={onToggleListening}
        state={activeOrbDisplayState}
      />
    </div>
  );
};

export default Home;
