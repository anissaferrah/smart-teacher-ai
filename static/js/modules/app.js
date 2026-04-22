import { stateManager } from './state-manager.js';
import { wsClient } from './ws-client.js?v=20260421a';
import { audioManager } from './audio-manager.js';
import UIManager from './ui-manager.js';

import { Header } from '../components/header.js';
import { SlideViewer } from '../components/slide-viewer.js';
import { ChatPanel } from '../components/chat-panel.js';
import { CourseSelector } from '../components/course-selector.js';
import { QAPanel } from '../components/qa-panel.js';

class SmartTeacherApp {
  constructor() {
    this.initialized = false;
    this.components = {};
  }

  // =========================
  // INIT SAFE FLOW
  // =========================
  async init() {
    try {
      console.log("🚀 APP INIT START");

      this._initializeComponents();
      console.log("✔ components ready");

      this._setupStateListeners();
      console.log("✔ state ready");

      this._setupWebSocketListeners();
      console.log("✔ ws listeners ready");

      this._setupCourseUpload();
      console.log("✔ upload ready");

      // 🔥 IMPORTANT FIX: session MUST come BEFORE WS connect
      await this._ensureWebSocketSession('fr', 'lycée');
      console.log("✔ session ready");

      wsClient.connect();
      console.log("✔ ws connecting");

      this.initialized = true;
      console.log("🎉 APP READY");

    } catch (error) {
      console.error("💥 INIT FAILED:", error);

      document.body.innerHTML = `
        <div style="padding:20px;color:red;font-family:Arial">
          <h2>Application error</h2>
          <pre>${error.stack}</pre>
        </div>
      `;
    }
  }

  // =========================
  // COMPONENTS
  // =========================
  _initializeComponents() {
    this.components.header = new Header('headerContainer');
    this.components.header.render();

    this.components.slideViewer = new SlideViewer('slideViewerContainer');
    this.components.slideViewer.render();

    this.components.chatPanel = new ChatPanel('chatPanelContainer');
    this.components.chatPanel.render();

    this.components.courseSelector = new CourseSelector('courseSelectorContainer');
    this.components.courseSelector.render();

    this.components.qaPanel = new QAPanel('qaPanelContainer');
    this.components.qaPanel.render();
  }

  // =========================
  // STATE
  // =========================
  _setupStateListeners() {
    stateManager.subscribe('paused', (val) => {
      const btn = document.getElementById('pauseBtn');
      if (btn) btn.textContent = val ? "▶ Resume" : "⏸ Pause";
    });

    stateManager.subscribe('activePanel', (panel) => {
      document.querySelectorAll('.panel').forEach(p =>
        p.classList.toggle('active', p.id === `panel-${panel}`)
      );
    });
  }

  // =========================
  // WEBSOCKET (FIXED)
  // =========================
  _setupWebSocketListeners() {

    wsClient.on('connected', () => {
      console.log("✅ WS connected");
      this.components.header?.setStatus('connected', 'Connected');
    });

    wsClient.on('disconnected', (e) => {
      console.warn("⚠️ WS disconnected:", e);
      this.components.header?.setStatus('idle', 'Disconnected');
    });

    wsClient.on('error', (err) => {
      console.error("❌ WS error:", err);
      UIManager.showNotification("Connection error", "error");
    });

    // optional debug (IMPORTANT for your 1008 issue)
    wsClient.on('close', (e) => {
      console.warn("🔴 WS CLOSE:", e?.code, e?.reason);
    });

    wsClient.on('slide_data', (data) => {
      this.components.slideViewer?.displaySlide(
        data.title,
        data.text,
        data.image_url
      );
    });

    wsClient.on('response', (data) => {
      this.components.chatPanel?.addMessage(
        data.text,
        't',
        data.label || "Teacher"
      );
    });
  }

  // =========================
  // SESSION (CRITICAL FIX PART)
  // =========================
  async _ensureWebSocketSession(language, level) {
    try {
      const res = await fetch('/session', {
        method: 'POST'
      });

      if (!res.ok) {
        throw new Error("Session creation failed");
      }

      const data = await res.json();

      if (!data.session_id || !data.token) {
        throw new Error("Invalid session response");
      }

      stateManager.sessionId = data.session_id;

      wsClient.sessionToken = data.token;
      wsClient.sessionLanguage = language;
      wsClient.sessionLevel = level;

      localStorage.setItem('session_id', data.session_id);
      localStorage.setItem('token', data.token);

      console.log("🔐 session initialized");

      return data;

    } catch (err) {
      console.error("❌ session error:", err);
      throw err;
    }
  }

  // =========================
  // COURSE UPLOAD (SAFE)
  // =========================
  _setupCourseUpload() {
    const dz = document.getElementById('dz');
    const fi = document.getElementById('fi');
    const btn = document.getElementById('buildBtn');

    if (!dz || !fi || !btn) {
      console.warn("Upload elements missing");
      return;
    }

    dz.onclick = () => fi.click();

    fi.onchange = () => {
      btn.disabled = fi.files.length === 0;
    };

    btn.onclick = async () => {
      if (!fi.files.length) return;

      const form = new FormData();
      for (const f of fi.files) form.append("files", f);

      try {
        UIManager.showNotification("Uploading...", "info");

        const res = await fetch("/course/build", {
          method: "POST",
          body: form
        });

        if (!res.ok) throw new Error("Upload failed");

        const data = await res.json();
        console.log("UPLOAD OK:", data);

        UIManager.showNotification("Upload success", "success");

      } catch (e) {
        console.error(e);
        UIManager.showNotification("Upload error", "error");
      }
    };
  }

  // =========================
  // PUBLIC API
  // =========================
  askQuestion(text) {
    if (!wsClient.isConnected()) return;

    wsClient.send({
      type: "question",
      text
    });
  }

  selectCourse(courseId) {
    stateManager.setState('courseId', courseId);

    wsClient.send({
      type: "start_course",
      course_id: courseId
    });
  }
}

// =========================
// BOOTSTRAP
// =========================
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    window.app = new SmartTeacherApp();
    window.app.init();
  });
} else {
  window.app = new SmartTeacherApp();
  window.app.init();
}

export default SmartTeacherApp;