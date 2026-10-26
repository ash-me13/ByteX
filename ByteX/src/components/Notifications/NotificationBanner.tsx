import React from 'react';
import { Cpu, HardDrive, BatteryWarning, Wifi, WifiOff, AlertTriangle, Info, X } from 'lucide-react';
import type { SystemNotification } from '../../types';
import './NotificationBanner.css';

interface NotificationBannerProps {
  notifications: SystemNotification[];
  onDismiss: (id: string) => void;
}

const getNotificationIcon = (eventType: string, severity: string) => {
  switch (eventType) {
    case 'CPU_HIGH':
      return <Cpu size={16} className="bytex-notif-icon warning" />;
    case 'RAM_HIGH':
      return <AlertTriangle size={16} className="bytex-notif-icon warning" />;
    case 'DISK_HIGH':
      return <HardDrive size={16} className="bytex-notif-icon warning" />;
    case 'BATTERY_LOW':
      return <BatteryWarning size={16} className="bytex-notif-icon critical" />;
    case 'NETWORK_DISCONNECTED':
      return <WifiOff size={16} className="bytex-notif-icon critical" />;
    case 'NETWORK_RECONNECTED':
      return <Wifi size={16} className="bytex-notif-icon info" />;
    default:
      return severity === 'warning' ? (
        <AlertTriangle size={16} className="bytex-notif-icon warning" />
      ) : (
        <Info size={16} className="bytex-notif-icon info" />
      );
  }
};

export const NotificationBanner: React.FC<NotificationBannerProps> = ({
  notifications,
  onDismiss,
}) => {
  if (notifications.length === 0) return null;

  return (
    <div className="bytex-notification-container" aria-live="polite">
      {notifications.map((notif) => (
        <div key={notif.id} className={`bytex-notification-toast ${notif.severity}`}>
          <div className="bytex-notif-left">
            {getNotificationIcon(notif.eventType, notif.severity)}
            <div className="bytex-notif-body">
              <span className="bytex-notif-title">{notif.eventType.replace(/_/g, ' ')}</span>
              <span className="bytex-notif-message">{notif.message}</span>
            </div>
          </div>
          <button
            type="button"
            className="bytex-notif-close"
            onClick={() => onDismiss(notif.id)}
            title="Dismiss notification"
            aria-label="Dismiss notification"
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
};

export default NotificationBanner;
