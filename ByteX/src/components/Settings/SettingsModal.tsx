import { debugLog } from '../../lib/debug';
import React, { useState, useEffect } from 'react';
import { X, Sliders, Database, Trash2, Plus, BrainCircuit, Volume2, Mic, Sparkles, Languages, Play, Search, Lightbulb, History, ChevronDown, ChevronUp, Clock, Zap, Smartphone, Check, AlertCircle, Edit3 } from 'lucide-react';
import QRCode from 'qrcode';
import bytexApi from '../../services/bytexApi';
import ttsService from '../../services/ttsService';
import voiceSettingsService from '../../services/voiceSettingsService';
import wakeWordService from '../../services/wakeWordService';
import phonePairingService from '../../services/phonePairingService';
import type { TrustedDeviceInfo, PairingSessionResponse } from '../../services/phonePairingService';
import type { VoiceSettings } from '../../services/voiceSettingsService';
import type { MemoryItem, TaskHistoryItem, AutomationItem } from '../../types';
import './SettingsModal.css';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabType = 'voice' | 'phone' | 'automations' | 'history' | 'memory' | 'suggestions' | 'appearance' | 'assistant' | 'security' | 'ai';

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState<TabType>('voice');
  
  // Voice Settings State
  const [voiceSettings, setVoiceSettings] = useState<VoiceSettings>(voiceSettingsService.getSettings());
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);

  // Memory Settings State (Feature #39 Persistent Memory 2.0)
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [newMemoryContent, setNewMemoryContent] = useState('');
  const [newMemoryCategory, setNewMemoryCategory] = useState<string>('USER_PREFERENCE');
  const [selectedCategoryFilter, setSelectedCategoryFilter] = useState<string>('ALL');
  const [memorySearchQuery, setMemorySearchQuery] = useState('');
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [isLearningEnabled, setIsLearningEnabled] = useState(true);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState<string>('');
  const [editingCategory, setEditingCategory] = useState<string>('FACT');
  const [activeProjectInfo, setActiveProjectInfo] = useState<any>(null);

  // Task History State (Feature #29)
  const [tasks, setTasks] = useState<TaskHistoryItem[]>([]);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskStatusFilter, setTaskStatusFilter] = useState<string>('ALL');
  const [isLoadingTasks, setIsLoadingTasks] = useState(false);
  const [expandedTaskIds, setExpandedTaskIds] = useState<Set<string>>(new Set());

  // Automations State (Feature #30)
  const [automations, setAutomations] = useState<AutomationItem[]>([]);
  const [autoSearchQuery, setAutoSearchQuery] = useState('');
  const [autoFilter, setAutoFilter] = useState<string>('ALL');
  const [isLoadingAutomations, setIsLoadingAutomations] = useState(false);
  const [expandedAutoIds, setExpandedAutoIds] = useState<Set<string>>(new Set());
  const [newAutoPrompt, setNewAutoPrompt] = useState('');

  // Suggestions Settings State
  const [isSuggestionsEnabled, setIsSuggestionsEnabled] = useState(true);
  const [suggestionFrequency, setSuggestionFrequency] = useState<'minimal' | 'balanced' | 'frequent'>('balanced');

  // Appearance Settings State
  const [ambientAnimations, setAmbientAnimations] = useState<boolean>(() => {
    return localStorage.getItem('bytex_ambient_animations') !== 'false';
  });

  const handleToggleAmbientAnimations = (enabled: boolean) => {
    setAmbientAnimations(enabled);
    localStorage.setItem('bytex_ambient_animations', enabled ? 'true' : 'false');
    window.dispatchEvent(new CustomEvent('bytex_ambient_animations_change', { detail: { enabled } }));
  };

  // Phone Integration State (Feature #38.1)
  const [trustedDevices, setTrustedDevices] = useState<TrustedDeviceInfo[]>([]);
  const [pairingSession, setPairingSession] = useState<PairingSessionResponse | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [pairingCountdown, setPairingCountdown] = useState<number>(60);
  const [pendingDeviceApproval, setPendingDeviceApproval] = useState<any>(null);
  const [isPairingLoading, setIsPairingLoading] = useState(false);
  const [pairingError, setPairingError] = useState<string | null>(null);

  const fetchTrustedDevices = async () => {
    const devices = await phonePairingService.getTrustedDevices();
    setTrustedDevices(devices);
  };

  const handleStartPairing = async () => {
    setIsPairingLoading(true);
    setPairingError(null);
    setPendingDeviceApproval(null);
    try {
      const session = await phonePairingService.createPairingSession();
      setPairingSession(session);
      setPairingCountdown(session.expires_in_seconds || 60);
      const dataUrl = await QRCode.toDataURL(JSON.stringify(session.qr_payload), {
        width: 220,
        margin: 1,
        color: { dark: '#00f0ff', light: '#090d16' },
      });
      setQrDataUrl(dataUrl);
    } catch (e: any) {
      setPairingError(e.message || 'Failed to generate pairing QR code');
    } finally {
      setIsPairingLoading(false);
    }
  };

  const handleCancelPairing = () => {
    if (pairingSession) {
      phonePairingService.cancelPairingSession(pairingSession.session_id);
    }
    setPairingSession(null);
    setQrDataUrl('');
    setPendingDeviceApproval(null);
  };

  const handleApproveDevice = async (approved: boolean) => {
    if (!pairingSession) return;
    try {
      await phonePairingService.approvePairing(pairingSession.session_id, approved);
      setPairingSession(null);
      setQrDataUrl('');
      setPendingDeviceApproval(null);
      await fetchTrustedDevices();
    } catch (e: any) {
      setPairingError(e.message || 'Approval failed');
    }
  };

  const handleRemoveDevice = async (deviceId: string) => {
    if (window.confirm('Are you sure you want to remove this paired device? You will need to scan a new QR code to reconnect.')) {
      await phonePairingService.revokeDevice(deviceId);
      await fetchTrustedDevices();
    }
  };

  // Polling for pairing status & countdown & live devices
  useEffect(() => {
    let timer: any;
    let pollInterval: any;

    if (isOpen && activeTab === 'phone') {
      if (pairingSession) {
        timer = setInterval(() => {
          setPairingCountdown((prev) => {
            if (prev <= 1) {
              clearInterval(timer);
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      }

      pollInterval = setInterval(async () => {
        try {
          const sid = pairingSession?.session_id || '';
          const status = await phonePairingService.getPairingStatus(sid);
          if (status.has_active_session && status.status === 'PENDING_APPROVAL' && status.pending_device) {
            setPendingDeviceApproval(status.pending_device);
            if (status.session_id && (!pairingSession || pairingSession.session_id !== status.session_id)) {
              setPairingSession((prev: any) => ({
                ...(prev || {}),
                session_id: status.session_id!,
                expires_in_seconds: status.expires_in_seconds || 60,
              }));
            }
          } else if (status.status === 'APPROVED') {
            setPairingSession(null);
            setQrDataUrl('');
            setPendingDeviceApproval(null);
            fetchTrustedDevices();
          } else if (status.status === 'EXPIRED') {
            setPairingCountdown(0);
          }
          // Periodic refresh of trusted devices list
          fetchTrustedDevices();
        } catch (e) {
          console.warn('[PhoneSettings] Polling error:', e);
        }
      }, 1000);
    }

    return () => {
      if (timer) clearInterval(timer);
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [isOpen, activeTab, pairingSession]);

  // Fetch data on open
  useEffect(() => {
    if (isOpen) {
      if (ttsService.isSupported()) {
        const voices = ttsService.getAvailableVoices();
        setAvailableVoices(voices);
        if ('speechSynthesis' in window) {
          window.speechSynthesis.onvoiceschanged = () => {
            setAvailableVoices(window.speechSynthesis.getVoices());
          };
        }
      }
      if (activeTab === 'phone') {
        fetchTrustedDevices();
      }
      if (activeTab === 'memory') {
        fetchMemories();
      }
      if (activeTab === 'history') {
        fetchTasks();
      }
      if (activeTab === 'automations') {
        fetchAutomations();
      }
    }
  }, [isOpen, activeTab]);

  const handleUpdateVoiceSettings = (updates: Partial<VoiceSettings>) => {
    const updated = voiceSettingsService.save(updates);
    setVoiceSettings(updated);
  };

  const handleTestVoice = () => {
    ttsService.speak("Hello, I'm ByteX.", {
      rate: voiceSettings.rate,
      volume: voiceSettings.volume,
      pitch: voiceSettings.pitch || 1.0,
      language: voiceSettings.language,
      voiceURI: voiceSettings.voiceURI,
      speakOnlyHighlights: false,
    });
  };

  const fetchTasks = async () => {
    setIsLoadingTasks(true);
    const data = await bytexApi.getTasks({
      status: taskStatusFilter === 'ALL' ? undefined : taskStatusFilter,
      date: undefined,
      keyword: taskSearchQuery.trim() || undefined,
      limit: 50,
    });
    setTasks(data);
    setIsLoadingTasks(false);
  };

  const fetchAutomations = async () => {
    setIsLoadingAutomations(true);
    const data = await bytexApi.getAutomations();
    setAutomations(data);
    setIsLoadingAutomations(false);
  };

  const handleToggleAutomation = async (auto: AutomationItem) => {
    const ok = await bytexApi.setAutomationEnabled(auto.automation_id, !auto.enabled);
    if (ok) {
      setAutomations((prev) =>
        prev.map((a) => (a.automation_id === auto.automation_id ? { ...a, enabled: !a.enabled } : a))
      );
    }
  };

  const handleRunAutomation = async (auto: AutomationItem) => {
    await bytexApi.runAutomation(auto.automation_id);
    await fetchAutomations();
  };

  const handleDeleteAutomation = async (auto: AutomationItem) => {
    if (window.confirm(`Permanently delete automation '${auto.name}'?`)) {
      const ok = await bytexApi.deleteAutomation(auto.automation_id);
      if (ok) {
        setAutomations((prev) => prev.filter((a) => a.automation_id !== auto.automation_id));
      }
    }
  };

  const fetchMemories = async () => {
    setIsLoadingMemories(true);
    try {
      const data = await bytexApi.getMemories();
      setMemories(data);
      const proj = await bytexApi.getActiveProject();
      setActiveProjectInfo(proj);
    } catch (e) {
      console.warn('Failed to fetch memories:', e);
    } finally {
      setIsLoadingMemories(false);
    }
  };

  const handleAddMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMemoryContent.trim()) return;

    const ok = await bytexApi.addMemory(newMemoryContent.trim(), newMemoryCategory);
    if (ok) {
      setNewMemoryContent('');
      await fetchMemories();
    }
  };

  const handleStartEdit = (item: MemoryItem) => {
    setEditingMemoryId(item.id);
    setEditingContent(item.content);
    setEditingCategory(item.category || 'FACT');
  };

  const handleSaveEdit = async (id: string) => {
    if (!editingContent.trim()) return;
    const ok = await bytexApi.updateMemory(id, { content: editingContent.trim(), category: editingCategory });
    if (ok) {
      setEditingMemoryId(null);
      await fetchMemories();
    }
  };

  const handleCancelEdit = () => {
    setEditingMemoryId(null);
  };

  const handleDeleteMemory = async (id: string) => {
    const ok = await bytexApi.deleteMemory(id);
    if (ok) {
      setMemories((prev) => prev.filter((m) => m.id !== id));
    }
  };

  const handleCreateAutomationSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAutoPrompt.trim()) return;
    try {
      await fetch('http://127.0.0.1:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: newAutoPrompt.trim() }),
      });
      setNewAutoPrompt('');
      await fetchAutomations();
    } catch (err) {
      console.warn('Failed to submit automation prompt:', err);
    }
  };

  const toggleAutoExpanded = (autoId: string) => {
    setExpandedAutoIds((prev) => {
      const next = new Set(prev);
      if (next.has(autoId)) {
        next.delete(autoId);
      } else {
        next.add(autoId);
      }
      return next;
    });
  };

  const handleClearAllMemories = async () => {
    if (window.confirm('This will permanently delete all saved ByteX memories. Continue?')) {
      const ok = await bytexApi.clearAllMemories();
      if (ok) {
        setMemories([]);
      }
    }
  };

  const handleClearAllTasks = async () => {
    if (window.confirm('This will permanently delete your ByteX task history. Long-term memories will remain untouched. Continue?')) {
      const ok = await bytexApi.clearTaskHistory();
      if (ok) {
        setTasks([]);
      }
    }
  };

  const toggleTaskExpanded = (taskId: string) => {
    setExpandedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) {
        next.delete(taskId);
      } else {
        next.add(taskId);
      }
      return next;
    });
  };

  const handleUpdateSuggestionSettings = async (enabled: boolean, freq: 'minimal' | 'balanced' | 'frequent') => {
    setIsSuggestionsEnabled(enabled);
    setSuggestionFrequency(freq);
    try {
      await fetch(`http://127.0.0.1:8000/api/suggestions/settings?enabled=${enabled}&frequency=${freq}`, { method: 'POST' });
    } catch (e) {
      console.warn('Failed to update suggestion settings:', e);
    }
  };

  const filteredMemories = memories.filter((m) => {
    const catMatch = selectedCategoryFilter === 'ALL' || m.category.toUpperCase() === selectedCategoryFilter.toUpperCase() || m.category.toLowerCase().includes(selectedCategoryFilter.toLowerCase());
    const searchMatch = !memorySearchQuery.trim() || m.content.toLowerCase().includes(memorySearchQuery.toLowerCase()) || (m.key && m.key.toLowerCase().includes(memorySearchQuery.toLowerCase()));
    return catMatch && searchMatch;
  });

  const filteredTasks = tasks.filter((t) => {
    const stMatch = taskStatusFilter === 'ALL' || t.status.toUpperCase() === taskStatusFilter.toUpperCase() || (taskStatusFilter === 'RECOVERED' && t.recovery_occurred);
    const searchMatch = !taskSearchQuery.trim() || t.command.toLowerCase().includes(taskSearchQuery.toLowerCase()) || t.summary.toLowerCase().includes(taskSearchQuery.toLowerCase());
    return stMatch && searchMatch;
  });

  const filteredAutomations = automations.filter((a) => {
    const statusMatch = autoFilter === 'ALL' || (autoFilter === 'ENABLED' && a.enabled) || (autoFilter === 'DISABLED' && !a.enabled);
    const searchMatch = !autoSearchQuery.trim() || a.name.toLowerCase().includes(autoSearchQuery.toLowerCase()) || a.trigger.toLowerCase().includes(autoSearchQuery.toLowerCase()) || a.description.toLowerCase().includes(autoSearchQuery.toLowerCase());
    return statusMatch && searchMatch;
  });

  if (!isOpen) return null;

  return (
    <div className="bytex-modal-backdrop" onClick={onClose}>
      <div className="bytex-modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="bytex-modal-header">
          <h2 className="bytex-modal-title">
            <Sliders size={20} />
            <span>ByteX Settings</span>
          </h2>
          <button className="bytex-modal-close-btn" onClick={onClose} title="Close (Esc)">
            <X size={18} />
          </button>
        </div>

        <div className="bytex-modal-tabs">
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'voice' ? 'active' : ''}`}
            onClick={() => setActiveTab('voice')}
          >
            <Volume2 size={14} style={{ marginRight: 6 }} />
            Voice
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'phone' ? 'active' : ''}`}
            onClick={() => { setActiveTab('phone'); fetchTrustedDevices(); }}
          >
            <Smartphone size={14} style={{ marginRight: 6 }} />
            Phone Integration
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'automations' ? 'active' : ''}`}
            onClick={() => { setActiveTab('automations'); fetchAutomations(); }}
          >
            <Zap size={14} style={{ marginRight: 6 }} />
            Automations ({automations.length})
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => { setActiveTab('history'); fetchTasks(); }}
          >
            <History size={14} style={{ marginRight: 6 }} />
            History ({tasks.length})
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'memory' ? 'active' : ''}`}
            onClick={() => { setActiveTab('memory'); fetchMemories(); }}
          >
            <BrainCircuit size={14} style={{ marginRight: 6 }} />
            Memory ({memories.length})
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'suggestions' ? 'active' : ''}`}
            onClick={() => setActiveTab('suggestions')}
          >
            <Lightbulb size={14} style={{ marginRight: 6 }} />
            Suggestions
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'appearance' ? 'active' : ''}`}
            onClick={() => setActiveTab('appearance')}
          >
            Appearance
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'assistant' ? 'active' : ''}`}
            onClick={() => setActiveTab('assistant')}
          >
            Assistant
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'security' ? 'active' : ''}`}
            onClick={() => setActiveTab('security')}
          >
            Security
          </button>
          <button
            className={`bytex-modal-tab-btn ${activeTab === 'ai' ? 'active' : ''}`}
            onClick={() => setActiveTab('ai')}
          >
            AI Engine
          </button>
        </div>

        <div className="bytex-modal-body">
          {/* PHONE INTEGRATION TAB (FEATURE #38.1) */}
          {activeTab === 'phone' && (
            <div className="bytex-memory-section">
              <div className="bytex-memory-header">
                <div>
                  <h3 className="bytex-memory-title">
                    <Smartphone size={16} />
                    <span>SECURE ANDROID PHONE INTEGRATION</span>
                  </h3>
                  <p className="bytex-memory-subtitle">
                    Pair your Android device with ByteX over local Wi-Fi using end-to-end authenticated QR pairing
                  </p>
                </div>
                {!pairingSession && (
                  <button
                    type="button"
                    className="bytex-memory-add-btn"
                    onClick={handleStartPairing}
                    disabled={isPairingLoading}
                  >
                    <Smartphone size={14} />
                    <span>{isPairingLoading ? 'Generating...' : 'Pair Android Phone'}</span>
                  </button>
                )}
              </div>

              {pairingError && (
                <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', padding: '8px 12px', borderRadius: 6, color: '#f87171', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                  <AlertCircle size={14} />
                  <span>{pairingError}</span>
                </div>
              )}

              {/* ACTIVE PAIRING SESSION CARD */}
              {pairingSession && (
                <div className="bytex-memory-card" style={{ flexDirection: 'column', alignItems: 'center', padding: '24px', background: 'rgba(0, 240, 255, 0.04)', border: '1px solid rgba(0, 240, 255, 0.25)' }}>
                  <h4 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: '#00f0ff', fontWeight: 600 }}>
                    Scan QR with ByteX Android App
                  </h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: '0 0 16px 0', textAlign: 'center' }}>
                    Open ByteX on your phone, tap <b>Scan QR Code</b>, and point your camera at this screen.
                  </p>

                  {/* QR Image Display */}
                  {qrDataUrl && pairingCountdown > 0 ? (
                    <div style={{ background: '#090d16', padding: '12px', borderRadius: '12px', border: '1px solid rgba(0, 240, 255, 0.3)', boxShadow: '0 0 20px rgba(0, 240, 255, 0.15)' }}>
                      <img src={qrDataUrl} alt="Pairing QR Code" style={{ display: 'block', width: '220px', height: '220px', borderRadius: '8px' }} />
                    </div>
                  ) : (
                    <div style={{ padding: '32px', textAlign: 'center', color: '#f87171' }}>
                      <AlertCircle size={32} style={{ margin: '0 auto 8px auto' }} />
                      <div style={{ fontWeight: 600 }}>Pairing code expired.</div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>For your security, pairing codes expire in 60 seconds.</div>
                    </div>
                  )}

                  {/* Countdown Timer */}
                  <div style={{ margin: '16px 0 8px 0', fontSize: '0.85rem', color: pairingCountdown > 0 ? '#38bdf8' : '#f87171' }}>
                    {pairingCountdown > 0 ? (
                      <span>⏱️ Expires in: <b>{pairingCountdown}s</b></span>
                    ) : (
                      <span>Code expired</span>
                    )}
                  </div>

                  {/* Pending Approval Dialog */}
                  {pendingDeviceApproval && (
                    <div style={{ background: 'rgba(0, 240, 255, 0.1)', border: '1px solid #00f0ff', padding: '16px', borderRadius: '8px', width: '100%', maxWidth: '400px', marginTop: '12px', textAlign: 'center' }}>
                      <div style={{ fontWeight: 600, color: '#f8fafc', marginBottom: '6px' }}>
                        📱 Android Phone Requesting Connection
                      </div>
                      <div style={{ fontSize: '13px', color: '#00f0ff', marginBottom: '12px' }}>
                        <b>{pendingDeviceApproval.device_name}</b> ({pendingDeviceApproval.platform})
                      </div>
                      <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
                        <button
                          type="button"
                          className="bytex-memory-add-btn"
                          style={{ background: '#00f0ff', color: '#090d16', border: 'none', fontWeight: 600 }}
                          onClick={() => handleApproveDevice(true)}
                        >
                          <Check size={14} />
                          Approve
                        </button>
                        <button
                          type="button"
                          className="bytex-btn bytex-btn-secondary"
                          style={{ fontSize: '12px', padding: '6px 14px' }}
                          onClick={() => handleApproveDevice(false)}
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
                    {pairingCountdown === 0 ? (
                      <button
                        type="button"
                        className="bytex-memory-add-btn"
                        onClick={handleStartPairing}
                      >
                        Generate New Code
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="bytex-btn bytex-btn-secondary"
                        onClick={handleCancelPairing}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* TRUSTED DEVICES SECTION */}
              <div style={{ marginTop: '24px' }}>
                <h4 style={{ fontSize: '0.9rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px' }}>
                  Trusted Paired Devices ({trustedDevices.length})
                </h4>

                {trustedDevices.length === 0 ? (
                  <div className="bytex-memory-empty">
                    <Smartphone size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
                    <p>No Android devices paired yet.</p>
                    <p style={{ fontSize: '0.78rem', color: '#64748b' }}>
                      Click "Pair Android Phone" above to connect your phone over local Wi-Fi.
                    </p>
                  </div>
                ) : (
                  <div className="bytex-memory-list">
                    {trustedDevices.map((dev) => (
                      <div key={dev.device_id} className="bytex-memory-card" style={{ justifyContent: 'space-between' }}>
                        <div className="bytex-memory-card-main">
                          <div className="bytex-memory-badge-row">
                            <span className={`bytex-memory-badge ${dev.is_connected ? 'badge-success' : 'badge-failed'}`}>
                              {dev.is_connected ? '🟢 CONNECTED' : '🔴 DISCONNECTED'}
                            </span>
                            <span className="bytex-memory-date">
                              Paired on {new Date(dev.paired_at * 1000).toLocaleDateString()}
                            </span>
                          </div>
                          <h4 style={{ margin: '0.35rem 0 0.2rem 0', fontSize: '0.92rem', color: '#f8fafc', fontWeight: 600 }}>
                            📱 {dev.device_name}
                          </h4>
                          <p className="bytex-memory-content" style={{ color: '#94a3b8', fontSize: '0.8rem' }}>
                            Platform: {dev.platform} • Permissions: {dev.permissions.join(', ')}
                          </p>
                        </div>

                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            type="button"
                            className="bytex-memory-del-btn"
                            title="Remove Device (Revoke Access)"
                            onClick={() => handleRemoveDevice(dev.device_id)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* AUTOMATIONS TAB (FEATURE #30) */}
          {activeTab === 'automations' && (
            <div className="bytex-memory-section">
              <div className="bytex-memory-header">
                <div>
                  <h3 className="bytex-memory-title">
                    <Zap size={16} />
                    <span>BYTE X NATURAL-LANGUAGE AUTOMATIONS</span>
                  </h3>
                  <p className="bytex-memory-subtitle">
                    {automations.length} structured automation workflows (Agent Pipeline Driven)
                  </p>
                </div>
              </div>

              {/* Natural Creation Prompt Input */}
              <form className="bytex-memory-form" onSubmit={handleCreateAutomationSubmit}>
                <input
                  type="text"
                  className="bytex-memory-input"
                  placeholder="Describe what to automate (e.g., 'Whenever I say start coding, open VS Code and start backend')..."
                  value={newAutoPrompt}
                  onChange={(e) => setNewAutoPrompt(e.target.value)}
                />
                <button type="submit" className="bytex-memory-add-btn">
                  <Plus size={16} />
                  Create
                </button>
              </form>

              {/* Filter & Search Bar */}
              <div className="bytex-memory-filter-bar">
                <div className="bytex-memory-search-box">
                  <Search size={14} className="bytex-memory-search-icon" />
                  <input
                    type="text"
                    placeholder="Search automations by name or trigger..."
                    value={autoSearchQuery}
                    onChange={(e) => setAutoSearchQuery(e.target.value)}
                    className="bytex-memory-filter-input"
                  />
                </div>

                <div className="bytex-memory-cat-chips">
                  {['ALL', 'ENABLED', 'DISABLED'].map((f) => (
                    <button
                      key={f}
                      type="button"
                      className={`bytex-cat-chip ${autoFilter === f ? 'active' : ''}`}
                      onClick={() => setAutoFilter(f)}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              {isLoadingAutomations ? (
                <div className="bytex-memory-empty">Loading automations...</div>
              ) : filteredAutomations.length === 0 ? (
                <div className="bytex-memory-empty">
                  {automations.length === 0
                    ? "No automations created yet. Try: 'Create an automation called ByteX Dev that starts backend and frontend.'"
                    : 'No automations match your search filter.'}
                </div>
              ) : (
                <div className="bytex-memory-list">
                  {filteredAutomations.map((a) => {
                    const isExpanded = expandedAutoIds.has(a.automation_id);
                    return (
                      <div key={a.automation_id} className="bytex-memory-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div className="bytex-memory-card-main" style={{ width: '100%' }}>
                            <div className="bytex-memory-badge-row">
                              <span className={`bytex-memory-badge ${a.enabled ? 'badge-success' : 'badge-failed'}`}>
                                {a.enabled ? '● Enabled' : '○ Disabled'}
                              </span>
                              <span className="bytex-memory-key-tag">
                                Trigger: &quot;{a.trigger}&quot; ({a.trigger_type})
                              </span>
                              {a.run_count > 0 && (
                                <span className="bytex-memory-date">
                                  Runs: {a.run_count} (✓ {a.success_count})
                                </span>
                              )}
                            </div>
                            <h4 style={{ margin: '0.35rem 0 0.2rem 0', fontSize: '0.9rem', color: '#f8fafc', fontWeight: 600 }}>
                              {a.name}
                            </h4>
                            <p className="bytex-memory-content" style={{ color: '#94a3b8', fontSize: '0.8rem' }}>
                              {a.description}
                            </p>
                          </div>

                          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginLeft: '8px' }}>
                            <button
                              type="button"
                              onClick={() => handleRunAutomation(a)}
                              style={{
                                background: 'rgba(0,240,255,0.15)',
                                border: '1px solid rgba(0,240,255,0.3)',
                                color: '#00f0ff',
                                padding: '0.3rem 0.5rem',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '3px',
                                fontSize: '0.72rem',
                                fontWeight: 600
                              }}
                              title="Run Automation Now"
                            >
                              <Play size={12} />
                              Run
                            </button>

                            <button
                              type="button"
                              onClick={() => handleToggleAutomation(a)}
                              style={{
                                background: 'rgba(255,255,255,0.06)',
                                border: '1px solid rgba(255,255,255,0.12)',
                                color: a.enabled ? '#4ade80' : '#94a3b8',
                                padding: '0.3rem 0.5rem',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontSize: '0.72rem'
                              }}
                            >
                              {a.enabled ? 'Disable' : 'Enable'}
                            </button>

                            <button
                              type="button"
                              className="bytex-memory-delete-btn"
                              onClick={() => handleDeleteAutomation(a)}
                              title="Delete Automation"
                            >
                              <Trash2 size={13} />
                            </button>

                            {a.steps && a.steps.length > 0 && (
                              <button
                                type="button"
                                onClick={() => toggleAutoExpanded(a.automation_id)}
                                style={{
                                  background: 'rgba(255,255,255,0.04)',
                                  border: '1px solid rgba(255,255,255,0.08)',
                                  color: '#94a3b8',
                                  padding: '0.3rem 0.4rem',
                                  borderRadius: '6px',
                                  cursor: 'pointer'
                                }}
                              >
                                {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Steps Accordion */}
                        {isExpanded && a.steps && (
                          <div style={{
                            marginTop: '0.6rem',
                            paddingTop: '0.6rem',
                            borderTop: '1px solid rgba(255,255,255,0.08)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.4rem'
                          }}>
                            {a.steps.map((s) => (
                              <div key={s.step_id} style={{
                                background: 'rgba(0,0,0,0.25)',
                                padding: '0.4rem 0.6rem',
                                borderRadius: '6px',
                                fontSize: '0.75rem',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center'
                              }}>
                                <div>
                                  <span style={{ color: '#00f0ff', fontWeight: 600 }}>Step {s.step_id} ({s.skill}):</span>{' '}
                                  <span style={{ color: '#cbd5e1' }}>{s.description || s.action}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TASK HISTORY TAB (FEATURE #29) */}
          {activeTab === 'history' && (
            <div className="bytex-memory-section">
              <div className="bytex-memory-header">
                <div>
                  <h3 className="bytex-memory-title">
                    <History size={16} />
                    <span>BYTE X TASK HISTORY</span>
                  </h3>
                  <p className="bytex-memory-subtitle">
                    {tasks.length} recorded tasks (Persistent SQLite Execution Log)
                  </p>
                </div>

                {tasks.length > 0 && (
                  <button className="bytex-memory-clear-btn" onClick={handleClearAllTasks}>
                    <Trash2 size={14} />
                    Clear History
                  </button>
                )}
              </div>

              {/* Filter & Search Bar */}
              <div className="bytex-memory-filter-bar">
                <div className="bytex-memory-search-box">
                  <Search size={14} className="bytex-memory-search-icon" />
                  <input
                    type="text"
                    placeholder="Search tasks by command, action, or target..."
                    value={taskSearchQuery}
                    onChange={(e) => setTaskSearchQuery(e.target.value)}
                    className="bytex-memory-filter-input"
                  />
                </div>

                <div className="bytex-memory-cat-chips">
                  {['ALL', 'SUCCESS', 'RECOVERED', 'FAILED', 'PARTIAL'].map((st) => (
                    <button
                      key={st}
                      type="button"
                      className={`bytex-cat-chip ${taskStatusFilter === st ? 'active' : ''}`}
                      onClick={() => setTaskStatusFilter(st)}
                    >
                      {st}
                    </button>
                  ))}
                </div>
              </div>

              {isLoadingTasks ? (
                <div className="bytex-memory-empty">Loading task history...</div>
              ) : filteredTasks.length === 0 ? (
                <div className="bytex-memory-empty">
                  {tasks.length === 0
                    ? 'No task history found. Ask ByteX to perform an action to start recording.'
                    : 'No tasks match your current filter.'}
                </div>
              ) : (
                <div className="bytex-memory-list">
                  {filteredTasks.map((t) => {
                    const isExpanded = expandedTaskIds.has(t.task_id);
                    const isSuccess = t.status.toUpperCase() === 'SUCCESS' || t.status.toUpperCase() === 'COMPLETED';
                    const isRecovered = t.status.toUpperCase() === 'RECOVERED' || t.recovery_occurred;
                    const isFailed = t.status.toUpperCase() === 'FAILED';

                    const badgeClass = isRecovered ? 'badge-recovered' : isSuccess ? 'badge-success' : isFailed ? 'badge-failed' : 'badge-partial';

                    return (
                      <div key={t.task_id} className="bytex-memory-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div className="bytex-memory-card-main" style={{ width: '100%' }}>
                            <div className="bytex-memory-badge-row">
                              <span className={`bytex-memory-badge ${badgeClass}`}>
                                {isRecovered ? '↻ RECOVERED' : isSuccess ? '✓ SUCCESS' : isFailed ? '✕ FAILED' : '◷ PARTIAL'}
                              </span>
                              <span className="bytex-memory-date">
                                <Clock size={11} style={{ marginRight: 3, verticalAlign: 'middle' }} />
                                {new Date(t.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {new Date(t.timestamp * 1000).toLocaleDateString()}
                              </span>
                              {t.duration_seconds > 0 && (
                                <span className="bytex-memory-key-tag">
                                  {t.duration_seconds}s
                                </span>
                              )}
                            </div>
                            <h4 style={{ margin: '0.35rem 0 0.2rem 0', fontSize: '0.88rem', color: '#f8fafc', fontWeight: 600 }}>
                              {t.command}
                            </h4>
                            <p className="bytex-memory-content" style={{ color: '#94a3b8', fontSize: '0.8rem' }}>
                              {t.summary}
                            </p>
                          </div>

                          {t.steps && t.steps.length > 0 && (
                            <button
                              type="button"
                              onClick={() => toggleTaskExpanded(t.task_id)}
                              style={{
                                background: 'rgba(255,255,255,0.06)',
                                border: '1px solid rgba(255,255,255,0.1)',
                                color: '#94a3b8',
                                padding: '0.3rem 0.5rem',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                fontSize: '0.72rem',
                                marginLeft: '8px'
                              }}
                            >
                              <span>{t.steps.length} {t.steps.length === 1 ? 'step' : 'steps'}</span>
                              {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            </button>
                          )}
                        </div>

                        {/* Step Details Accordion */}
                        {isExpanded && t.steps && (
                          <div style={{
                            marginTop: '0.6rem',
                            paddingTop: '0.6rem',
                            borderTop: '1px solid rgba(255,255,255,0.08)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.4rem'
                          }}>
                            {t.steps.map((s) => (
                              <div key={s.step_id} style={{
                                background: 'rgba(0,0,0,0.25)',
                                padding: '0.4rem 0.6rem',
                                borderRadius: '6px',
                                fontSize: '0.75rem',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center'
                              }}>
                                <div>
                                  <span style={{ color: '#00f0ff', fontWeight: 600 }}>Step {s.step_id} ({s.action}):</span>{' '}
                                  <span style={{ color: '#cbd5e1' }}>{s.human_readable_result || s.target || 'Executed'}</span>
                                </div>
                                <span style={{
                                  fontSize: '0.68rem',
                                  color: s.status === 'RECOVERED' ? '#38bdf8' : (s.status.includes('SUCCESS') ? '#4ade80' : '#f87171')
                                }}>
                                  {s.status}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* VOICE SETTINGS TAB */}
          {activeTab === 'voice' && (
            <div className="bytex-voice-settings-group">
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Speech Output (TTS)</span>
                  <span className="bytex-setting-desc">Read ByteX AI responses aloud</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={voiceSettings.enabled}
                    onChange={(e) => handleUpdateVoiceSettings({ enabled: e.target.checked })}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">
                    <Languages size={14} style={{ marginRight: 4 }} />
                    Language
                  </span>
                  <span className="bytex-setting-desc">Speech recognition & synthesis locale</span>
                </div>
                <div className="bytex-setting-control">
                  <select
                    value={voiceSettings.language}
                    onChange={(e: any) => handleUpdateVoiceSettings({ language: e.target.value })}
                  >
                    <option value="auto">Auto (Auto-Detect English / Hindi / Hinglish)</option>
                    <option value="en-US">English (en-US)</option>
                    <option value="hi-IN">Hindi (hi-IN)</option>
                    <option value="hi-IN-hinglish">Hinglish (Hindi + English)</option>
                  </select>
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Voice Model</span>
                  <span className="bytex-setting-desc">Neural & Natural system voice selection</span>
                </div>
                <div className="bytex-setting-control" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <select
                    value={voiceSettings.voiceURI}
                    onChange={(e) => handleUpdateVoiceSettings({ voiceURI: e.target.value })}
                  >
                    <option value="">✨ Automatic Best Natural Voice</option>
                    {availableVoices.map((v) => {
                      const isNatural = v.name.toLowerCase().includes('natural') || v.name.toLowerCase().includes('neural');
                      const isOnline = v.name.toLowerCase().includes('online') || v.name.toLowerCase().includes('google');
                      const tag = [isNatural ? '✨ Natural' : isOnline ? '🌐 Online' : '', v.localService ? 'Local' : 'Network'].filter(Boolean).join(', ');
                      return (
                        <option key={v.voiceURI} value={v.voiceURI}>
                          {v.name} {tag ? `[${tag}]` : ''} ({v.lang})
                        </option>
                      );
                    })}
                  </select>
                  <button
                    type="button"
                    className="bytex-test-voice-btn"
                    onClick={handleTestVoice}
                    title="Test Voice Sample"
                  >
                    <Play size={14} />
                    Test
                  </button>
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Voice Personality</span>
                  <span className="bytex-setting-desc">Assistant communication and phrasing style</span>
                </div>
                <div className="bytex-setting-control">
                  <select
                    value={voiceSettings.personality || 'friendly'}
                    onChange={(e: any) => handleUpdateVoiceSettings({ personality: e.target.value })}
                  >
                    <option value="friendly">Friendly (Default)</option>
                    <option value="professional">Professional</option>
                    <option value="casual">Casual</option>
                    <option value="concise">Concise</option>
                    <option value="custom">Custom Style</option>
                  </select>
                </div>
              </div>

              {voiceSettings.personality === 'custom' && (
                <div className="bytex-setting-row" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
                  <div className="bytex-setting-info">
                    <span className="bytex-setting-label">Custom Personality Style</span>
                    <span className="bytex-setting-desc">Describe response tone (Presentation only, max 300 chars)</span>
                  </div>
                  <input
                    type="text"
                    className="bytex-input"
                    style={{ width: '100%', fontSize: '12px' }}
                    placeholder="e.g., Be calm, concise and slightly witty."
                    maxLength={300}
                    value={voiceSettings.customPersonality || ''}
                    onChange={(e) => handleUpdateVoiceSettings({ customPersonality: e.target.value })}
                  />
                </div>
              )}

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Response Length</span>
                  <span className="bytex-setting-desc">Spoken response detail level</span>
                </div>
                <div className="bytex-setting-control">
                  <select
                    value={voiceSettings.responseLength || 'balanced'}
                    onChange={(e: any) => handleUpdateVoiceSettings({ responseLength: e.target.value })}
                  >
                    <option value="balanced">Balanced (Default)</option>
                    <option value="short">Short</option>
                    <option value="detailed">Detailed</option>
                  </select>
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Wake Response</span>
                  <span className="bytex-setting-desc">Spoken response when "Hey ByteX" is activated</span>
                </div>
                <div className="bytex-setting-control">
                  <select
                    value={voiceSettings.wakeResponse || 'yes'}
                    onChange={(e: any) => handleUpdateVoiceSettings({ wakeResponse: e.target.value })}
                  >
                    <option value="yes">"Yes?" (Default)</option>
                    <option value="listening">"I'm listening."</option>
                    <option value="ready">"Ready."</option>
                    <option value="help">"How can I help?"</option>
                    <option value="go_ahead">"Go ahead."</option>
                    <option value="custom">Custom Wake Response</option>
                  </select>
                </div>
              </div>

              {voiceSettings.wakeResponse === 'custom' && (
                <div className="bytex-setting-row" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
                  <div className="bytex-setting-info">
                    <span className="bytex-setting-label">Custom Wake Phrase</span>
                    <span className="bytex-setting-desc">Spoken acknowledgment (Max 100 chars)</span>
                  </div>
                  <input
                    type="text"
                    className="bytex-input"
                    style={{ width: '100%', fontSize: '12px' }}
                    placeholder="e.g., At your service."
                    maxLength={100}
                    value={voiceSettings.customWakeResponse || ''}
                    onChange={(e) => handleUpdateVoiceSettings({ customWakeResponse: e.target.value })}
                  />
                </div>
              )}

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Speech Speed</span>
                  <span className="bytex-setting-desc">Audio rate multiplier ({voiceSettings.rate}x)</span>
                </div>
                <div className="bytex-setting-control">
                  <input
                    type="range"
                    min="0.5"
                    max="2.0"
                    step="0.1"
                    value={voiceSettings.rate}
                    onChange={(e) => handleUpdateVoiceSettings({ rate: parseFloat(e.target.value) })}
                  />
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Voice Pitch</span>
                  <span className="bytex-setting-desc">Audio frequency multiplier ({voiceSettings.pitch || 1.0}x)</span>
                </div>
                <div className="bytex-setting-control">
                  <input
                    type="range"
                    min="0.75"
                    max="1.5"
                    step="0.05"
                    value={voiceSettings.pitch || 1.0}
                    onChange={(e) => handleUpdateVoiceSettings({ pitch: parseFloat(e.target.value) })}
                  />
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Voice Volume</span>
                  <span className="bytex-setting-desc">Output volume ({Math.round(voiceSettings.volume * 100)}%)</span>
                </div>
                <div className="bytex-setting-control">
                  <input
                    type="range"
                    min="0"
                    max="1.0"
                    step="0.05"
                    value={voiceSettings.volume}
                    onChange={(e) => handleUpdateVoiceSettings({ volume: parseFloat(e.target.value) })}
                  />
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">
                    <Mic size={14} style={{ marginRight: 4 }} />
                    Continuous Listening
                  </span>
                  <span className="bytex-setting-desc">Keep microphone ready (OFF by default for privacy)</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={voiceSettings.continuous}
                    onChange={(e) => handleUpdateVoiceSettings({ continuous: e.target.checked })}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">
                    <Sparkles size={14} style={{ marginRight: 4, color: '#00f0ff' }} />
                    Wake Word Activation ("Hey ByteX")
                  </span>
                  <span className="bytex-setting-desc">Listen for "Hey ByteX" to activate voice commands</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={voiceSettings.wakeWordEnabled || false}
                    onChange={(e) => {
                      debugLog('[WakeDebug] wakeWordEnabled =', e.target.checked);
                      handleUpdateVoiceSettings({ wakeWordEnabled: e.target.checked });
                    }}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">
                    <Sparkles size={14} style={{ marginRight: 4, color: '#00f0ff' }} />
                    Continuous Listening
                  </span>
                  <span className="bytex-setting-desc">Keep listening for follow-up commands after ByteX responds</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={voiceSettings.continuousListeningEnabled || voiceSettings.continuous || false}
                    onChange={(e) => {
                      debugLog('[WakeDebug] continuousListeningEnabled =', e.target.checked);
                      handleUpdateVoiceSettings({
                        continuousListeningEnabled: e.target.checked,
                        continuous: e.target.checked
                      });
                    }}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Wake Phrase</span>
                  <span className="bytex-setting-desc">Supported wake activation phrase</span>
                </div>
                <span className="bytex-placeholder-tag">Hey ByteX</span>
              </div>

              <div className="bytex-setting-row" style={{ marginTop: 8, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="bytex-btn bytex-btn-secondary"
                  style={{ fontSize: '12px', padding: '6px 12px' }}
                  onClick={() => {
                    const reset = voiceSettingsService.resetToDefaults();
                    setVoiceSettings(reset);
                  }}
                >
                  Reset Voice Settings
                </button>
              </div>

              <div className="bytex-setting-row" style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.1)', flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
                <div className="bytex-setting-info" style={{ width: '100%' }}>
                  <span className="bytex-setting-label">Diagnostic Wake Word Panel (Development Only)</span>
                  <span className="bytex-setting-desc">Real-time status of SpeechRecognition instance and microphone state</span>
                </div>

                <div style={{ background: 'rgba(0,0,0,0.4)', padding: '10px 14px', borderRadius: 6, fontSize: '11px', fontFamily: 'monospace', width: '100%', color: '#00f0ff', lineHeight: '1.6' }}>
                  <div>SpeechRecognition supported: {typeof window !== 'undefined' && 'SpeechRecognition' in window ? 'YES' : 'NO'}</div>
                  <div>webkitSpeechRecognition supported: {typeof window !== 'undefined' && 'webkitSpeechRecognition' in window ? 'YES' : 'NO'}</div>
                  <div>Wake enabled: {voiceSettings.wakeWordEnabled ? 'YES' : 'NO'}</div>
                  <div>Continuous Listening: {voiceSettings.continuousListeningEnabled || voiceSettings.continuous ? 'YES' : 'NO'}</div>
                  <div>State: {wakeWordService.getState()}</div>
                  <div>Recognition instance: {wakeWordService.getDiagnosticData().recognitionInstanceExists ? 'EXISTS' : 'MISSING'}</div>
                  <div>Recognition running: {wakeWordService.isRunning() ? 'YES' : 'NO'}</div>
                  <div>getUserMedia permission: {wakeWordService.getDiagnosticData().permissionState}</div>
                  <div>Last transcript: "{wakeWordService.getDiagnosticData().lastTranscript}"</div>
                  <div>Last isFinal: {String(wakeWordService.getDiagnosticData().lastIsFinal)}</div>
                  <div>Last resultIndex: {wakeWordService.getDiagnosticData().lastResultIndex}</div>
                  <div>Last event time: {wakeWordService.getDiagnosticData().lastEventTime}</div>
                  <div>Instance ID: {wakeWordService.instanceId}</div>
                  {wakeWordService.getLastError() && <div style={{ color: '#ef4444' }}>Last Error: {wakeWordService.getLastError()}</div>}
                </div>

                <div style={{ display: 'flex', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
                  <button
                    className="bytex-btn secondary"
                    style={{ fontSize: '11px', padding: '4px 10px' }}
                    onClick={() => {
                      debugLog('[WakeDebug] START RAW MIC TEST clicked');
                      wakeWordService.runRawMicTest((msg) => debugLog(`[WakeDebug] ${msg}`));
                    }}
                  >
                    START RAW MIC TEST
                  </button>
                  <button
                    className="bytex-btn secondary"
                    style={{ fontSize: '11px', padding: '4px 10px' }}
                    onClick={() => {
                      debugLog('[WakeDebug] START WAKE LISTENER clicked');
                      wakeWordService.start();
                    }}
                  >
                    START WAKE LISTENER
                  </button>
                  <button
                    className="bytex-btn primary"
                    style={{ fontSize: '11px', padding: '4px 10px' }}
                    onClick={() => {
                      debugLog('[WakeDebug] Manual Test Wake Word clicked');
                      wakeWordService.triggerWakeWord('Hey ByteX');
                    }}
                  >
                    TEST WAKE WORD
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* MEMORY TAB (FEATURE #39 PERSISTENT MEMORY 2.0) */}
          {activeTab === 'memory' && (
            <div className="bytex-memory-section">
              <div className="bytex-memory-header">
                <div>
                  <h3 className="bytex-memory-title">
                    <Database size={16} />
                    <span>BYTE X PERSISTENT MEMORY 2.0</span>
                  </h3>
                  <p className="bytex-memory-subtitle">
                    {memories.length} stored memories (Persistent SQLite Database)
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <div className="bytex-memory-toggle-wrap">
                    <span className="bytex-memory-toggle-label">Learn Preferences:</span>
                    <label className="bytex-toggle-switch">
                      <input
                        type="checkbox"
                        checked={isLearningEnabled}
                        onChange={async (e) => {
                          const val = e.target.checked;
                          setIsLearningEnabled(val);
                          try {
                            await fetch(`http://127.0.0.1:8000/api/learning/toggle?enabled=${val}`, { method: 'POST' });
                          } catch (err) {
                            console.warn('Failed to toggle learning:', err);
                          }
                        }}
                      />
                      <span className="bytex-toggle-slider" />
                    </label>
                  </div>

                  {memories.length > 0 && (
                    <button className="bytex-memory-clear-btn" onClick={handleClearAllMemories}>
                      <Trash2 size={14} />
                      Clear All
                    </button>
                  )}
                </div>
              </div>

              {/* Active Project Banner */}
              {activeProjectInfo && (
                <div style={{ background: 'rgba(0, 240, 255, 0.06)', border: '1px solid rgba(0, 240, 255, 0.3)', padding: '10px 14px', borderRadius: 8, marginBottom: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: '#00f0ff', fontWeight: 600, letterSpacing: '0.05em' }}>
                      📁 Active Project
                    </span>
                    <div style={{ fontSize: '0.92rem', color: '#f8fafc', fontWeight: 600, marginTop: 2 }}>
                      {activeProjectInfo.project_name} {activeProjectInfo.framework ? `(${activeProjectInfo.framework})` : ''}
                    </div>
                    {activeProjectInfo.workspace_path && (
                      <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                        {activeProjectInfo.workspace_path}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="bytex-btn bytex-btn-secondary"
                    style={{ fontSize: '11px', padding: '4px 10px' }}
                    onClick={async () => {
                      await bytexApi.clearActiveProject();
                      setActiveProjectInfo(null);
                    }}
                  >
                    Clear Active
                  </button>
                </div>
              )}

              <div className="bytex-memory-filter-bar">
                <div className="bytex-memory-search-box">
                  <Search size={14} className="bytex-memory-search-icon" />
                  <input
                    type="text"
                    placeholder="Search memories..."
                    value={memorySearchQuery}
                    onChange={(e) => setMemorySearchQuery(e.target.value)}
                    className="bytex-memory-filter-input"
                  />
                </div>

                <div className="bytex-memory-cat-chips">
                  {['ALL', 'USER_PREFERENCE', 'PROJECT', 'WORKFLOW', 'APPLICATION_PREFERENCE', 'ROUTINE', 'FACT', 'ALIAS'].map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      className={`bytex-cat-chip ${selectedCategoryFilter === cat ? 'active' : ''}`}
                      onClick={() => setSelectedCategoryFilter(cat)}
                    >
                      {cat.replace('USER_', '').replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>

              <form className="bytex-memory-form" onSubmit={handleAddMemory}>
                <input
                  type="text"
                  className="bytex-memory-input"
                  placeholder="Add a fact or preference (e.g., 'I prefer VS Code')..."
                  value={newMemoryContent}
                  onChange={(e) => setNewMemoryContent(e.target.value)}
                />
                <select
                  className="bytex-memory-select"
                  value={newMemoryCategory}
                  onChange={(e: any) => setNewMemoryCategory(e.target.value)}
                >
                  <option value="USER_PREFERENCE">User Preference</option>
                  <option value="PROJECT">Project</option>
                  <option value="WORKFLOW">Workflow</option>
                  <option value="APPLICATION_PREFERENCE">App Preference</option>
                  <option value="ROUTINE">Routine</option>
                  <option value="FACT">Fact</option>
                  <option value="ALIAS">Alias</option>
                </select>
                <button type="submit" className="bytex-memory-add-btn">
                  <Plus size={16} />
                  Add
                </button>
              </form>

              {isLoadingMemories ? (
                <div className="bytex-memory-empty">Loading memories...</div>
              ) : filteredMemories.length === 0 ? (
                <div className="bytex-memory-empty">
                  {memories.length === 0
                    ? 'No stored memories found. Add one above or tell ByteX "Remember that I prefer VS Code".'
                    : 'No memories match your current filter.'}
                </div>
              ) : (
                <div className="bytex-memory-list">
                  {filteredMemories.map((item) => (
                    <div key={item.id} className="bytex-memory-card">
                      {editingMemoryId === item.id ? (
                        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          <input
                            type="text"
                            className="bytex-memory-input"
                            value={editingContent}
                            onChange={(e) => setEditingContent(e.target.value)}
                            style={{ width: '100%' }}
                          />
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', alignItems: 'center' }}>
                            <select
                              className="bytex-memory-select"
                              value={editingCategory}
                              onChange={(e) => setEditingCategory(e.target.value)}
                            >
                              <option value="USER_PREFERENCE">User Preference</option>
                              <option value="PROJECT">Project</option>
                              <option value="WORKFLOW">Workflow</option>
                              <option value="APPLICATION_PREFERENCE">App Preference</option>
                              <option value="ROUTINE">Routine</option>
                              <option value="FACT">Fact</option>
                              <option value="ALIAS">Alias</option>
                            </select>
                            <button
                              type="button"
                              className="bytex-memory-add-btn"
                              style={{ padding: '4px 12px', fontSize: '12px' }}
                              onClick={() => handleSaveEdit(item.id)}
                            >
                              <Check size={13} />
                              Save
                            </button>
                            <button
                              type="button"
                              className="bytex-btn bytex-btn-secondary"
                              style={{ padding: '4px 10px', fontSize: '12px' }}
                              onClick={handleCancelEdit}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="bytex-memory-card-main">
                            <div className="bytex-memory-badge-row">
                              <span className={`bytex-memory-badge badge-${item.category.toLowerCase()}`}>
                                {item.category.replace('USER_', '').replace('_', ' ')}
                              </span>
                              {item.key && (
                                <span className="bytex-memory-key-tag">
                                  Key: {item.key}
                                </span>
                              )}
                              <span className="bytex-memory-date">
                                {new Date(item.created_at).toLocaleDateString()}
                              </span>
                            </div>
                            <p className="bytex-memory-content">{item.content}</p>
                          </div>

                          <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                            <button
                              type="button"
                              className="bytex-memory-delete-btn"
                              onClick={() => handleStartEdit(item)}
                              title="Edit memory"
                              style={{ color: '#38bdf8' }}
                            >
                              <Edit3 size={14} />
                            </button>
                            <button
                              type="button"
                              className="bytex-memory-delete-btn"
                              onClick={() => handleDeleteMemory(item.id)}
                              title="Forget memory"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* SUGGESTIONS TAB */}
          {activeTab === 'suggestions' && (
            <div className="bytex-voice-settings-group">
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Proactive Suggestions</span>
                  <span className="bytex-setting-desc">Proactively suggest useful follow-up actions and workflows</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={isSuggestionsEnabled}
                    onChange={(e) => handleUpdateSuggestionSettings(e.target.checked, suggestionFrequency)}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Suggestion Frequency</span>
                  <span className="bytex-setting-desc">Configure how proactively ByteX suggests actions</span>
                </div>
                <div className="bytex-setting-control">
                  <select
                    value={suggestionFrequency}
                    onChange={(e: any) => handleUpdateSuggestionSettings(isSuggestionsEnabled, e.target.value)}
                    disabled={!isSuggestionsEnabled}
                  >
                    <option value="minimal">Minimal (High Confidence Only)</option>
                    <option value="balanced">Balanced (Recommended)</option>
                    <option value="frequent">Frequent</option>
                  </select>
                </div>
              </div>

              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Safety & Permissions</span>
                  <span className="bytex-setting-desc">Suggestions NEVER execute automatically. User acceptance required.</span>
                </div>
                <span className="bytex-placeholder-tag">Strict Control</span>
              </div>
            </div>
          )}

          {activeTab === 'appearance' && (
            <>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Ambient Animations</span>
                  <span className="bytex-setting-desc">Animated light rays and soft atmospheric glow</span>
                </div>
                <label className="bytex-toggle-switch">
                  <input
                    type="checkbox"
                    checked={ambientAnimations}
                    onChange={(e) => handleToggleAmbientAnimations(e.target.checked)}
                  />
                  <span className="bytex-toggle-slider" />
                </label>
              </div>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Interface Theme</span>
                  <span className="bytex-setting-desc">Futuristic Dark Mode</span>
                </div>
                <span className="bytex-placeholder-tag">Dark Mode (Active)</span>
              </div>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Orb Glow Intensity</span>
                  <span className="bytex-setting-desc">Adjust ambient background glow</span>
                </div>
                <span className="bytex-placeholder-tag">High</span>
              </div>
            </>
          )}

          {activeTab === 'assistant' && (
            <>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Assistant Identity</span>
                  <span className="bytex-setting-desc">Project identity name</span>
                </div>
                <span className="bytex-placeholder-tag">ByteX AI</span>
              </div>
            </>
          )}

          {activeTab === 'security' && (
            <>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Authentication System</span>
                  <span className="bytex-setting-desc">Biometric Auth</span>
                </div>
                <span className="bytex-placeholder-tag">Phase 7 Security</span>
              </div>
            </>
          )}

          {activeTab === 'ai' && (
            <>
              <div className="bytex-setting-row">
                <div className="bytex-setting-info">
                  <span className="bytex-setting-label">Primary AI Provider</span>
                  <span className="bytex-setting-desc">Groq / Gemini Router</span>
                </div>
                <span className="bytex-placeholder-tag">Groq (Primary) + Gemini (Fallback)</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
