/**
 * QA Panel Component
 * Q&A interface with message history
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';

export class QAPanel extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.onSendQuestion = null;
    this.recordingActive = false;
    this.reasoningTrace = [];
  }

  render() {
    const content = `
      <div class="reasoning-shell" id="qaReasoningShell" hidden>
        <div class="reasoning-head">
          <span id="qaReasoningTitle">Suivi du traitement</span>
          <span class="reasoning-count" id="qaReasoningCount">0 étape</span>
        </div>
        <div class="reasoning-list" id="qaReasoningList"></div>
      </div>

      <div class="qa-msgs" id="qaMessages">
        <div class="msg msg-t">
          <div class="msg-lbl">Professeur</div>
          <div class="msg-body">Bonjour ! Posez-moi n'importe quelle question. Je suis là pour vous aider !</div>
        </div>
      </div>

      <div class="state-bar">
        <div class="sd" id="qaStatus"></div>
        <span id="qaStatusText">En attente</span>
      </div>

      <div class="inp-row">
        <input class="ci" id="qaInput" placeholder="Posez votre question…" autocomplete="off">
        <button class="btn btn-p" id="qaSendBtn">Envoyer</button>
        <button class="mic-b" id="qaMicBtn">🎤</button>
      </div>
    `;

    if (this.container.classList.contains('qa-panel')) {
      this.container.innerHTML = content;
    } else {
      this.container.innerHTML = `<div class="qa-panel">${content}</div>`;
    }

    this._attachListeners();
  }

  setReasoningTrace(trace = []) {
    const steps = Array.isArray(trace)
      ? trace.map((step) => this._normalizeReasoningStep(step)).filter(Boolean)
      : [];

    this.reasoningTrace = steps.sort((left, right) => this._compareReasoningSteps(left, right));
    this._syncReasoningMeta();
    this._renderReasoningTrace();
  }

  appendReasoningStep(step) {
    const normalized = this._normalizeReasoningStep(step);
    if (!normalized) {
      return;
    }

    const merged = [...this.reasoningTrace];
    const key = this._reasoningStepKey(normalized);
    const index = merged.findIndex((item) => this._reasoningStepKey(item) === key);

    if (index >= 0) {
      merged[index] = { ...merged[index], ...normalized };
    } else {
      merged.push(normalized);
    }

    this.setReasoningTrace(merged);
  }

  clearReasoningTrace() {
    this.setReasoningTrace([]);
  }

  _attachListeners() {
    this.query('#qaSendBtn')?.addEventListener('click', () => this.sendQuestion());
    this.query('#qaInput')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.sendQuestion();
    });
    this.query('#qaMicBtn')?.addEventListener('click', () => this.toggleRecording());
  }

  addMessage(text, type = 't', label = '') {
    const msgs = this.query('#qaMessages');
    if (!msgs) return null;

    const msg = document.createElement('div');
    msg.className = 'msg msg-' + (type === 't' ? 't' : type === 's' ? 's' : 'sys');

    if (label && label.trim()) {
      const labelEl = document.createElement('div');
      labelEl.className = 'msg-lbl';
      labelEl.textContent = this._normalizeLabel(label);
      msg.appendChild(labelEl);
    }

    const body = document.createElement('div');
    body.className = 'msg-body';
    
    // Handle markdown-like formatting
    if (type === 't' && text.includes('\n')) {
      body.innerHTML = text
        .split('\n')
        .map((line) => {
          if (line.startsWith('• ')) {
            return `<li>${line.substring(2)}</li>`;
          }
          return line;
        })
        .join('<br>');
    } else {
      body.textContent = text;
    }
    
    msg.appendChild(body);
    msgs.appendChild(msg);
    msgs.scrollTop = msgs.scrollHeight;

    return msg;
  }

  _normalizeLabel(label) {
    const value = (label || '').trim().toLowerCase();
    if (value === 'teacher' || value === 'professeur') return 'Professeur';
    if (value === 'student' || value === 'étudiant' || value.startsWith('voice')) return 'Vous';
    if (value === 'system' || value === 'sys') return 'Système';
    return (label || '').trim();
  }

  clearMessages() {
    const msgs = this.query('#qaMessages');
    if (msgs) {
      msgs.innerHTML = '<div class="msg msg-t"><div class="msg-lbl">Professeur</div><div class="msg-body">Posez votre première question!</div></div>';
    }
  }

  setStatus(state, text) {
    const dot = this.query('#qaStatus');
    if (dot) {
      dot.className = 'sd';
      if (state === 'listening') dot.classList.add('li');
      if (state === 'processing') dot.classList.add('po');
      if (state === 'responding') dot.classList.add('pr');
    }

    const statusText = this.query('#qaStatusText');
    if (statusText) {
      const labels = {
        'idle': 'En attente',
        'listening': 'Écoute',
        'processing': 'Traitement',
        'responding': 'Réponse',
        'presenting': 'Présentation'
      };
      statusText.textContent = text || labels[state] || 'En attente';
    }
  }

  sendQuestion() {
    const input = this.query('#qaInput');
    if (!input) return;

    const text = input.value.trim();
    if (!text) return;

    this.clearReasoningTrace();

    // Add user message
    this.addMessage(text, 's', 'Vous');

    // Update status
    this.setStatus('processing', 'Traitement…');

    // Emit event
    if (this.onSendQuestion) {
      this.onSendQuestion(text);
    }

    // Clear input
    input.value = '';
    input.focus();
  }

  toggleRecording() {
    this.recordingActive = !this.recordingActive;
    const btn = this.query('#qaMicBtn');
    if (btn) {
      btn.classList.toggle('recording', this.recordingActive);
      btn.style.opacity = this.recordingActive ? '1' : '0.6';
    }

    if (this.recordingActive) {
      this.clearReasoningTrace();
    }

    this.setStatus(this.recordingActive ? 'listening' : 'idle', this.recordingActive ? 'Enregistrement…' : 'En attente');

    // Emit event
    const event = new CustomEvent('qa-recording-toggled', {
      detail: { active: this.recordingActive }
    });
    window.dispatchEvent(event);
  }

  stopRecording() {
    if (this.recordingActive) {
      this.recordingActive = false;
      const btn = this.query('#qaMicBtn');
      if (btn) {
        btn.classList.remove('recording');
        btn.style.opacity = '0.6';
      }
    }
  }

  setInputDisabled(disabled) {
    const input = this.query('#qaInput');
    if (input) input.disabled = disabled;

    const btn = this.query('#qaSendBtn');
    if (btn) btn.disabled = disabled;

    const mic = this.query('#qaMicBtn');
    if (mic) mic.disabled = disabled;
  }

  update(data) {
    if (data.messages) {
      this.clearMessages();
      data.messages.forEach((msg) => {
        this.addMessage(msg.text, msg.type, msg.label);
      });
    }
    if (data.status) {
      this.setStatus(data.status, data.statusText);
    }
  }

  _normalizeState(step) {
    return String(step?.state || step?.dialog_state || step?.system_state || 'idle').toLowerCase();
  }

  _syncReasoningMeta() {
    const latest = this.reasoningTrace[this.reasoningTrace.length - 1] || {};

    if (this.reasoningTrace.length) {
      const normalizedState = this._normalizeState(latest);
      stateManager.setState('lastStateMain', normalizedState);
      stateManager.setState('lastSubstep', latest?.summary || latest?.title || null);
      this.setStatus(normalizedState, latest?.summary || latest?.title || 'En cours');
    } else {
      stateManager.setState('lastStateMain', null);
      stateManager.setState('lastSubstep', null);
      this.setStatus('idle', 'En attente');
    }
  }

  _renderReasoningTrace() {
    const shell = this.query('#qaReasoningShell');
    const title = this.query('#qaReasoningTitle');
    const count = this.query('#qaReasoningCount');
    const list = this.query('#qaReasoningList');

    if (!shell || !title || !count || !list) {
      return;
    }

    if (!this.reasoningTrace.length) {
      shell.hidden = true;
      title.textContent = 'Suivi du traitement';
      count.textContent = '0 étape';
      list.innerHTML = '';
      return;
    }

    shell.hidden = false;
    const hasRunningStep = this.reasoningTrace.some((step) => this._isReasoningRunning(step));
    title.textContent = hasRunningStep ? 'Traitement en cours…' : 'Trace du traitement';
    count.textContent = `${this.reasoningTrace.length} étape${this.reasoningTrace.length > 1 ? 's' : ''}`;
    list.innerHTML = this.reasoningTrace
      .map((step, index) => this._renderReasoningBlock(step, index))
      .join('');
    list.scrollTop = list.scrollHeight;
  }

  _renderReasoningBlock(step, index) {
    const stepNumber = Number.isFinite(Number(step?.step)) ? Number(step.step) : index + 1;
    const status = String(step?.status || 'done').toLowerCase();
    const stateLabel = this._formatReasoningState(step);
    const statusLabel = this._formatReasoningStatus(status);
    const detailText = this._formatReasoningDetails(step?.details);
    const durationText = Number.isFinite(Number(step?.duration_ms)) && Number(step.duration_ms) > 0
      ? `${Number(step.duration_ms).toFixed(1)} ms`
      : '';
    const confidenceText = Number.isFinite(Number(step?.confidence))
      ? `${Math.round(Number(step.confidence) * 100)}%`
      : '';
    const statusClass =
      status === 'done'
        ? 'reasoning-status-done'
        : status === 'skipped'
          ? 'reasoning-status-skipped'
          : status === 'failed'
            ? 'reasoning-status-failed'
            : '';
    const runningStyle = this._isReasoningRunning(step)
      ? ' style="border-color: rgba(0, 229, 176, 0.34); box-shadow: 0 0 0 1px rgba(0, 229, 176, 0.08) inset;"'
      : '';

    return `
      <div class="reasoning-block ${statusClass}"${runningStyle}>
        <div class="reasoning-top">
          <div>
            <div class="reasoning-title">${this._escapeHtml(step?.title || step?.key || `Étape ${stepNumber}`)}</div>
            <div class="reasoning-sub">${this._escapeHtml(step?.summary || 'En cours')}</div>
          </div>
          <div class="reasoning-time">${this._escapeHtml(durationText)}</div>
        </div>
        <div class="reasoning-badges">
          <span class="reasoning-chip reasoning-chip-state">${this._escapeHtml(`Étape ${stepNumber}`)}</span>
          <span class="reasoning-chip reasoning-chip-state">${this._escapeHtml(stateLabel)}</span>
          <span class="reasoning-chip reasoning-chip-status">${this._escapeHtml(statusLabel)}</span>
          ${confidenceText ? `<span class="reasoning-chip reasoning-chip-confidence">${this._escapeHtml(`Confiance ${confidenceText}`)}</span>` : ''}
        </div>
        ${detailText ? `<div class="reasoning-detail">${this._escapeHtml(detailText)}</div>` : ''}
      </div>
    `;
  }

  _normalizeReasoningStep(step) {
    if (!step || typeof step !== 'object') {
      return null;
    }

    const normalizedStep = { ...step };
    if (normalizedStep.step !== undefined && normalizedStep.step !== null && normalizedStep.step !== '') {
      const parsedStep = Number(normalizedStep.step);
      normalizedStep.step = Number.isFinite(parsedStep) ? parsedStep : null;
    } else {
      normalizedStep.step = null;
    }

    normalizedStep.key = normalizedStep.key || normalizedStep.title || normalizedStep.summary || '';
    normalizedStep.title = normalizedStep.title || normalizedStep.key || '';
    normalizedStep.summary = normalizedStep.summary || normalizedStep.title || '';
    normalizedStep.state = this._normalizeState(normalizedStep);
    normalizedStep.status = String(normalizedStep.status || 'done').toLowerCase();

    if (normalizedStep.duration_ms !== undefined && normalizedStep.duration_ms !== null && normalizedStep.duration_ms !== '') {
      const parsedDuration = Number(normalizedStep.duration_ms);
      normalizedStep.duration_ms = Number.isFinite(parsedDuration) ? parsedDuration : null;
    } else {
      normalizedStep.duration_ms = null;
    }

    if (normalizedStep.confidence !== undefined && normalizedStep.confidence !== null && normalizedStep.confidence !== '') {
      const parsedConfidence = Number(normalizedStep.confidence);
      normalizedStep.confidence = Number.isFinite(parsedConfidence) ? parsedConfidence : null;
    } else {
      normalizedStep.confidence = null;
    }

    return normalizedStep;
  }

  _reasoningStepKey(step) {
    if (!step || typeof step !== 'object') {
      return '';
    }

    if (Number.isFinite(Number(step.step))) {
      return `step:${Number(step.step)}`;
    }

    return `key:${String(step.key || step.title || step.summary || '').trim().toLowerCase()}`;
  }

  _compareReasoningSteps(left, right) {
    const leftStep = Number.isFinite(Number(left?.step)) ? Number(left.step) : Number.MAX_SAFE_INTEGER;
    const rightStep = Number.isFinite(Number(right?.step)) ? Number(right.step) : Number.MAX_SAFE_INTEGER;

    if (leftStep !== rightStep) {
      return leftStep - rightStep;
    }

    return String(left?.key || left?.title || '').localeCompare(String(right?.key || right?.title || ''));
  }

  _isReasoningRunning(step) {
    const status = String(step?.status || '').toLowerCase();
    return ['running', 'in_progress', 'processing'].includes(status);
  }

  _formatReasoningState(step) {
    const value = String(step?.state || step?.dialog_state || step?.system_state || 'idle').toLowerCase();
    const labels = {
      idle: 'Attente',
      listening: 'Écoute',
      processing: 'Traitement',
      presenting: 'Présentation',
      responding: 'Réponse',
    };

    return labels[value] || value;
  }

  _formatReasoningStatus(status) {
    const labels = {
      running: 'En cours',
      done: 'Terminé',
      skipped: 'Ignoré',
      failed: 'Erreur',
    };

    return labels[String(status || '').toLowerCase()] || 'En cours';
  }

  _formatReasoningDetails(details) {
    if (!details) {
      return '';
    }

    if (typeof details === 'string') {
      return details;
    }

    try {
      return JSON.stringify(details, null, 2);
    } catch (_) {
      return String(details);
    }
  }

  _escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

export default QAPanel;
