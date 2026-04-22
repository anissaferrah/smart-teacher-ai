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

  async init() {
    if (this.initialized) return;

    try {
      console.log("🚀 APP INIT START");

      this._initializeComponents();
      this._setupStateListeners();
      this._setupWebSocketListeners();
      this._setupCourseUpload();

      await this._ensureSession("fr", "lycée");

      wsClient.connect();

      this.initialized = true;
      console.log("🎉 APP READY");

    } catch (error) {
      console.error("💥 INIT FAILED:", error);

      document.body.innerHTML = `
        <div style="padding:20px;color:red;font-family:Arial">
          <h2>Application error</h2>
          <pre>${error?.stack || error}</pre>
        </div>
      `;
    }
  }

  // ================= COMPONENTS =================
  _initializeComponents() {
    const safe = (Cls, id) => {
      try {
        const el = document.getElementById(id);
        if (!el) return null;
        const c = new Cls(id);
        c.render();
        return c;
      } catch (e) {
        console.warn(`Component error ${id}`, e);
        return null;
      }
    };

    this.components.header = safe(Header, 'headerContainer');
    this.components.slideViewer = safe(SlideViewer, 'slideViewerContainer');
    this.components.chatPanel = safe(ChatPanel, 'chatPanelContainer');
    this.components.courseSelector = safe(CourseSelector, 'courseSelectorContainer');
    if (this.components.courseSelector) {
      this.components.courseSelector.onCourseSelect = (course) => {
        this.selectCourse(course.id);
      };
    }
    this.components.qaPanel = safe(QAPanel, 'qaPanelContainer');
  }

  // ================= STATE =================
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

  // ================= WEBSOCKET =================
  _setupWebSocketListeners() {

    wsClient.on('connected', () => {
      this.components.header?.setStatus('connected', 'Connected');
    });

    wsClient.on('disconnected', () => {
      this.components.header?.setStatus('idle', 'Disconnected');
    });

    wsClient.on('error', (err) => {
      UIManager.showNotification("Connection error", "error");
      console.error(err);
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

    // FIX-6: Handle session_started to display student profile
    wsClient.on('session_started', (data) => {
      console.log('✅ Session started', data);
      
      // Display student profile in header
      if (data.student_profile) {
        this.components.header?.updateProfile({
          name: data.student_profile.name || data.student_profile.student_id || 'Étudiant',
          level: data.student_profile.level || 'lycée',
          language: data.student_profile.language || 'fr'
        });
        stateManager.studentProfile = data.student_profile;
        localStorage.setItem('student_id', data.student_profile.student_id || '');
      }
      
      // FIX-1: Sync session language from server
      if (data.language) {
        wsClient.sessionLanguage = data.language;
        stateManager.setState('sessionLanguage', data.language);
        console.log(`🌐 Session language synchronized: ${data.language}`);
      }
    });
  }

  // ================= SESSION FIX =================
  async _ensureSession(language, level) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
      const res = await fetch('/session', {
        method: 'POST',
        signal: controller.signal
      });

      clearTimeout(timeout);

      if (!res.ok) throw new Error("Session failed");

      const data = await res.json();

      if (!data?.session_id || !data?.token) {
        throw new Error("Invalid session response");
      }

      stateManager.sessionId = data.session_id;

      wsClient.sessionToken = data.token;
      wsClient.sessionLanguage = language;
      wsClient.sessionLevel = level;

      localStorage.setItem('session_id', data.session_id);
      localStorage.setItem('token', data.token);

      console.log("🔐 session OK");

    } catch (e) {
      console.error("SESSION ERROR", e);
      throw e;
    }
  }

  // ================= UPLOAD =================
  _setupCourseUpload() {
    const dz = document.getElementById('dz');
    const fi = document.getElementById('fi');
    const btn = document.getElementById('buildBtn');
    const bstat = document.getElementById('bstat');
    const ingestionLog = document.getElementById('ingestionLog');
    const pfill = document.getElementById('pfill');

    if (!dz || !fi || !btn) return;

    dz.onclick = () => fi.click();

    fi.onchange = () => {
      btn.disabled = !fi.files.length;
    };

    btn.onclick = () => {
      if (!fi.files.length) return;

      const form = new FormData();
      [...fi.files].forEach(f => form.append("files", f));
      const bLang = document.getElementById('bLang');
      const bLevel = document.getElementById('bLevel');
      const language = bLang ? bLang.value : 'fr';
      const level = bLevel ? bLevel.value : 'lycée';
      form.append('language', language);
      form.append('level', level);

      if (bstat) bstat.textContent = '⏳ Démarrage de l’upload…';
      if (ingestionLog) ingestionLog.innerHTML = '';
      if (pfill) pfill.style.width = '0%';

      UIManager.showNotification("Uploading...", "info");
      if (bstat) bstat.textContent = '⏳ Upload en cours…';

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/course/build', true);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && pfill) {
          const percent = Math.round((event.loaded / event.total) * 100);
          pfill.style.width = percent + '%';
        }
      };

      xhr.onload = async () => {
        try {
          if (xhr.status >= 200 && xhr.status < 300) {
            const payload = JSON.parse(xhr.responseText || '{}');
            let logHtml = '';
            let okCount = 0;
            if (payload && Array.isArray(payload.results)) {
              payload.results.forEach((item) => {
                if (item.status === 'ok') {
                  logHtml += `<div style='color:green'>✅ ${item.file} importé avec succès</div>`;
                  okCount++;
                } else {
                  logHtml += `<div style='color:red'>❌ ${item.file} : ${item.error || 'Erreur inconnue'}`;
                  if (item.traceback) logHtml += `<details><summary>Traceback</summary><pre>${item.traceback}</pre></details>`;
                  logHtml += `</div>`;
                }
              });
              if (bstat) bstat.textContent = okCount > 0 ? `✅ ${okCount}/${payload.results.length} fichier(s) importé(s)` : '❌ Aucun cours importé';
              if (ingestionLog) ingestionLog.innerHTML = logHtml;
            } else {
              if (bstat) bstat.textContent = '✅ Upload terminé';
            }
            if (pfill) pfill.style.width = '100%';

            UIManager.showNotification("Upload success", "success");

            // Refresh course list
            try {
              const res = await fetch('/course/list');
              if (res.ok) {
                const json = await res.json();
                const courses = (json.courses || []).map(c => ({
                  id: c.id,
                  name: c.title || c.name || c.id,
                  domain: c.domain || '',
                  subject: c.subject || '',
                }));
                this.components.courseSelector?.displayCourses(courses);
              }
            } catch (e) {
              console.warn('Failed to refresh course list', e);
            }

          } else {
            let errMsg = 'Upload failed';
            try { errMsg = JSON.parse(xhr.responseText).detail || JSON.parse(xhr.responseText).message || errMsg; } catch(e){}
            if (bstat) bstat.textContent = '❌ Erreur lors de l’upload';
            if (ingestionLog) ingestionLog.innerHTML = `<div style='color:red'>${errMsg}</div>`;
            if (pfill) pfill.style.width = '0%';
            UIManager.showNotification(errMsg, 'error');
          }
        } catch (e) {
          console.error(e);
        }
      };

      xhr.onerror = () => {
        if (bstat) bstat.textContent = '❌ Erreur lors de l’upload';
        if (pfill) pfill.style.width = '0%';
        UIManager.showNotification('Upload error', 'error');
      };

      xhr.send(form);
    };
  }

  // ================= API =================
  askQuestion(text) {
    if (!wsClient.isConnected()) return;

    wsClient.send({ type: "question", text });
  }

  selectCourse(courseId) {
    stateManager.setState('courseId', courseId);

    wsClient.send({
      type: "start_course",
      course_id: courseId
    });
  }
}

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