import type { ChatMessage } from '../types';

export interface MockResponseResult {
  message: ChatMessage;
  processingDelayMs: number;
  speakingDurationMs: number;
}

export class MockAssistantService {
  private static responses: Record<string, string> = {
    hello: "Hello! I'm ByteX, your personal desktop AI assistant. I'm ready when you are.",
    hi: "Greetings. Systems are operational and ready for your commands.",
    "what can you do": "I am currently initializing my core architecture. I will support OS control, phone pairing, AI routing, and multi-step workflows.",
    "open chrome": "[Mock Action] Requesting to open Google Chrome. OS automation integration will be enabled in Phase 3.",
    "take screenshot": "[Mock Action] Screen capture requested. System capture capabilities will connect in Phase 3.",
    "system status": "[Mock Telemetry] CPU: 12% | RAM: 2.4 GB | GPU: 18% | Core: Online & Healthy.",
    "open youtube": "[Mock Action] Launching YouTube. Web automation capabilities scheduled for Phase 3.",
    help: "Available test commands: 'Hello', 'What can you do', 'System Status', or click any of the Quick Action chips below.",
  };

  public static async processCommand(userQuery: string): Promise<MockResponseResult> {
    const queryNormalized = userQuery.toLowerCase().trim();
    
    let responseText = this.responses[queryNormalized];

    if (!responseText) {
      // Check partial matches
      for (const [key, val] of Object.entries(this.responses)) {
        if (queryNormalized.includes(key)) {
          responseText = val;
          break;
        }
      }
    }

    if (!responseText) {
      responseText = `Received command: "${userQuery}". Core command pipeline is operational. Real AI provider backend will connect in Phase 3.`;
    }

    // Simulate realistic processing delay and speaking duration
    const processingDelayMs = 1200 + Math.random() * 600;
    const speakingDurationMs = Math.max(2000, responseText.length * 45);

    const message: ChatMessage = {
      id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      role: 'assistant',
      content: responseText,
      timestamp: new Date(),
      isMock: true,
    };

    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          message,
          processingDelayMs,
          speakingDurationMs,
        });
      }, processingDelayMs);
    });
  }
}
