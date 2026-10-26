import React from 'react';
import { CircleDot, Mic, BrainCircuit, Volume2 } from 'lucide-react';
import type { OrbState } from '../../types/orb';
import './OrbStateSelector.css';

interface OrbStateSelectorProps {
  activeState: OrbState;
  onSelectState?: (state: OrbState) => void;
}

interface StateItem {
  id: OrbState;
  label: string;
  icon: React.ReactNode;
}

const STATES: StateItem[] = [
  { id: 'idle', label: 'Idle', icon: <CircleDot size={14} /> },
  { id: 'listening', label: 'Listening', icon: <Mic size={14} /> },
  { id: 'thinking', label: 'Thinking', icon: <BrainCircuit size={14} /> },
  { id: 'speaking', label: 'Speaking', icon: <Volume2 size={14} /> },
];

export const OrbStateSelector: React.FC<OrbStateSelectorProps> = ({ activeState, onSelectState }) => {
  return (
    <div className="bytex-state-dock-container" role="region" aria-label="Orb State Selector">
      <div className="bytex-state-dock-capsule">
        {STATES.map((item) => {
          const isActive = activeState === item.id;
          return (
            <button
              key={item.id}
              className={`bytex-state-dock-btn ${isActive ? 'active' : ''} state-${item.id}`}
              onClick={() => onSelectState?.(item.id)}
              title={`Orb state: ${item.label}`}
              aria-label={`Orb state: ${item.label}`}
              aria-pressed={isActive}
            >
              <span className="bytex-state-dock-icon">{item.icon}</span>
              <span className="bytex-state-dock-label">{item.label}</span>
              {isActive && <span className="bytex-state-dock-indicator" />}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default OrbStateSelector;
