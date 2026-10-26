import React from 'react';
import { Search, Sparkles, Palette, Sliders } from 'lucide-react';
import type { ConnectionStatus } from '../../services/bytexApi';
import './Header.css';

interface HeaderProps {
  connectionStatus?: ConnectionStatus;
  onOpenSettings?: () => void;
  onOpenCustomizer?: () => void;
  onOpenSearch?: () => void;
  onOpenAiMenu?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  connectionStatus = 'online',
  onOpenSettings,
  onOpenCustomizer,
  onOpenSearch,
  onOpenAiMenu,
}) => {
  const isOnline = connectionStatus === 'online';
  const isConnecting = connectionStatus === 'connecting';

  return (
    <header className="bytex-header">
      {/* 1. TOP-LEFT: BYTEX v0.1.0 CORE + ● CORE: ONLINE + Tagline */}
      <div className="bytex-header-left">
        <div className="bytex-header-branding-row">
          <h1 className="bytex-header-title">
            BYTEX <span className="bytex-header-version">v0.1.0 CORE</span>
          </h1>
          <div className="bytex-core-status-inline">
            <span
              className="bytex-core-status-dot"
              style={{
                backgroundColor: isOnline ? '#10b981' : isConnecting ? '#f59e0b' : '#ef4444',
                boxShadow: `0 0 8px ${isOnline ? '#10b981' : isConnecting ? '#f59e0b' : '#ef4444'}`,
              }}
            />
            <span className="bytex-core-status-text">
              CORE: {isOnline ? 'ONLINE' : isConnecting ? 'CONNECTING...' : 'OFFLINE'}
            </span>
          </div>
        </div>
        <div className="bytex-header-tagline">
          <span>THINK</span>
          <span className="bytex-tagline-bullet">•</span>
          <span>SEE</span>
          <span className="bytex-tagline-bullet">•</span>
          <span>DO</span>
          <span className="bytex-tagline-bullet">•</span>
          <span>WITH YOU</span>
        </div>
      </div>

      {/* 2. TOP-RIGHT: COMPACT CIRCULAR GLASS ACTION BUTTONS */}
      <div className="bytex-header-actions">
        {onOpenSearch && (
          <button
            className="bytex-header-btn"
            onClick={onOpenSearch}
            title="Search"
            aria-label="Search"
          >
            <Search size={15} />
          </button>
        )}
        {onOpenAiMenu && (
          <button
            className="bytex-header-btn"
            onClick={onOpenAiMenu}
            title="AI Intelligence & Quick Actions"
            aria-label="AI Intelligence & Quick Actions"
          >
            <Sparkles size={15} />
          </button>
        )}
        {onOpenCustomizer && (
          <button
            className="bytex-header-btn"
            onClick={onOpenCustomizer}
            title="Customize Orb"
            aria-label="Customize Orb"
          >
            <Palette size={15} />
          </button>
        )}
        {onOpenSettings && (
          <button
            className="bytex-header-btn"
            onClick={onOpenSettings}
            title="System Settings"
            aria-label="System Settings"
          >
            <Sliders size={15} />
          </button>
        )}
      </div>
    </header>
  );
};

export default Header;
