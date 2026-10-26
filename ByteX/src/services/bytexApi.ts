import type { OrbState, MemoryItem } from '../types';

export type ConnectionStatus = 'online' | 'offline' | 'connecting';

export interface WSEventPayload {
  type: 'USER_MESSAGE' | 'ASSISTANT_MESSAGE' | 'ASSISTANT_DELTA' | 'ASSISTANT_COMPLETE' | 'STATE_CHANGE' | 'ERROR' | 'SYSTEM_STATUS' | 'SYSTEM_NOTIFICATION';
  message?: string;
  content?: string;
  state?: OrbState;
  data?: Record<string, any>;
}

export type StatusListener = (status: ConnectionStatus) => void;
export type EventListener = (event: WSEventPayload) => void;

class ByteXApiService {
  private apiUrl: string = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';
  private wsUrl: string = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws';
  
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = 'offline';
  private reconnectTimer: number | null = null;
  private isConnecting: boolean = false;

  private statusListeners: Set<StatusListener> = new Set();
  private eventListeners: Set<EventListener> = new Set();

  constructor() {
    this.connect();
  }

  public getStatus(): ConnectionStatus {
    return this.status;
  }

  public getApiUrl(): string {
    return this.apiUrl;
  }

  public getWsUrl(): string {
    return this.wsUrl;
  }

  public onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  public onEvent(listener: EventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  private setStatus(newStatus: ConnectionStatus) {
    if (this.status !== newStatus) {
      console.log(`[ByteX WS Lifecycle] STATE UPDATE: ${this.status} -> ${newStatus}`);
      this.status = newStatus;
      this.statusListeners.forEach((fn) => fn(newStatus));
    }
  }

  private notifyEvent(event: WSEventPayload) {
    this.eventListeners.forEach((fn) => fn(event));
  }

  public async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/health`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        signal: AbortSignal.timeout(3000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  public connect() {
    if (this.isConnecting || (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN))) {
      return;
    }

    this.isConnecting = true;
    console.log(`[ByteX WS Lifecycle] CONNECTING -> URL: ${this.wsUrl}`);
    this.setStatus('connecting');

    try {
      const socket = new WebSocket(this.wsUrl);
      this.ws = socket;

      socket.onopen = () => {
        this.isConnecting = false;
        console.log(`[ByteX WS Lifecycle] OPEN / CONNECTED -> readyState: ${socket.readyState}, URL: ${this.wsUrl}`);
        this.setStatus('online');
        if (this.reconnectTimer) {
          window.clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      socket.onmessage = (event: MessageEvent) => {
        try {
          const payload: WSEventPayload = JSON.parse(event.data);
          console.log(`[ByteX WS Lifecycle] MESSAGE RECEIVED & PARSED:`, { type: payload.type, state: payload.state, hasMessage: !!payload.message, hasContent: !!payload.content });
          this.notifyEvent(payload);
        } catch (e) {
          console.warn('[ByteX WS Lifecycle] PARSE ERROR:', e);
        }
      };

      socket.onerror = (err) => {
        console.warn(`[ByteX WS Lifecycle] ERROR -> readyState: ${socket.readyState}`, err);
        this.handleDisconnect();
      };

      socket.onclose = (ev: CloseEvent) => {
        console.log(`[ByteX WS Lifecycle] CLOSE -> code: ${ev.code}, reason: "${ev.reason || 'none'}", clean: ${ev.wasClean}`);
        this.handleDisconnect();
      };
    } catch (e) {
      console.warn(`[ByteX WS Lifecycle] Exception during connect:`, e);
      this.handleDisconnect();
    }
  }

  private handleDisconnect() {
    this.isConnecting = false;
    this.setStatus('offline');
    this.ws = null;

    if (!this.reconnectTimer) {
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, 3500);
    }
  }

  public async sendMessage(messageText: string): Promise<boolean> {
    const text = messageText.trim();
    if (!text) return false;

    // 1. Send via WebSocket if OPEN
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        const payload = { message: text };
        console.log(`[ByteX WS Lifecycle] SEND -> readyState: ${this.ws.readyState}, payload structure:`, { messageLength: text.length });
        this.ws.send(JSON.stringify(payload));
        return true;
      } catch (e) {
        console.warn('[ByteX WS] Send failed, attempting REST fallback:', e);
      }
    }

    // 2. REST Fallback if HTTP endpoint is available
    try {
      this.notifyEvent({ type: 'STATE_CHANGE', state: 'thinking' });

      const response = await fetch(`${this.apiUrl}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      if (response.ok) {
        const data = await response.json();
        this.setStatus('online');
        
        this.notifyEvent({
          type: 'ASSISTANT_MESSAGE',
          message: data.message,
          state: (data.state as OrbState) || 'speaking',
        });

        setTimeout(() => {
          this.notifyEvent({ type: 'STATE_CHANGE', state: 'idle' });
        }, 3000);

        return true;
      }
    } catch (e) {
      console.warn('[ByteX REST] Fallback failed:', e);
    }

    // 3. Backend Offline Alert
    this.setStatus('offline');
    this.notifyEvent({
      type: 'ERROR',
      message: 'ByteX Core is offline. Reconnecting backend...',
      state: 'error',
    });

    setTimeout(() => {
      this.notifyEvent({ type: 'STATE_CHANGE', state: 'idle' });
    }, 3000);

