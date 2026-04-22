/**
 * Smart Teacher Application
 * Main entry point - initializes all modules and components
 */

import { stateManager } from './modules/state-manager.js';
import { wsClient } from './modules/ws-client.js?v=20260421a';
import { audioManager } from './modules/audio-manager.js?v=20260421g';
import UIManager from './modules/ui-manager.js';
import { Header } from './components/header.js?v=20260421b';
import { SlideViewer } from './components/slide-viewer.js';
import { ChatPanel } from './components/chat-panel.js?v=20260421h';
import { CourseSelector } from './components/course-selector.js';
import { QAPanel } from './components/qa-panel.js?v=20260421h';

class SmartTeacherApp {
  constructor() {
    this.initialized = false;
    this.components = {};
    this._selectedUploadFiles = [];
    this._uploadingCourse = false;
    this._lastUploadSummary = '';
    this._questionRecordingActive = false;
    this._questionRecorder = null;
    this._questionMediaStream = null;
    this._questionAudioChunks = [];
    this._questionAudioMimeType = 'audio/webm';
    this._questionAudioListenersBound = false;
    this._uploadStatusPollTimer = null;
  }

  async init() {
    try {
      console.log('🚀 Initializing Smart Teacher Application...');

      this._restoreStudentContext();

      this._initializeComponents();
      console.log('✅ Components initialized');

      this._setupStateListeners();
      console.log('✅ State listeners attached');

      this._setupWebSocketListeners();
      console.log('✅ WebSocket listeners attached');

      this._setupCourseUpload();
      console.log('✅ Course upload handlers attached');

      this._setupQuestionAudioListeners();
      console.log('✅ Audio question handlers attached');

      if (!this._beforeUnloadHandler) {
        this._beforeUnloadHandler = () => wsClient.disconnect();
        window.addEventListener('beforeunload', this._beforeUnloadHandler);
      }

      await this._ensureWebSocketSession('fr', 'lycée');
      console.log('✅ Session prepared');

      wsClient.connect();
      console.log('✅ WebSocket connection initiated');

      audioManager.initWaveform();
      console.log('✅ Audio waveform initialized');

      this._loadAvailableCourses().catch((error) => {
        console.warn('⚠️ Unable to load course list:', error);
      });
      await this._loadStudentProfile();
      this.initialized = true;
      this._exposeAuthHelpers();
      console.log('🎉 Application ready!');
    } catch (error) {
      console.error('❌ Initialization failed:', error);
      UIManager.showNotification('Erreur d\'initialisation', 'error');
    }
  }

  _initializeComponents() {
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
    wsClient.on('connected', () => {
      console.log('✅ Connected to server');
      this.components.header?.setStatus('connected', 'Connecté');
    });

    wsClient.on('disconnected', () => {
      console.log('⚠️ Disconnected from server');
      this.components.header?.setStatus('idle', 'Déconnecté');
    });

    wsClient.on('ws_error', (error) => {
      console.error('❌ WebSocket transport error:', error);
      UIManager.showNotification('Erreur de connexion WebSocket', 'error');
    });

    wsClient.on('server_error', (payload) => {
      const message = payload?.message || 'Erreur serveur';
      console.warn('⚠️ Server error:', payload);
      UIManager.showNotification(message, 'error');
    });

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

    wsClient.on('interrupt', (data) => {
      this._handleInterrupt(data);
    });
  }

  _setupQuestionAudioListeners() {
    if (this._questionAudioListenersBound) {
      return;
    }

    this._questionAudioListenersBound = true;

    window.addEventListener('qa-recording-toggled', (event) => {
      const active = Boolean(event.detail?.active);
      void this._setQuestionRecordingActive(active);
    });

    window.addEventListener('start-recording', () => {
      void this._toggleQuestionRecording();
    });
  }

  _interruptCurrentPlayback(reason = 'student_speaking') {
    const playbackSnapshot = audioManager.stopAudio();
    this.components.slideViewer?.setWaveformState('off');

    if (wsClient.isConnected()) {
      wsClient.send({
        type: 'interrupt',
        reason,
        playback_snapshot: playbackSnapshot,
      });
    }

    return playbackSnapshot;
  }

