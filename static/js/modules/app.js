/**
 * Smart Teacher Application
 * Main entry point - initializes all modules and components
 */

import { stateManager } from './modules/state-manager.js';
import { wsClient } from './modules/ws-client.js?v=20260421a';
import { audioManager } from './modules/audio-manager.js';
import UIManager from './modules/ui-manager.js';
import { Header } from './components/header.js';
import { SlideViewer } from './components/slide-viewer.js';
import { ChatPanel } from './components/chat-panel.js';
import { CourseSelector } from './components/course-selector.js';
import { QAPanel } from './components/qa-panel.js';

class SmartTeacherApp {
  constructor() {
    this.initialized = false;
    this.components = {};
    this._selectedUploadFiles = [];
    this._uploadingCourse = false;
    this._lastUploadSummary = '';
  }

  async init() {
    try {
      console.log('🚀 Initializing Smart Teacher Application...');

      // Initialize components
      this._initializeComponents();
      console.log('✅ Components initialized');

      // Set up state listeners
      this._setupStateListeners();
      console.log('✅ State listeners attached');

      // Set up WebSocket listeners
      this._setupWebSocketListeners();
      console.log('✅ WebSocket listeners attached');

      this._setupCourseUpload();
      console.log('✅ Course upload handlers attached');

      if (!this._beforeUnloadHandler) {
        this._beforeUnloadHandler = () => wsClient.disconnect();
        window.addEventListener('beforeunload', this._beforeUnloadHandler);
      }

      await this._ensureWebSocketSession('fr', 'lycée');
      console.log('✅ Session prepared');

      // Connect to WebSocket
      wsClient.connect();
      console.log('✅ WebSocket connection initiated');

      // Initialize audio waveform
      audioManager.initWaveform();
      console.log('✅ Audio waveform initialized');

      this._loadAvailableCourses().catch((error) => {
        console.warn('⚠️ Unable to load course list:', error);
      });

      this.initialized = true;
      console.log('🎉 Application ready!');
    } catch (error) {
      console.error('❌ Initialization failed:', error);
      UIManager.showNotification('Erreur d\'initialisation', 'error');
    }
  }

  _initializeComponents() {
    // Header
    this.components.header = new Header('headerContainer');
    this.components.header.render();

    this.components.slideViewer = new SlideViewer('slideViewerContainer');
    this.components.slideViewer.render();
    this.components.slideViewer.onNext = () => {
      void this.nextSlide();
    };
    this.components.slideViewer.onPrev = () => {
      void this.previousSlide();
    };
    this.components.slideViewer.onPause = (isPaused) => {
      void (isPaused ? this.pause() : this.resume());
    };

    this.components.chatPanel = new ChatPanel('chatPanelContainer');
    this.components.chatPanel.render();
    this.components.chatPanel.onSendMessage = (text) => {
      void this.askQuestion(text);
    };

    this.components.courseSelector = new CourseSelector('courseSelectorContainer');
    this.components.courseSelector.render();
    this.components.courseSelector.onCourseSelect = (course) => {
      void this.selectCourse(course.id, course);
    };

    this.components.qaPanel = new QAPanel('qaPanelContainer');
    this.components.qaPanel.render();
    this.components.qaPanel.onSendQuestion = (text) => {
      void this.askQuestion(text);
    };

    console.log(`  ├─ Header component loaded`);
    console.log(`  ├─ SlideViewer component loaded`);
    console.log(`  ├─ ChatPanel component loaded`);
    console.log(`  ├─ CourseSelector component loaded`);
    console.log(`  └─ QAPanel component loaded`);
  }

  _setupStateListeners() {
    // Listen for state changes
    stateManager.subscribe('paused', (isPaused) => {
      const btn = document.getElementById('pauseBtn');
      if (btn) {
        btn.textContent = isPaused ? '▶ Reprendre' : '⏸ Pause';
      }
    });

    stateManager.subscribe('courseId', (courseId) => {
      console.log(`Course changed: ${courseId}`);
    });

    stateManager.subscribe('activePanel', (panel) => {
      this._setActivePanel(panel);
    });
  }

