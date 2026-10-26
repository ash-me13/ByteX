import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera,
  Search,
  LayoutGrid,
  Clipboard,
  MoreHorizontal,
  Volume2,
  Wifi,
  Bluetooth,
  Lock,
  ChevronLeft,
} from 'lucide-react';
import './QuickActions.css';

interface QuickActionsProps {
  isOpen: boolean;
  onClose: () => void;
  onActionClick: (command: string) => void;
  disabled?: boolean;
}

interface ActionItem {
  id: string;
  label: string;
  command?: string;
  icon: React.ReactNode;
  isMoreToggle?: boolean;
  isBackToggle?: boolean;
  tooltip?: string;
}

export const QuickActions: React.FC<QuickActionsProps> = ({
  isOpen,
  onClose,
  onActionClick,
  disabled = false,
}) => {
  const [view, setView] = useState<'main' | 'more'>('main');
  const panelRef = useRef<HTMLDivElement>(null);
  const lastClickTimeRef = useRef<number>(0);

  // Reset view to 'main' whenever panel is closed
  useEffect(() => {
    if (!isOpen) {
      setView('main');
    }
  }, [isOpen]);

  // Click-outside listener
  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node;
      // If click is outside the panel and not on the quickactions toggle button
      if (
        panelRef.current &&
        !panelRef.current.contains(target) &&
        !(target as HTMLElement).closest('.bytex-quickactions-toggle-btn')
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [isOpen, onClose]);

  const handleAction = useCallback(
    (item: ActionItem) => {
      if (disabled) return;

      const now = Date.now();
      if (now - lastClickTimeRef.current < 400) {
        return; // Prevent accidental rapid double-dispatch
      }
      lastClickTimeRef.current = now;

      if (item.isMoreToggle) {
        setView('more');
        return;
      }

      if (item.isBackToggle) {
        setView('main');
        return;
      }

      if (item.command) {
        onActionClick(item.command);
      }
    },
    [disabled, onActionClick]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, item: ActionItem) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleAction(item);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    },
    [handleAction, onClose]
  );

  if (!isOpen) {
    return null;
  }

  const mainActions: ActionItem[] = [
    {
      id: 'screenshot',
      label: 'Screenshot',
      command: 'Take a screenshot',
      icon: <Camera size={13} className="bytex-action-icon" />,
      tooltip: 'Capture desktop screenshot',
    },
    {
      id: 'search',
      label: 'Search',
      command: 'Search the web',
      icon: <Search size={13} className="bytex-action-icon" />,
      tooltip: 'Search the web or files',
    },
    {
      id: 'open-app',
      label: 'Open App',
      command: 'Open application',
      icon: <LayoutGrid size={13} className="bytex-action-icon" />,
      tooltip: 'Launch an installed application',
    },
    {
      id: 'clipboard',
      label: 'Clipboard',
      command: 'What is in my clipboard?',
      icon: <Clipboard size={13} className="bytex-action-icon" />,
      tooltip: 'Inspect or manage Windows clipboard',
    },
    {
      id: 'more-toggle',
      label: 'More',
      isMoreToggle: true,
      icon: <MoreHorizontal size={13} className="bytex-action-icon" />,
      tooltip: 'View additional system quick actions',
    },
  ];

  const moreActions: ActionItem[] = [
    {
      id: 'back-toggle',
      label: 'Back',
      isBackToggle: true,
      icon: <ChevronLeft size={13} className="bytex-action-icon" />,
      tooltip: 'Return to primary actions',
    },
    {
      id: 'volume',
      label: 'Volume',
      command: 'Check system volume and performance',
      icon: <Volume2 size={13} className="bytex-action-icon" />,
      tooltip: 'Inspect system volume and audio status',
    },
    {
      id: 'wifi',
      label: 'Wi-Fi',
      command: 'Check network and system status',
      icon: <Wifi size={13} className="bytex-action-icon" />,
      tooltip: 'Check wireless network connectivity',
    },
    {
      id: 'bluetooth',
      label: 'Bluetooth',
      command: 'Check bluetooth and system status',
      icon: <Bluetooth size={13} className="bytex-action-icon" />,
      tooltip: 'Check bluetooth device connections',
    },
    {
      id: 'lock',
      label: 'Lock PC',
      command: 'Lock PC',
      icon: <Lock size={13} className="bytex-action-icon" />,
      tooltip: 'Safely lock Windows workstation (Requires Confirmation)',
    },
  ];

  const currentActions = view === 'main' ? mainActions : moreActions;

  return (
    <div
      ref={panelRef}
      className="bytex-quickactions-panel"
      role="toolbar"
      aria-label="Quick Actions Menu"
    >
      <div className="bytex-quickactions-track">
        {currentActions.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`bytex-quickaction-chip ${item.isMoreToggle || item.isBackToggle ? 'toggle-chip' : ''}`}
            onClick={() => handleAction(item)}
            onKeyDown={(e) => handleKeyDown(e, item)}
            disabled={disabled}
            title={item.tooltip || item.label}
            aria-label={item.label}
            tabIndex={0}
          >
            {item.icon}
            <span className="bytex-action-label">{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default QuickActions;
