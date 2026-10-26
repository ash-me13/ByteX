export interface PairingQRPayload {
  v: number;
  sid: string;
  sec: string;
  pc: string;
  host: string;
  port: number;
  exp: number;
}

export interface PairingSessionResponse {
  session_id: string;
  secret: string;
  pc_name: string;
  pc_id: string;
  host: string;
  port: number;
  expires_at: number;
  expires_in_seconds: number;
  protocol_version: number;
  qr_payload: PairingQRPayload;
}

export interface TrustedDeviceInfo {
  device_id: string;
  device_name: string;
  platform: string;
  paired_at: number;
  status: string;
  permissions: string[];
  last_connected_at?: number;
  is_connected: boolean;
}

export interface PairingStatusResponse {
  has_active_session: boolean;
  session_id?: string;
  status: 'NONE' | 'ACTIVE' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  expires_in_seconds?: number;
  pending_device?: {
    device_id: string;
    device_name: string;
    platform: string;
    requested_at: number;
  };
}

// Same base URL as the rest of the app (ByteX/.env: VITE_API_URL); default is the local backend.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) || 'http://127.0.0.1:8000/api';

class PhonePairingService {
  public async createPairingSession(): Promise<PairingSessionResponse> {
    const url = `${API_BASE}/phone/pairing/create`;
    console.log('[PHONE_UI] Creating pairing session');
    console.log(`[PHONE_UI] Request URL: POST ${url}`);
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    console.log(`[PHONE_UI] Response status: ${res.status}`);
    if (!res.ok) {
      if (res.status === 404) {
        throw new Error(`Pairing endpoint not found: POST ${url}`);
      } else if (res.status >= 500) {
        throw new Error('Failed to create pairing session. Check ByteX backend logs.');
      }
      throw new Error(`Failed to create pairing session: ${res.statusText}`);
    }
    return res.json();
  }

  public async cancelPairingSession(sessionId: string): Promise<void> {
    try {
      await fetch(`${API_BASE}/phone/pairing/cancel?session_id=${encodeURIComponent(sessionId)}`, {
        method: 'POST',
      });
    } catch (e) {
      console.warn('[PhonePairingService] Cancel error:', e);
    }
  }

  public async getPairingStatus(sessionId: string): Promise<PairingStatusResponse> {
    const res = await fetch(`${API_BASE}/phone/pairing/status?session_id=${encodeURIComponent(sessionId)}`);
    if (!res.ok) {
      return { has_active_session: false, status: 'EXPIRED' };
    }
    return res.json();
  }

  public async approvePairing(sessionId: string, approved: boolean): Promise<any> {
    const res = await fetch(`${API_BASE}/phone/pairing/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, approved }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to approve pairing');
    }
    return res.json();
  }

  public async getTrustedDevices(): Promise<TrustedDeviceInfo[]> {
    try {
      const res = await fetch(`${API_BASE}/phone/devices`);
      if (!res.ok) return [];
      return res.json();
    } catch (e) {
      console.warn('[PhonePairingService] getTrustedDevices error:', e);
      return [];
    }
  }

  public async revokeDevice(deviceId: string): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/phone/devices/${encodeURIComponent(deviceId)}/revoke`, {
        method: 'POST',
      });
      return res.ok;
    } catch (e) {
      console.warn('[PhonePairingService] revokeDevice error:', e);
      return false;
    }
  }

  public async disconnectDevice(deviceId: string): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/phone/devices/${encodeURIComponent(deviceId)}/disconnect`, {
        method: 'POST',
      });
      return res.ok;
    } catch (e) {
      console.warn('[PhonePairingService] disconnectDevice error:', e);
      return false;
    }
  }
}

export const phonePairingService = new PhonePairingService();
export default phonePairingService;
