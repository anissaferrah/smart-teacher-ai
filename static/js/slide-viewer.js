/**
 * Slide Viewer Component
 * Displays slides, controls, and progress
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';
import { audioManager } from '../modules/audio-manager.js';

export class SlideViewer extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.onNext = null;
    this.onPrev = null;
    this.onPause = null;
  }

  render() {
    const content = `
      <div class="slide-hdr">
        <div class="slide-course" id="slideCourseName">Aucun cours</div>
        <div class="slide-chapter" id="slideChapter">—</div>
        <div class="prog-bar"><div class="prog-fill" id="progressBar"></div></div>
      </div>

      <div class="slide-body" id="slideBody">
        <div class="slide-empty">
          <div class="slide-icon">📖</div>
          <p class="slide-title">Aucune présentation chargée</p>
          <p class="slide-text">Sélectionnez un cours dans <strong>Mes Cours</strong> pour commencer</p>
        </div>
      </div>

      <div class="wave-row">
        <div class="wave-lbl" id="wlbl">En attente</div>
        <div class="waveform" id="wf"></div>
      </div>

      <div class="ctrl-row">
        <button class="btn btn-grn feature-hidden" id="autoPlayBtn" disabled>Lecture automatique</button>
        <button class="btn btn-blu feature-hidden" id="explainBtn" disabled>🎓 Expliquer</button>
        <button class="btn btn-o btn-primary" id="prevSlideBtn" disabled>◀</button>
        <button class="btn btn-pau btn-primary" id="pauseBtn" disabled>⏸ Pause</button>
        <button class="btn btn-o btn-primary" id="nextSlideBtn" disabled>▶</button>
        <button class="btn btn-grn" id="askQuestionBtn" disabled>🎤 Question</button>
      </div>
    `;

    if (this.container.classList.contains('slide-area')) {
      this.container.innerHTML = content;
    } else {
      this.container.innerHTML = `<div class="slide-area">${content}</div>`;
    }

    this._attachListeners();
    audioManager.initWaveform();
  }

  _attachListeners() {
    this.query('#nextSlideBtn')?.addEventListener('click', () => this.next());
    this.query('#prevSlideBtn')?.addEventListener('click', () => this.prev());
    this.query('#pauseBtn')?.addEventListener('click', () => this.togglePause());
    this.query('#autoPlayBtn')?.addEventListener('click', () => this.toggleAutoPlay());
    this.query('#explainBtn')?.addEventListener('click', () => this.requestExplanation());
    this.query('#askQuestionBtn')?.addEventListener('click', () => this.startRecording());
  }

  displaySlide(title, text, imageUrl = null) {
    const slideBody = this.query('#slideBody');
    if (!slideBody) return;

    if (imageUrl) {
      slideBody.innerHTML = `<img src="${imageUrl}" alt="${title}">`;
    } else {
      slideBody.innerHTML = `
        <div style="text-align:center;padding:40px 20px">
          <div class="slide-icon">📄</div>
          <h2 class="slide-title">${title}</h2>
          <p class="slide-text">${text}</p>
        </div>
      `;
    }
  }

  updateHeader(courseName, chapterTitle) {
    const courseName_ = this.query('#slideCourseName');
    if (courseName_) courseName_.textContent = courseName || 'Aucun cours';

    const chapter = this.query('#slideChapter');
    if (chapter) chapter.textContent = chapterTitle || '—';
  }

  updateProgress(current, total) {
    if (total === 0) total = 1;
    const percentage = (current / total) * 100;
    const progressBar = this.query('#progressBar');
    if (progressBar) progressBar.style.width = percentage + '%';
  }

  next() {
    stateManager.setState('sectionIndex', stateManager.sectionIndex + 1);
    if (this.onNext) this.onNext();
  }

  prev() {
    stateManager.setState('sectionIndex', Math.max(0, stateManager.sectionIndex - 1));
    if (this.onPrev) this.onPrev();
  }

  togglePause() {
    const isPaused = stateManager.paused;
    stateManager.setState('paused', !isPaused);

    const btn = this.query('#pauseBtn');
    if (btn) {
      btn.textContent = isPaused ? '⏸ Pause' : '▶ Reprendre';
    }

    if (this.onPause) this.onPause(!isPaused);
  }

  toggleAutoPlay() {
    const autoPlay = stateManager.autoPlay;
    stateManager.setState('autoPlay', !autoPlay);

    const btn = this.query('#autoPlayBtn');
    if (btn) {
      btn.classList.toggle('active', !autoPlay);
    }
  }

  requestExplanation() {
    // Emit event to request explanation from AI
    const event = new CustomEvent('request-explanation', {
      detail: { slide: stateManager.slideTitle }
    });
    window.dispatchEvent(event);
  }

  startRecording() {
    const event = new CustomEvent('start-recording');
    window.dispatchEvent(event);
  }

  enableControls() {
    const btns = ['nextSlideBtn', 'prevSlideBtn', 'pauseBtn', 'askQuestionBtn', 'autoPlayBtn', 'explainBtn'];
    btns.forEach((btn) => {
      const el = this.query(`#${btn}`);
      if (el) el.disabled = false;
    });
  }

  disableControls() {
    const btns = ['nextSlideBtn', 'prevSlideBtn', 'pauseBtn', 'askQuestionBtn', 'autoPlayBtn', 'explainBtn'];
    btns.forEach((btn) => {
      const el = this.query(`#${btn}`);
      if (el) el.disabled = true;
    });
  }

  setWaveformState(state) {
    audioManager.animateWaveform(state);
  }

  update(data) {
    if (data.slide) {
      this.displaySlide(data.slide.title, data.slide.text, data.slide.imageUrl);
    }
    if (data.header) {
      this.updateHeader(data.header.course, data.header.chapter);
    }
    if (data.progress) {
      this.updateProgress(data.progress.current, data.progress.total);
    }
  }
}

export default SlideViewer;