  _setActivePanel(panelName) {
    const normalizedPanel = panelName === 'quiz' ? 'qa' : panelName;
    document.querySelectorAll('.panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `panel-${normalizedPanel}`);
    });
  }

  _setupWebSocketListeners() {
    // Connection events
    wsClient.on('connected', () => {
      console.log('✅ Connected to server');
      this.components.header?.setStatus('connected', 'Connecté');
    });

    wsClient.on('disconnected', () => {
      console.log('⚠️ Disconnected from server');
      this.components.header?.setStatus('idle', 'Déconnecté');
    });

    wsClient.on('error', (error) => {
      console.error('❌ WebSocket error:', error);
      UIManager.showNotification('Erreur de connexion', 'error');
    });

    // Message events
    wsClient.on('slide_data', (data) => {
      this._handleSlideData(data);
    });

    wsClient.on('presentation_started', (data) => {
      this._handlePresentationStarted(data);
    });

    wsClient.on('audio_stream', (data) => {
      this._handleAudioStream(data);
    });

    wsClient.on('transcription', (data) => {
      this._handleTranscription(data);
    });

    wsClient.on('text_answer', (data) => {
      this._handleResponse(data);
    });

    wsClient.on('response', (data) => {
      this._handleResponse(data);
    });

    wsClient.on('status_update', (data) => {
      this._handleStatusUpdate(data);
    });
  }

  _setupCourseUpload() {
    this.uploadZone = document.getElementById('dz');
    this.uploadInput = document.getElementById('fi');
    this.uploadButton = document.getElementById('buildBtn');
    this.uploadInfo = document.getElementById('finfo');
    this.uploadProgress = document.getElementById('bprog');
    this.uploadStatus = document.getElementById('bstat');
    this.uploadFill = document.getElementById('pfill');
    this.languageSelect = document.getElementById('bLang');
    this.levelSelect = document.getElementById('bLevel');

    this.uploadZone?.addEventListener('click', () => this.uploadInput?.click());
    this.uploadZone?.addEventListener('dragover', (event) => {
      event.preventDefault();
      this.uploadZone.classList.add('drag');
    });
    this.uploadZone?.addEventListener('dragenter', (event) => {
      event.preventDefault();
      this.uploadZone.classList.add('drag');
    });
    this.uploadZone?.addEventListener('dragleave', (event) => {
      if (event.target === this.uploadZone) {
        this.uploadZone.classList.remove('drag');
      }
    });
    this.uploadZone?.addEventListener('drop', (event) => {
      event.preventDefault();
      this.uploadZone.classList.remove('drag');
      this._setUploadFiles(event.dataTransfer?.files || []);
    });

    this.uploadInput?.addEventListener('change', (event) => {
      this._setUploadFiles(event.target.files || []);
    });

    this.uploadButton?.addEventListener('click', () => {
      this._uploadSelectedCourses();
    });

    this._renderUploadSelection();
    this._setUploadBusy(false);
  }

  _setUploadFiles(fileList) {
    this._selectedUploadFiles = Array.from(fileList || []).filter((file) => file && file.size > 0);
    this._lastUploadSummary = '';
    this._renderUploadSelection();
  }

  _formatFileSize(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) {
      return '0 B';
    }

    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }

    return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  _escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  _renderUploadSelection() {
    if (!this.uploadInfo) {
      return;
    }

    if (this._selectedUploadFiles.length > 0) {
      this.uploadInfo.innerHTML = this._selectedUploadFiles
        .map((file) => `
          <div style="padding:8px 10px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.03);display:flex;justify-content:space-between;gap:12px;align-items:center;">
            <div style="min-width:0;">
              <div style="font-size:.86em;font-weight:700;color:var(--text);word-break:break-word;">${this._escapeHtml(file.name)}</div>
              <div style="font-size:.74em;color:var(--muted);">${this._formatFileSize(file.size)}</div>
            </div>
            <div style="font-size:.72em;color:var(--accent2);font-weight:700;white-space:nowrap;">Prêt</div>
          </div>
        `)
        .join('');
    } else if (this._lastUploadSummary) {
      this.uploadInfo.innerHTML = `
        <div style="padding:10px 12px;border:1px solid rgba(0,229,176,.2);border-radius:10px;background:rgba(0,229,176,.06);color:var(--text);font-size:.85em;">
          ${this._escapeHtml(this._lastUploadSummary)}
        </div>
      `;
    } else {
      this.uploadInfo.innerHTML = `
        <div style="padding:10px 12px;border:1px dashed var(--border);border-radius:10px;color:var(--muted);font-size:.82em;">
          Aucun fichier sélectionné. Cliquez sur la zone ou déposez un PDF, DOCX, PPTX ou TXT.
        </div>
      `;
    }

    this._syncUploadControls();
  }

  _syncUploadControls() {
    if (this.uploadButton) {
      this.uploadButton.disabled = this._uploadingCourse;
    }

    if (this.uploadInput) {
      this.uploadInput.disabled = this._uploadingCourse;
    }
  }

  _setUploadBusy(isBusy, statusText = '') {
    this._uploadingCourse = isBusy;

    if (this.uploadZone) {
      this.uploadZone.classList.toggle('drag', false);
      this.uploadZone.style.opacity = isBusy ? '0.92' : '';
    }

    if (this.uploadProgress) {
      this.uploadProgress.style.display = isBusy || this._lastUploadSummary ? 'flex' : 'none';
    }

    if (this.uploadStatus) {
      this.uploadStatus.textContent = statusText || (this._lastUploadSummary ? 'Import terminé' : 'Construction…');
    }

    if (this.uploadFill) {
      this.uploadFill.style.width = isBusy ? '55%' : (this._lastUploadSummary ? '100%' : '0%');
    }

    this._syncUploadControls();
  }

  async _uploadSelectedCourses() {
    if (this._uploadingCourse) {
      return;
    }

    if (!this._selectedUploadFiles.length) {
      this.uploadInput?.click();
      UIManager.showNotification('Sélectionne un fichier de cours pour l’import.', 'info');
      return;
    }

    const language = this.languageSelect?.value || 'fr';
    const level = this.levelSelect?.value || 'lycée';
    const formData = new FormData();

    this._selectedUploadFiles.forEach((file) => {
      formData.append('files', file);
    });
    formData.append('language', language);
    formData.append('level', level);

    try {
      this._setUploadBusy(true, 'Import du cours en cours…');

      const response = await fetch('/course/build', {
        method: 'POST',
        body: formData,
      });

      let payload = null;
      if (response.ok) {
        payload = await response.json();
      } else {
        let errorMessage = `Import impossible (${response.status})`;
        try {
          const errorPayload = await response.json();
          errorMessage = errorPayload.detail || errorPayload.message || errorMessage;
        } catch (_) {
          // Ignore non-JSON error bodies.
        }
        throw new Error(errorMessage);
      }

      const results = Array.isArray(payload?.results) ? payload.results : [];
      const okCount = results.filter((item) => item && item.status !== 'error').length;
      const totalCount = results.length || this._selectedUploadFiles.length;
      const firstSuccess = results.find((item) => item && item.course_id && item.status !== 'error');

      if (firstSuccess?.course_id) {
        const uploadedCourse = {
          id: String(firstSuccess.course_id),
          name: firstSuccess.title || firstSuccess.course || firstSuccess.file || 'Cours importé',
          domain: firstSuccess.domain || 'general',
          chapters: firstSuccess.chapters || 0,
          sections: firstSuccess.sections || 0,
          language: language,
          level: level,
        };

        stateManager.setState('courseId', uploadedCourse.id);
        stateManager.setState('course', uploadedCourse);
        if (this.components.courseSelector) {
          const currentCourses = Array.isArray(this.components.courseSelector.courses)
            ? this.components.courseSelector.courses.filter((course) => course.id !== uploadedCourse.id)
            : [];
          this.components.courseSelector.displayCourses([uploadedCourse, ...currentCourses]);
        }

        void this.selectCourse(uploadedCourse.id, uploadedCourse);
      }

      this._lastUploadSummary = `${okCount}/${totalCount} fichier(s) importé(s) avec succès.`;
      this._selectedUploadFiles = [];
      if (this.uploadInput) {
        this.uploadInput.value = '';
      }

      this._setUploadBusy(false, 'Import terminé');
      this._renderUploadSelection();
      UIManager.showNotification(this._lastUploadSummary, okCount > 0 ? 'success' : 'warning');

      this._loadAvailableCourses().catch((error) => {
        console.warn('⚠️ Unable to refresh course list:', error);
      });
    } catch (error) {
      console.error('❌ Course upload failed:', error);
      this._lastUploadSummary = `Échec de l'import: ${error.message}`;
      this._setUploadBusy(false, 'Import échoué');
      this._renderUploadSelection();
      UIManager.showNotification(error.message || 'Import impossible', 'error');
    }
  }

  async _loadAvailableCourses() {
    const response = await fetch('/course/list');
    if (!response.ok) {
      throw new Error(`Course list request failed (${response.status})`);
    }

    const payload = await response.json();
    const courses = Array.isArray(payload?.courses)
      ? payload.courses.map((course) => ({
          id: String(course.id),
          name: course.display_title || course.title || course.subject || 'Cours',
          domain: course.domain || course.subject || course.level || '',
          chapters: course.chapter_count ?? course.chapters ?? 0,
          sections: course.section_count ?? course.sections ?? 0,
          language: course.language || 'fr',
          level: course.level || 'lycée',
        }))
      : [];

    this.components.courseSelector?.displayCourses(courses);
  }

  async _ensureWebSocketSession(language, level) {
    if (typeof wsClient.prepareSession === 'function') {
      return wsClient.prepareSession(language, level);
    }

    const response = await fetch('/session', { method: 'POST' });
    if (!response.ok) {
      throw new Error(`Session negotiation failed (${response.status})`);
    }

    const payload = await response.json();
    if (!payload.session_id || !payload.token) {
      throw new Error('Session negotiation returned an invalid payload');
    }

    stateManager.sessionId = payload.session_id;
    wsClient.sessionToken = payload.token;
    wsClient.sessionLanguage = language;
    wsClient.sessionLevel = level;
    localStorage.setItem('session_id', payload.session_id);
    localStorage.setItem('token', payload.token);
    return payload;
  }

  _handleSlideData(data) {
    const { title, text, image_url, slide_path, course, chapter, section, total_sections } = data;
    const slideImageUrl = image_url || slide_path || null;
    const courseTitle = course || stateManager.course?.name || 'Aucun cours';
    
    stateManager.setState('slideTitle', title);
    stateManager.setState('slideText', text);
    
    if (this.components.slideViewer) {
      this.components.slideViewer.displaySlide(title, text, slideImageUrl);
      this.components.slideViewer.updateHeader(courseTitle, chapter || 'Chapitre');
      this.components.slideViewer.updateProgress(section || 0, total_sections || 1);
    }
  }

  _handlePresentationStarted(data) {
    const courseTitle = data.course || stateManager.course?.name || 'Aucun cours';
    const chapterTitle = data.chapter || 'Chapitre 1';
    const sectionTitle = data.section || 'Section 1';
    const narration = data.narration || data.content || 'Présentation en cours…';
    const reasoningTrace = this._normalizeReasoningTrace(
      data.reasoning || data.reasoning_trace || data.metrics?.reasoning_trace || []
    );

    stateManager.setState('activePanel', 'course');
    stateManager.setState('slideTitle', sectionTitle);
    stateManager.setState('slideText', narration);

    if (this.components.slideViewer) {
      this.components.slideViewer.updateHeader(courseTitle, chapterTitle);
      this.components.slideViewer.displaySlide(sectionTitle, narration, data.image_url || data.slide_path || null);
      this.components.slideViewer.enableControls();
    }

    if (this.components.chatPanel) {
      this.components.chatPanel.setReasoningTrace(reasoningTrace);
      if (reasoningTrace.length && typeof this.components.chatPanel.expand === 'function') {
        this.components.chatPanel.expand();
      }
    }

    if (this.components.qaPanel) {
      this.components.qaPanel.setReasoningTrace(reasoningTrace);
    }

    if (reasoningTrace.length) {
      const lastStage = reasoningTrace[reasoningTrace.length - 1] || {};
      stateManager.setState('lastStateMain', (lastStage.state || 'presenting').toLowerCase());
      stateManager.setState('lastSubstep', lastStage.summary || lastStage.title || null);
    }

    this.components.header?.setStatus('connected', 'Présentation chargée');
  }

  _handleAudioStream(data) {
    const { audio_data, mime_type, is_final, stream_id, turn_id } = data;
    
    audioManager.bufferAudioChunk(audio_data, mime_type, is_final, stream_id, turn_id);
    
    if (is_final) {
      this.components.slideViewer?.setWaveformState('off');
    }
  }

  _handleTranscription(data) {
    const { text, label, is_final } = data;
    
    if (this.components.chatPanel) {
      if (is_final) {
        this.components.chatPanel.addMessage(text, 's', label || 'Étudiant');
      }
    }
  }

  _handleResponse(data) {
    const answerText = data.text || data.content || '';
    const label = data.label || 'Professeur';
    const reasoningTrace = this._normalizeReasoningTrace(
      data.reasoning || data.reasoning_trace || data.metrics?.reasoning_trace || []
    );
    
    if (this.components.chatPanel) {
      this.components.chatPanel.addMessage(answerText, 't', label);
      this.components.chatPanel.setReasoningTrace(reasoningTrace);
      if (reasoningTrace.length && typeof this.components.chatPanel.expand === 'function') {
        this.components.chatPanel.expand();
      }
    }

    if (this.components.qaPanel) {
      this.components.qaPanel.addMessage(answerText, 't', label);
      this.components.qaPanel.setReasoningTrace(reasoningTrace);
    }

    if (reasoningTrace.length) {
      const lastStage = reasoningTrace[reasoningTrace.length - 1] || {};
      stateManager.setState('lastStateMain', (lastStage.state || 'idle').toLowerCase());
      stateManager.setState('lastSubstep', lastStage.summary || lastStage.title || null);
      console.log('Reasoning:', reasoningTrace);
    }
  }

  _handleStatusUpdate(data) {
    const { state, message } = data;
    
    const stateMap = {
      'idle': 'idle',
      'listening': 'listening',
      'processing': 'processing',
      'responding': 'responding',
      'presenting': 'presenting'
    };

    const mappedState = stateMap[state] || 'idle';
    this.components.slideViewer?.setWaveformState(mappedState);
    this.components.chatPanel?.setStatus(mappedState, message);
  }

  _normalizeReasoningTrace(reasoning) {
    if (!reasoning) return [];
    if (Array.isArray(reasoning)) return reasoning;
    if (Array.isArray(reasoning.steps)) return reasoning.steps;
    if (Array.isArray(reasoning.trace)) return reasoning.trace;
    if (Array.isArray(reasoning.stages)) return reasoning.stages;
    return [];
  }

  // Public API for manual interactions
  async askQuestion(text) {
    if (!wsClient.isConnected()) {
      UIManager.showNotification('WebSocket non connecté, impossible d\'envoyer la question.', 'error');
      return false;
    }

    wsClient.send({
      type: 'text_question',
      content: text,
      text,
      course_id: stateManager.courseId,
      language: wsClient.sessionLanguage || 'fr',
      subject: stateManager.course?.domain || stateManager.course?.subject || '',
      turn_id: stateManager.activeQuestionTurnId
    });

    return true;
  }

  async selectCourse(courseId, course = null) {
    const selectedCourse = course || this.components.courseSelector?.courses?.find((item) => item.id === courseId) || stateManager.course;

    stateManager.setState('courseId', courseId);
    if (selectedCourse) {
      stateManager.setState('course', selectedCourse);
    }
    stateManager.setState('chapterIndex', 0);
    stateManager.setState('sectionIndex', 0);
    stateManager.setState('activePanel', 'course');

    this.components.slideViewer?.displaySlide(
      selectedCourse?.name || 'Cours sélectionné',
      'Chargement de la présentation…'
    );
    this.components.slideViewer?.disableControls();
    this.components.header?.setStatus('connected', 'Chargement du cours');

    if (!wsClient.isConnected()) {
      UIManager.showNotification('WebSocket non connecté, impossible de lancer la présentation.', 'error');
      return false;
    }

    wsClient.send({
      type: 'start_presentation',
      course_id: courseId,
      chapter_index: 0,
      section_index: 0,
    });

    return true;
  }

  pause() {
    stateManager.setState('paused', true);
    if (!wsClient.isConnected()) {
      return false;
    }

    wsClient.send({ type: 'pause', reason: 'user_request' });
    return true;
  }

  resume() {
    stateManager.setState('paused', false);
    if (!wsClient.isConnected()) {
      return false;
    }

    wsClient.send({ type: 'resume' });
    return true;
  }

  nextSlide() {
    if (!wsClient.isConnected()) {
      return false;
    }

    const nextSectionIndex = (stateManager.sectionIndex || 0) + 1;
    stateManager.setState('sectionIndex', nextSectionIndex);

    wsClient.send({
      type: 'start_presentation',
      course_id: stateManager.courseId,
      chapter_index: stateManager.chapterIndex || 0,
      section_index: nextSectionIndex,
    });

    return true;
  }

  previousSlide() {
    if (!wsClient.isConnected()) {
      return false;
    }

    const previousSectionIndex = Math.max(0, (stateManager.sectionIndex || 0) - 1);
    stateManager.setState('sectionIndex', previousSectionIndex);

    wsClient.send({
      type: 'start_presentation',
      course_id: stateManager.courseId,
      chapter_index: stateManager.chapterIndex || 0,
      section_index: previousSectionIndex,
    });

    return true;
  }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.app = new SmartTeacherApp();
    window.app.init();
  });
} else {
  window.app = new SmartTeacherApp();
  window.app.init();
}

export default SmartTeacherApp;