  _setQuestionStatus(state, text) {
    this.components.chatPanel?.setStatus(state, text);
    this.components.qaPanel?.setStatus(state, text);
  }

  async _toggleQuestionRecording() {
    if (this._questionRecordingActive) {
      return this._stopQuestionRecording();
    }

    return this._startQuestionRecording();
  }

  async _setQuestionRecordingActive(active) {
    if (active) {
      return this._startQuestionRecording();
    }

    return this._stopQuestionRecording();
  }

  async _startQuestionRecording() {
    if (this._questionRecordingActive) {
      return true;
    }

    if (!wsClient.isConnected()) {
      UIManager.showNotification('WebSocket non connecté, impossible d\'enregistrer la question.', 'error');
      return false;
    }

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      UIManager.showNotification('L\'enregistrement audio n\'est pas supporté dans ce navigateur.', 'error');
      return false;
    }

    try {
      this._interruptCurrentPlayback('student_speaking');

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      this._questionAudioChunks = [];
      this._questionAudioMimeType = mimeType;
      this._questionMediaStream = stream;
      this._questionRecorder = new MediaRecorder(stream, { mimeType });
      this._questionRecordingActive = true;

      this._setQuestionStatus('listening', 'Enregistrement en cours…');

      this._questionRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          this._questionAudioChunks.push(event.data);
        }
      };

      this._questionRecorder.onstop = async () => {
        const chunks = this._questionAudioChunks.slice();
        this._questionAudioChunks = [];

        if (this._questionMediaStream) {
          this._questionMediaStream.getTracks().forEach((track) => track.stop());
        }

        this._questionMediaStream = null;
        this._questionRecorder = null;
        this._questionRecordingActive = false;

        if (!chunks.length) {
          this._setQuestionStatus('idle', 'En attente');
          return;
        }

        const blob = new Blob(chunks, { type: this._questionAudioMimeType });
        this._setQuestionStatus('processing', 'Transcription de la question…');

        try {
          await this._submitQuestionAudio(blob, this._questionAudioMimeType);
        } catch (error) {
          console.error('❌ Audio question submission failed:', error);
          UIManager.showNotification('Impossible d\'envoyer la question audio.', 'error');
          this._setQuestionStatus('idle', 'En attente');
        }
      };

      this._questionRecorder.start();
      return true;
    } catch (error) {
      console.error('❌ Failed to start audio recording:', error);
      UIManager.showNotification('Impossible de démarrer le micro.', 'error');
      this._setQuestionStatus('idle', 'En attente');
      this._questionRecordingActive = false;
      return false;
    }
  }

  async _stopQuestionRecording() {
    if (!this._questionRecorder || this._questionRecorder.state === 'inactive') {
      this._questionRecordingActive = false;
      return false;
    }

    this._questionRecorder.stop();
    return true;
  }

  async _submitQuestionAudio(blob, mimeType) {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('Audio encoding failed'));
      reader.readAsDataURL(blob);
    });

    const audioData = String(dataUrl || '').split(',')[1] || '';
    if (!audioData) {
      throw new Error('Empty audio payload');
    }

    wsClient.send({
      type: 'audio_question',
      audio_data: audioData,
      mime_type: mimeType,
      course_id: stateManager.courseId,
      language: wsClient.sessionLanguage || 'fr',
      subject: stateManager.course?.domain || stateManager.course?.subject || '',
      turn_id: stateManager.activeQuestionTurnId,
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

  _applyUploadProgressStatus(payload) {
    const status = payload && typeof payload === 'object' ? payload : {};
    const progress = Number(status.progress ?? 0);
    const boundedProgress = Number.isFinite(progress) ? Math.max(0, Math.min(progress, 100)) : 0;
    const stepText = String(status.current_step || '').trim();

    if (this.uploadStatus && stepText) {
      this.uploadStatus.textContent = stepText;
    }

    if (this.uploadFill) {
      this.uploadFill.style.width = `${boundedProgress}%`;
    }
  }

  async _pollUploadStatusOnce() {
    try {
      const response = await fetch('/ingestion/status');
      if (!response.ok) {
        return;
      }

      const payload = await response.json();
      this._applyUploadProgressStatus(payload);
    } catch (error) {
      // Non-blocking: upload can continue even if polling fails intermittently.
    }
  }

  _startUploadStatusPolling() {
    this._stopUploadStatusPolling();
    this._pollUploadStatusOnce();
    this._uploadStatusPollTimer = setInterval(() => {
      this._pollUploadStatusOnce();
    }, 1200);
  }

  _stopUploadStatusPolling() {
    if (this._uploadStatusPollTimer) {
      clearInterval(this._uploadStatusPollTimer);
      this._uploadStatusPollTimer = null;
    }
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
      this._startUploadStatusPolling();

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

        wsClient.sessionLanguage = language;
        wsClient.sessionLevel = level;

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
    } finally {
      this._stopUploadStatusPolling();
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
    const courseTitle = data.course || data.course_title || stateManager.course?.name || 'Aucun cours';
    const chapterTitle = data.chapter
      || data.chapter_title
      || data.chapter_display
      || (Number.isFinite(Number(data.chapter_number)) ? `Chapter ${Number(data.chapter_number)}` : 'Chapitre');
    const slideTitle = data.title || data.section_title || data.slide_title || stateManager.slideTitle || 'Section';
    const slideText = data.text || data.narration || data.content || 'Présentation en cours…';
    const imageUrl = data.image_url || data.slide_path || null;
    const progressCurrent = Number(data.progress?.current ?? data.section_number ?? data.section ?? data.section_index ?? 0);
    const progressTotal = Number(data.progress?.total ?? data.total_sections ?? data.section_total ?? 0);

    const chapterIndexFromPayload = Number(data.chapter_index);
    const sectionIndexFromPayload = Number(data.section_index);
    const chapterNumber = Number(data.chapter_number ?? data.progress?.chapter ?? (Number.isFinite(chapterIndexFromPayload) ? chapterIndexFromPayload + 1 : 1));
    const sectionNumber = Number(data.section_number ?? data.progress?.current ?? data.section ?? (Number.isFinite(sectionIndexFromPayload) ? sectionIndexFromPayload + 1 : 1));

    stateManager.setState('slideTitle', slideTitle);
    stateManager.setState('slideText', slideText);
    stateManager.setState('slidePath', imageUrl || '');
    if (Number.isFinite(chapterIndexFromPayload) && chapterIndexFromPayload >= 0) {
      stateManager.setState('chapterIndex', chapterIndexFromPayload);
    } else if (Number.isFinite(chapterNumber) && chapterNumber > 0) {
      stateManager.setState('chapterIndex', chapterNumber - 1);
    }
    if (Number.isFinite(sectionIndexFromPayload) && sectionIndexFromPayload >= 0) {
      stateManager.setState('sectionIndex', sectionIndexFromPayload);
    } else if (Number.isFinite(sectionNumber) && sectionNumber > 0) {
      stateManager.setState('sectionIndex', sectionNumber - 1);
    }

    if (this.components.slideViewer) {
      this.components.slideViewer.displaySlide(slideTitle, slideText, imageUrl);
      this.components.slideViewer.updateHeader(courseTitle, chapterTitle);
      if (Number.isFinite(progressCurrent) && Number.isFinite(progressTotal) && progressTotal > 0) {
        this.components.slideViewer.updateProgress(progressCurrent, progressTotal);
      }
      this.components.slideViewer.enableControls();
    }

    this._setQuestionStatus('presenting', 'Présentation en cours…');

    if (this.components.chatPanel && slideText && slideText !== 'Présentation en cours…') {
      this.components.chatPanel.addMessage(slideText, 't', 'Professeur');
    }
  }

  _handlePresentationStarted(data) {
    const courseTitle = data.course || stateManager.course?.name || 'Aucun cours';
    const chapterTitle = data.chapter
      || data.chapter_title
      || data.chapter_display
      || (Number.isFinite(Number(data.chapter_number)) ? `Chapter ${Number(data.chapter_number)}` : 'Chapitre 1');
    const sectionTitle = data.section || data.section_title || 'Section 1';
    const narration = data.narration || data.content || 'Présentation en cours…';
    const imageUrl = this._normalizeImageUrl(data.image_url || data.slide_path || null);
    const reasoningTrace = this._normalizeReasoningTrace(
      data.reasoning || data.reasoning_trace || data.metrics?.reasoning_trace || []
    );

    const chapterIndexFromPayload = Number(data.chapter_index);
    const sectionIndexFromPayload = Number(data.section_index);
    const chapterNumber = Number(data.chapter_number ?? (Number.isFinite(chapterIndexFromPayload) ? chapterIndexFromPayload + 1 : 1));
    const sectionNumber = Number(data.section_number ?? data.section ?? (Number.isFinite(sectionIndexFromPayload) ? sectionIndexFromPayload + 1 : 1));

    stateManager.setState('activePanel', 'course');
    stateManager.setState('slideTitle', sectionTitle);
    stateManager.setState('slideText', narration);
    if (Number.isFinite(chapterIndexFromPayload) && chapterIndexFromPayload >= 0) {
      stateManager.setState('chapterIndex', chapterIndexFromPayload);
    } else if (Number.isFinite(chapterNumber) && chapterNumber > 0) {
      stateManager.setState('chapterIndex', chapterNumber - 1);
    }
    if (Number.isFinite(sectionIndexFromPayload) && sectionIndexFromPayload >= 0) {
      stateManager.setState('sectionIndex', sectionIndexFromPayload);
    } else if (Number.isFinite(sectionNumber) && sectionNumber > 0) {
      stateManager.setState('sectionIndex', sectionNumber - 1);
    }

    this._setQuestionStatus('presenting', 'Présentation en cours…');

    if (this.components.slideViewer) {
      this.components.slideViewer.updateHeader(courseTitle, chapterTitle);
      this.components.slideViewer.displaySlide(sectionTitle, narration, imageUrl);
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
    const { audio_data, mime_type, is_final, turn_id } = data;
    const kind = turn_id !== null && turn_id !== undefined ? 'answer' : 'presentation';

    if (audio_data) {
      if (data.clip !== false) {
        audioManager.enqueueAudioClip(audio_data, mime_type, kind);
      } else {
        audioManager.bufferAudioChunk(audio_data, mime_type, is_final, data.stream_id, turn_id);
      }
    }

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

    if (this.components.qaPanel && is_final) {
      this.components.qaPanel.addMessage(text, 's', label || 'Étudiant');
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

    const nextStatus = stateManager.activePanel === 'qa' ? 'responding' : 'presenting';
    this._setQuestionStatus(nextStatus, answerText ? 'Réponse reçue' : 'Présentation');

    if (reasoningTrace.length) {
      const lastStage = reasoningTrace[reasoningTrace.length - 1] || {};
      stateManager.setState('lastStateMain', (lastStage.state || 'idle').toLowerCase());
      stateManager.setState('lastSubstep', lastStage.summary || lastStage.title || null);
    }

    if (reasoningTrace.length) {
      console.log('Reasoning:', reasoningTrace);
    }
  }

  _handleStatusUpdate(data) {
    const { state, message, reasoning_step: reasoningStep } = data;

    const stateMap = {
      idle: 'idle',
      listening: 'listening',
      processing: 'processing',
      responding: 'responding',
      presenting: 'presenting',
    };

    const mappedState = stateMap[state] || 'idle';
    this.components.slideViewer?.setWaveformState(mappedState);
    this.components.chatPanel?.setStatus(mappedState, message);
    this.components.qaPanel?.setStatus(mappedState, message);

    if (reasoningStep) {
      this.components.chatPanel?.appendReasoningStep?.(reasoningStep);
      if (typeof this.components.chatPanel?.expand === 'function') {
        this.components.chatPanel.expand();
      }
      this.components.qaPanel?.appendReasoningStep?.(reasoningStep);
    }
  }

  _handleInterrupt(data) {
    audioManager.stopAudio();
    const isSpeechInterrupt = data?.reason === 'student_speaking';
    this.components.slideViewer?.setWaveformState(isSpeechInterrupt ? 'listening' : 'off');
    this._setQuestionStatus(
      isSpeechInterrupt ? 'listening' : 'idle',
      isSpeechInterrupt ? 'Interruption détectée' : 'Lecture interrompue'
    );
  }

  async askQuestion(text) {
    this._interruptCurrentPlayback('typed_question');

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
      turn_id: stateManager.activeQuestionTurnId,
    });

    return true;
  }

  async selectCourse(courseId, course = null) {
    const selectedCourse = course || this.components.courseSelector?.courses?.find((item) => item.id === courseId) || stateManager.course;
    const courseLanguage = selectedCourse?.language || wsClient.sessionLanguage || 'fr';

    this._interruptCurrentPlayback('course_change');

    stateManager.setState('courseId', courseId);
    if (selectedCourse) {
      stateManager.setState('course', selectedCourse);
    }
    stateManager.setState('chapterIndex', 0);
    stateManager.setState('sectionIndex', 1);
    stateManager.setState('activePanel', 'course');

    this.components.header?.enableQuizButton();

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

    if (!this._ensureRealtimeSessionStarted()) {
      UIManager.showNotification('Session non initialisée, réessaie dans quelques secondes.', 'warning');
      return false;
    }

    wsClient.send({
      type: 'start_presentation',
      course_id: courseId,
      chapter_index: 0,
      section_index: 0,
      language: courseLanguage,
    });

    return true;
  }

  pause() {
    stateManager.setState('paused', true);
    const playbackSnapshot = this._interruptCurrentPlayback('user_pause');

    if (!wsClient.isConnected()) {
      return false;
    }

    wsClient.send({
      type: 'pause',
      reason: 'user_request',
      playback_snapshot: playbackSnapshot,
    });
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

    if (!this._ensureRealtimeSessionStarted()) {
      UIManager.showNotification('Session non initialisée, impossible de changer la slide.', 'warning');
      return false;
    }

    this._interruptCurrentPlayback('slide_change');

    const nextSectionIndex = (stateManager.sectionIndex || 0) + 1;
    stateManager.setState('sectionIndex', nextSectionIndex);

    wsClient.send({
      type: 'start_presentation',
      course_id: stateManager.courseId,
      chapter_index: stateManager.chapterIndex || 0,
      section_index: nextSectionIndex,
      language: wsClient.sessionLanguage || stateManager.course?.language || 'fr',
    });

    return true;
  }

  previousSlide() {
    if (!wsClient.isConnected()) {
      return false;
    }

    if (!this._ensureRealtimeSessionStarted()) {
      UIManager.showNotification('Session non initialisée, impossible de changer la slide.', 'warning');
      return false;
    }

    this._interruptCurrentPlayback('slide_change');

    const previousSectionIndex = Math.max(0, (stateManager.sectionIndex || 0) - 1);
    stateManager.setState('sectionIndex', previousSectionIndex);

    wsClient.send({
      type: 'start_presentation',
      course_id: stateManager.courseId,
      chapter_index: stateManager.chapterIndex || 0,
      section_index: previousSectionIndex,
      language: wsClient.sessionLanguage || stateManager.course?.language || 'fr',
    });

    return true;
  }

  _normalizeReasoningTrace(reasoning) {
    if (!reasoning) return [];
    if (Array.isArray(reasoning)) return reasoning;
    if (Array.isArray(reasoning.steps)) return reasoning.steps;
    if (Array.isArray(reasoning.trace)) return reasoning.trace;
    if (Array.isArray(reasoning.stages)) return reasoning.stages;
    return [];
  }

  _normalizeImageUrl(url) {
    if (!url) return null;

    const value = String(url).trim();
    if (/^(https?:)?\/\//i.test(value) || value.startsWith('/') || value.startsWith('data:')) {
      return value;
    }

    return null;
  }

  _restoreStudentContext() {
    const studentId = localStorage.getItem('student_id') || '';
    const studentEmail = localStorage.getItem('student_email') || '';
    const studentName = localStorage.getItem('student_name') || '';

    if (studentId) {
      stateManager.setState('studentId', studentId);
    }
    if (studentEmail) {
      stateManager.setState('studentEmail', studentEmail);
    }
    if (studentName) {
      stateManager.setState('studentName', studentName);
    }
  }

  _storeStudentContext(student = {}) {
    const id = String(student.id || '').trim();
    const email = String(student.email || '').trim();
    const firstName = String(student.first_name || '').trim();

    if (id) {
      localStorage.setItem('student_id', id);
      stateManager.setState('studentId', id);
    }
    if (email) {
      localStorage.setItem('student_email', email);
      stateManager.setState('studentEmail', email);
    }
    if (firstName) {
      localStorage.setItem('student_name', firstName);
      stateManager.setState('studentName', firstName);
    }
  }

  _clearStudentContext() {
    localStorage.removeItem('student_id');
    localStorage.removeItem('student_email');
    localStorage.removeItem('student_name');
    localStorage.removeItem('auth_token');
    stateManager.setState('studentId', null);
    stateManager.setState('studentEmail', '');
    stateManager.setState('studentName', '');
  }

  _exposeAuthHelpers() {
    this.auth = {
      register: async (payload) => {
        const response = await fetch('/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `Register failed (${response.status})`);
        }
        localStorage.setItem('auth_token', data.token || '');
        this._storeStudentContext(data.student || {});
        UIManager.showNotification('Compte cree avec succes', 'success');
        return data;
      },
      login: async (email, password) => {
        const response = await fetch('/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `Login failed (${response.status})`);
        }
        localStorage.setItem('auth_token', data.token || '');
        this._storeStudentContext(data.student || {});
        UIManager.showNotification('Connexion reussie', 'success');
        return data;
      },
      me: async () => {
        const token = localStorage.getItem('auth_token') || '';
        if (!token) {
          throw new Error('Aucun token de connexion');
        }
        const response = await fetch('/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.detail || `Me failed (${response.status})`);
        }
        this._storeStudentContext(data.student || {});
        return data;
      },
      logout: () => {
        this._clearStudentContext();
        UIManager.showNotification('Deconnexion effectuee', 'info');
      },
    };
  }

  _ensureRealtimeSessionStarted() {
    if (!wsClient.isConnected()) return false;
    if (wsClient.sessionStarted) return true;
    return wsClient.startSession(
      wsClient.sessionLanguage || stateManager.course?.language || 'fr',
      wsClient.sessionLevel || stateManager.course?.level || 'lycée'
    );
  }
  _normalizeReasoningTrace(trace) {
    if (!Array.isArray(trace)) return [];
    return trace.filter(step => step && typeof step === 'object');
  }
  async _loadStudentProfile() {
    const token = localStorage.getItem('token');
    
    if (!token) {
        this.components.header?.updateProfile({ name: 'Invité', level: 'lycée', language: 'fr' });
        return;
    }
    
    try {
        const response = await fetch('/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        
        if (response.ok) {
            const data = await response.json();
            const student = data.student || {};
            const lp = data.learning_profile || {};
            
            stateManager.studentId = student.id || '';
            stateManager.studentName = student.first_name || 'Étudiant';
            
            this.components.header?.updateProfile({
                name: (student.first_name || '') + ' ' + (student.last_name || ''),
                level: lp.level || student.account_level || 'lycée',
                language: lp.language || student.preferred_language || 'fr',
            });
            
            // Sync session language to student preference
            if (lp.language || student.preferred_language) {
                wsClient.sessionLanguage = lp.language || student.preferred_language;
            }
            wsClient.sessionLevel = lp.level || 'lycée';
            localStorage.setItem('student_id', student.id || '');
            
        } else {
            // Token invalid
            localStorage.removeItem('token');
            this.components.header?.updateProfile({ name: 'Invité', level: 'lycée', language: 'fr' });
        }
    } catch (err) {
        console.warn('Profile load failed:', err);
        this.components.header?.updateProfile({ name: 'Invité', level: 'lycée', language: 'fr' });
    }
  }
}

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