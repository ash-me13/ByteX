export type { OrbState, OrbStateConfig } from './orb';
export { ORB_STATE_CONFIGS } from './orb';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isMock?: boolean;
}

export type MemoryCategoryType =
  | 'USER_PREFERENCE'
  | 'PROJECT'
  | 'WORKFLOW'
  | 'APPLICATION_PREFERENCE'
  | 'ROUTINE'
  | 'FACT'
  | 'CONTEXT'
  | 'ALIAS'
  | 'TASK_CONTEXT'
  | 'USER_PROFILE'
  | 'GENERAL_FACT'
  | 'preference'
  | 'personal_info'
  | 'project'
  | 'instruction'
  | 'fact'
  | string;

export interface MemoryItem {
  id: string;
  category: MemoryCategoryType;
  content: string;
  key?: string | null;
  value?: string | null;
  source?: string;
  confidence?: number;
  confidence_level?: 'EXPLICIT' | 'HIGH' | 'MEDIUM' | 'LOW' | string;
  importance?: number;
  created_at: string;
  updated_at: string;
  last_used_at?: string | null;
  metadata?: Record<string, any> | null;
  expires_at?: string | null;
}

export interface ActiveProjectContext {
  project_name: string;
  workspace_path?: string | null;
  framework?: string | null;
  metadata?: Record<string, any> | null;
  updated_at: string;
}

export interface QuickActionItem {
  id: string;
  label: string;
  command: string;
  iconName: string;
}

export interface SettingsConfig {
  appearance: {
    theme: 'dark';
    glowIntensity: number;
  };
  voice: {
    enabled: boolean;
    voiceName: string;
  };
  assistant: {
    name: string;
    responseStyle: string;
  };
  security: {
    authMode: string;
  };
  ai: {
    provider: string;
    model: string;
  };
}

export interface TaskStepItem {
  step_id: number;
  skill: string;
  action: string;
  target?: string | null;
  status: string;
  started_at?: number;
  completed_at?: number;
  recovery_attempts?: number;
  recovery_details?: string | null;
  verification_status?: string;
  human_readable_result: string;
}

export interface TaskHistoryItem {
  task_id: string;
  command: string;
  status: 'SUCCESS' | 'COMPLETED' | 'PARTIAL_SUCCESS' | 'PARTIAL' | 'FAILED' | 'CANCELLED' | 'RECOVERED' | string;
  started_at?: number;
  completed_at?: number;
  duration_seconds: number;
  summary: string;
  recovery_occurred: boolean;
  created_at: string;
  timestamp: number;
  steps: TaskStepItem[];
}

export interface AutomationStepItem {
  step_id: number;
  skill: string;
  action: string;
  arguments?: Record<string, any>;
  condition?: string | null;
  description?: string | null;
}

export interface AutomationItem {
  automation_id: string;
  name: string;
  description: string;
  enabled: boolean;
  trigger: string;
  trigger_type: 'COMMAND' | 'TIME' | 'MANUAL' | string;
  steps: AutomationStepItem[];
  conditions?: string | null;
  requires_confirmation: boolean;
  created_at: string;
  updated_at: string;
  last_run_at?: number | null;
  run_count: number;
  success_count: number;
  failure_count: number;
}

export interface SystemNotification {
  id: string;
  eventType: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  timestamp: string;
  value?: number;
  threshold?: number;
}