    return false;
  }

  // --- MEMORY MANAGEMENT REST API CALLS (FEATURE #39 PERSISTENT MEMORY 2.0) ---

  public async getMemories(category?: string, search?: string): Promise<MemoryItem[]> {
    try {
      const params = new URLSearchParams();
      if (category && category.toUpperCase() !== 'ALL') params.append('category', category);
      if (search && search.trim()) params.append('search', search.trim());
      const queryStr = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${this.apiUrl}/memory/all${queryStr}`);
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to fetch memories:', e);
    }
    return [];
  }

  public async addMemory(content: string, category: string = 'FACT', key?: string, value?: string): Promise<boolean> {
    try {
      const params = new URLSearchParams({ content, category });
      if (key) params.append('key', key);
      if (value) params.append('value', value);
      const response = await fetch(`${this.apiUrl}/memory/add?${params.toString()}`, {
        method: 'POST',
      });
      return response.ok;
    } catch (e) {
      console.warn('[ByteX API] Failed to add memory:', e);
      return false;
    }
  }

  public async updateMemory(id: string, updates: Partial<MemoryItem>): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/memory/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      return response.ok;
    } catch (e) {
      console.warn(`[ByteX API] Failed to update memory ${id}:`, e);
      return false;
    }
  }

  public async deleteMemory(id: string): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/memory/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (e) {
      console.warn(`[ByteX API] Failed to delete memory ${id}:`, e);
      return false;
    }
  }

  public async clearAllMemories(): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/memory/clear`, {
        method: 'POST',
      });
      return response.ok;
    } catch (e) {
      console.warn('[ByteX API] Failed to clear memories:', e);
      return false;
    }
  }

  public async getActiveProject(): Promise<any | null> {
    try {
      const response = await fetch(`${this.apiUrl}/memory/project/active`);
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to get active project:', e);
    }
    return null;
  }

  public async setActiveProject(projectName: string, workspacePath?: string, framework?: string): Promise<any | null> {
    try {
      const params = new URLSearchParams({ project_name: projectName });
      if (workspacePath) params.append('workspace_path', workspacePath);
      if (framework) params.append('framework', framework);
      const response = await fetch(`${this.apiUrl}/memory/project/active?${params.toString()}`, {
        method: 'POST',
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to set active project:', e);
    }
    return null;
  }

  public async clearActiveProject(): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/memory/project/active`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (e) {
      console.warn('[ByteX API] Failed to clear active project:', e);
      return false;
    }
  }

  // --- TASK HISTORY REST API CALLS (FEATURE #29) ---

  public async getTasks(params?: { status?: string; date?: string; keyword?: string; application?: string; limit?: number }): Promise<any[]> {
    try {
      const query = new URLSearchParams();
      if (params?.status) query.append('status', params.status);
      if (params?.date) query.append('date', params.date);
      if (params?.keyword) query.append('keyword', params.keyword);
      if (params?.application) query.append('application', params.application);
      if (params?.limit) query.append('limit', params.limit.toString());

      const url = `${this.apiUrl}/tasks${query.toString() ? `?${query.toString()}` : ''}`;
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        return data.tasks || [];
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to fetch tasks:', e);
    }
    return [];
  }

  public async getTaskById(taskId: string): Promise<any | null> {
    try {
      const response = await fetch(`${this.apiUrl}/tasks/${encodeURIComponent(taskId)}`);
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn(`[ByteX API] Failed to fetch task ${taskId}:`, e);
    }
    return null;
  }

  public async deleteTask(taskId: string): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/tasks/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (e) {
      console.warn(`[ByteX API] Failed to delete task ${taskId}:`, e);
      return false;
    }
  }

  public async clearTaskHistory(): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/tasks`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (e) {
      console.warn('[ByteX API] Failed to clear task history:', e);
      return false;
    }
  }

  // --- AUTOMATIONS REST API CALLS (FEATURE #30) ---

  public async getAutomations(enabledOnly: boolean = false): Promise<any[]> {
    try {
      const url = `${this.apiUrl}/automations${enabledOnly ? '?enabled_only=true' : ''}`;
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        return data.automations || [];
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to fetch automations:', e);
    }
    return [];
  }

  public async getAutomationById(id: string): Promise<any | null> {
    try {
      const response = await fetch(`${this.apiUrl}/automations/${encodeURIComponent(id)}`);
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn(`[ByteX API] Failed to fetch automation ${id}:`, e);
    }
    return null;
  }

  public async createOrUpdateAutomation(auto: any): Promise<any | null> {
    try {
      const response = await fetch(`${this.apiUrl}/automations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(auto),
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn('[ByteX API] Failed to save automation:', e);
    }
    return null;
  }

  public async deleteAutomation(id: string): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/automations/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      });
      return response.ok;
    } catch (e) {
      console.warn(`[ByteX API] Failed to delete automation ${id}:`, e);
      return false;
    }
  }

  public async runAutomation(id: string): Promise<any> {
    try {
      const response = await fetch(`${this.apiUrl}/automations/${encodeURIComponent(id)}/run`, {
        method: 'POST',
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn(`[ByteX API] Failed to run automation ${id}:`, e);
    }
    return { handled: false, message: 'Execution failed' };
  }

  public async setAutomationEnabled(id: string, enabled: boolean): Promise<boolean> {
    try {
      const endpoint = enabled ? 'enable' : 'disable';
      const response = await fetch(`${this.apiUrl}/automations/${encodeURIComponent(id)}/${endpoint}`, {
        method: 'POST',
      });
      return response.ok;
    } catch (e) {
      console.warn(`[ByteX API] Failed to set automation status ${id}:`, e);
      return false;
    }
  }
}

export const bytexApi = new ByteXApiService();
export default bytexApi;
