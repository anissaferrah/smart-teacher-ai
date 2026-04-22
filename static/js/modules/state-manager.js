/**
 * State Manager Module
 * Centralized state management for Smart Teacher
 * Replaces global variables with pub/sub pattern
 */

class StateManager {
  constructor() {
    // Session & course state
    this.sessionId = null;
    this.studentId = null;
    this.studentEmail = '';
    this.studentName = '';
    this.course = null;
    this.courseId = null;
    this.chapterIndex = 0;
    this.sectionIndex = 0;

    // Presentation state
    this.paused = false;
    this.autoPlay = true;
    this.activePanel = 'course';
    this.courseSelectorOpen = false;

    // Slide state
    this.slideTitle = '';
    this.slideText = '';
    this.slidePageNum = 0;
    this.slidePath = '';
    this.slideDomain = '';
    this.slideCourse = '';

    // Audio state
    this.currentAudio = null;
    this.audioBuffer = [];
    this.audioQueue = [];
    this.audioQueueKinds = [];
    this.currentAudioKind = null;
    this.answerAudioPaused = false;

    // Recording state
    this.recording = false;
    this.mediaRecorder = null;
    this.audioChunks = [];

    // Chat state
    this.activeQuestionTurnId = 0;
    this.questionTurnSeq = 0;
    this.lastStateMain = null;
    this.lastSubstep = null;

    // Saved position state
    this.savedChapterIndex = null;
    this.savedSectionIndex = null;

    // Metrics state
    this.presentationMetrics = null;
    this.questionMetrics = null;
    this.finalMetrics = null;

    // Subscribers for state changes
    this._subscribers = new Map();
  }

  // Subscribe to state changes
  subscribe(key, callback) {
    if (!this._subscribers.has(key)) {
      this._subscribers.set(key, []);
    }
    this._subscribers.get(key).push(callback);
    return () => {
      const callbacks = this._subscribers.get(key);
      const index = callbacks.indexOf(callback);
      if (index > -1) callbacks.splice(index, 1);
    };
  }

  // Notify subscribers
  _notify(key, value) {
    if (this._subscribers.has(key)) {
      this._subscribers.get(key).forEach(cb => cb(value));
    }
  }

  // Set state property and notify
  setState(key, value) {
    const oldValue = this[key];
    if (oldValue === value) return;
    this[key] = value;
    this._notify(key, value);
  }

  // Get state property
  getState(key) {
    return this[key];
  }

  // Update multiple state properties
  updateState(updates) {
    Object.entries(updates).forEach(([key, value]) => {
      this.setState(key, value);
    });
  }

  // Reset to initial state
  reset() {
    this.course = null;
    this.courseId = null;
    this.chapterIndex = 0;
    this.sectionIndex = 0;
    this.paused = false;
    this.slideTitle = '';
    this.slideText = '';
    this.slidePath = '';
    this.audioBuffer = [];
    this.audioQueue = [];
    this.audioQueueKinds = [];
    this.currentAudioKind = null;
    this.answerAudioPaused = false;
    this.activeQuestionTurnId = 0;
    this.lastStateMain = null;
    this.lastSubstep = null;
  }

  // Serialize state to object
  toJSON() {
    return {
      sessionId: this.sessionId,
      courseId: this.courseId,
      chapterIndex: this.chapterIndex,
      sectionIndex: this.sectionIndex,
      paused: this.paused,
      autoPlay: this.autoPlay,
      activePanel: this.activePanel,
      slideTitle: this.slideTitle,
      slidePath: this.slidePath,
      questionTurnSeq: this.questionTurnSeq,
    };
  }
}

// Singleton instance
export const stateManager = new StateManager();

// Initialize session ID
stateManager.sessionId = crypto.randomUUID();

export default stateManager;
