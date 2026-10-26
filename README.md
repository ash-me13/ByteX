# ByteX — Next-Gen AI Desktop Assistant & Intelligence Core

[![Deploy ByteX Interface to GitHub Pages](https://github.com/ash-me13/ByteX/actions/workflows/deploy.yml/badge.svg)](https://github.com/ash-me13/ByteX/actions/workflows/deploy.yml)
[![Live Interface](https://img.shields.io/badge/Live_Interface-GitHub_Pages-6366f1?style=for-the-badge&logo=github)](https://ash-me13.github.io/ByteX/)

> **Live Web Interface:** [https://ash-me13.github.io/ByteX/](https://ash-me13.github.io/ByteX/)

---

## 🌟 Overview

**ByteX** is a desktop AI assistant combining a reactive 3D Orb visual interface, local voice processing, intelligent multi-model LLM routing, proactive automation, and deep operating system control.

### ✨ Highlights
- **Interactive 3D Energy Orb**: WebGL/Three.js-powered visual manifestation with dynamic aura, custom color palettes, reactivity states (`idle`, `listening`, `thinking`, `speaking`, `executing`, `error`).
- **Real-Time Voice Pipeline**: Streaming speech-to-text, low-latency text-to-speech, and always-listening wake-word detection.
- **Intelligent Assistant Pipeline**: Multi-turn context memory, autonomous task recovery, and proactive suggestions.
- **Autonomous Coding & Terminal Engine**: Code generation, compilation error auto-diagnosis, repair cycles, and workspace awareness.
- **SmartLife Automations**: Natural language reminders, recurring tasks, and lifestyle routines.
- **Secure Architecture**: Local execution guards, confirmation gates for destructive actions, and sandboxed phone pairing.

---

## 🚀 Live Demo & Web Interface

Open the interface directly in your browser:
### 🔗 [https://ash-me13.github.io/ByteX/](https://ash-me13.github.io/ByteX/)

When hosted on GitHub Pages:
- The 3D Orb, customizer, audio synthesizer, and interactive demo response engine run entirely in the browser.
- To connect full desktop automation capabilities (file modifications, terminal execution, system app control), simply run the local ByteX backend.

---

## 🛠️ Quickstart (Full Desktop Assistant)

### 1. Clone the Repository
```bash
git clone https://github.com/ash-me13/ByteX.git
cd ByteX
```

### 2. Backend Setup
```bash
# Install Python dependencies
pip install -r backend/requirements.txt

# Configure your environment
cp backend/.env.example backend/.env
# Add your GEMINI_API_KEY / GROQ_API_KEY in backend/.env
```

### 3. Frontend Setup
```bash
cd ByteX
npm install
npm run dev
```

### 4. Or Run with Single-Command Launcher
```bash
# macOS / Linux
chmod +x start_bytex.sh
./start_bytex.sh

# Python launcher
python3 start_bytex.py

# Windows
start_bytex.bat
```

---

## 📁 Repository Structure

```
├── ByteX/               # React + TypeScript + Vite Frontend with 3D Orb Interface
│   ├── src/
│   │   ├── components/  # Orb, Chat, CommandInput, Customizer, Docks
│   │   ├── hooks/       # Voice, Command, and Shortcut hooks
│   │   ├── services/    # WebSocket client, Audio TTS/STT, Orb customization
│   │   └── types/       # TypeScript schema definitions
├── backend/             # FastAPI & Python Intelligence Core
│   ├── agent/           # Autonomous execution pipelines & planners
│   ├── ai/              # Gemini & Groq LLM routers and prompts
│   ├── api/             # REST routes & WebSocket multiplexer
│   ├── core/            # Assistant coordinator, security sanitizers
│   ├── memory/          # SQLite persistent memory & learning vectors
│   ├── security/        # Permission gates & audit logging
│   ├── services/        # Vision OCR, Screen understanding & Phone pairing
│   └── skills/          # OS control, coding fixers, smart life tools
├── android/             # Android companion phone pairing app
└── tests/               # Automated test suites & end-to-end verifications
```

---

## 📄 License
This project is licensed under the [Apache License 2.0](LICENSE).
