/**
 * Smart Teacher Application
 * Main entry point - initializes all modules and components
 */

import { stateManager } from './modules/state-manager.js';
import { wsClient } from './modules/ws-client.js';
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

      // Connect to WebSocket
      wsClient.connect();
      console.log('✅ WebSocket connection initiated');

      // Initialize audio waveform
      audioManager.initWaveform();
      console.log('✅ Audio waveform initialized');

      this.initialized = true;
      console.log('🎉 Application ready!');

      // Start session after short delay
      setTimeout(() => {
        wsClient.startSession('fr', 'lycée');
      }, 1000);
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

    this.components.chatPanel = new ChatPanel('chatPanelContainer');
    this.components.chatPanel.render();

    this.components.courseSelector = new CourseSelector('courseSelectorContainer');
    this.components.courseSelector.render();

    this.components.qaPanel = new QAPanel('qaPanelContainer');
    this.components.qaPanel.render();

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

    wsClient.on('audio_stream', (data) => {
      this._handleAudioStream(data);
    });

    wsClient.on('transcription', (data) => {
      this._handleTranscription(data);
    });

    wsClient.on('response', (data) => {
      this._handleResponse(data);
    });

    wsClient.on('status_update', (data) => {
      this._handleStatusUpdate(data);
    });
  }

  _handleSlideData(data) {
    const { title, text, image_url, chapter, section, total_sections } = data;
    
    stateManager.setState('slideTitle', title);
    stateManager.setState('slideText', text);
    
    if (this.components.slideViewer) {
      this.components.slideViewer.displaySlide(title, text, image_url);
      this.components.slideViewer.updateHeader(
        stateManager.course?.name || 'Aucun cours',
        chapter || 'Chapitre'
      );
      this.components.slideViewer.updateProgress(section || 0, total_sections || 1);
    }
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
    const { text, label, reasoning } = data;
    
    if (this.components.chatPanel) {
      this.components.chatPanel.addMessage(text, 't', label || 'Professeur');
      
      if (reasoning && reasoning.steps) {
        console.log('Reasoning:', reasoning.steps);
      }
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

  // Public API for manual interactions
  async askQuestion(text) {
    wsClient.send({
      type: 'question',
      text,
      course_id: stateManager.courseId,
      turn_id: stateManager.activeQuestionTurnId
    });
  }

  async selectCourse(courseId) {
    wsClient.send({
      type: 'select_course',
      course_id: courseId
    });
  }

  pause() {
    stateManager.setState('paused', true);
  }

  resume() {
    stateManager.setState('paused', false);
  }

  nextSlide() {
    stateManager.setState('sectionIndex', stateManager.sectionIndex + 1);
  }

  previousSlide() {
    stateManager.setState('sectionIndex', Math.max(0, stateManager.sectionIndex - 1));
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
