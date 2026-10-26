import React from 'react';
import type { OrbState } from '../../types/orb';
import { ORB_STATE_CONFIGS } from '../../types/orb';
import './StatusIndicator.css';

interface StatusIndicatorProps {
  state: OrbState;
  customMessage?: string;
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ state }) => {
  const config = ORB_STATE_CONFIGS[state] || ORB_STATE_CONFIGS.idle;
  const statusColor = config.primaryColor;

  return (
    <div className="bytex-status-container">
      <div className="bytex-status-badge">
        <div
          className="bytex-status-dot"
          style={{
            backgroundColor: statusColor,
            boxShadow: `0 0 12px ${statusColor}`,
          }}
        />
        <span className="bytex-status-tag">{state}</span>
      </div>
    </div>
  );
};

export default StatusIndicator;
