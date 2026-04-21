/**
 * Chat Panel Component
 * Displays messages and handles message input
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';

export class ChatPanel extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.onSendMessage = null;
    this.isCollapsed = true;
    this.reasoningTrace = [];
  }

  render() {
    const content = `
      <div class="chat-lbl" id="chatToggle">
        <span>Transcription &amp; Réponses</span>
        <span id="chatToggleIcon">▶</span>
      </div>
      <div class="chat-msgs" id="cChat"></div>
      <div class="state-bar">
        <div class="sd" id="chatStatus"></div>
        <span id="chatStatusText">En attente</span>
      </div>

      <div class="reasoning-shell">
        <div class="reasoning-head">
          <span>Blocs de raisonnement</span>
          <span class="reasoning-count" id="chatReasoningCount">Aucun bloc</span>
        </div>
        <div class="reasoning-list" id="chatReasoningBlocks">
          <div class="reasoning-empty">Le système affichera ici ses étapes de traitement.</div>
        </div>
      </div>

      <div class="inp-row">
        <input class="ci" id="chatInput" placeholder="Question écrite…" autocomplete="off">
        <button class="btn btn-p" id="chatSendBtn">↵</button>
      </div>
    `;

    if (this.container.classList.contains('chat-col')) {
      this.container.innerHTML = content;
    } else {
      this.container.innerHTML = `<div class="chat-col collapsed" id="chatColumn">${content}</div>`;
    }

    this._attachListeners();
  }

  setReasoningTrace(trace = []) {
    const steps = Array.isArray(trace) ? trace.filter(Boolean) : [];
    this.reasoningTrace = steps;

    const count = this.query('#chatReasoningCount');
    if (count) {
      count.textContent = steps.length ? `${steps.length} blocs` : 'Aucun bloc';
    }

    const container = this.query('#chatReasoningBlocks');
    if (!container) return;

    if (!steps.length) {
      container.innerHTML = '<div class="reasoning-empty">Le système affichera ici ses étapes de traitement.</div>';
      stateManager.setState('lastStateMain', null);
      stateManager.setState('lastSubstep', null);
      return;
    }

    container.innerHTML = steps.map((step, index) => {
      const state = this._normalizeState(step);
      const status = String(step?.status || 'done').toLowerCase();
      const title = this._escapeHtml(step?.title || step?.label || step?.stage || `Étape ${index + 1}`);
      const summary = this._escapeHtml(step?.summary || step?.message || '—');
      const duration = Number(step?.duration_ms ?? step?.duration ?? 0);
      const confidence = step?.confidence != null ? Number(step.confidence) : null;
      const details = step?.details || {};
      const detailParts = [];

      if (details.chunks != null) detailParts.push(`${details.chunks} chunks`);
      if (details.top_score != null) detailParts.push(`score ${Number(details.top_score).toFixed(2)}`);
      if (details.detected != null) detailParts.push(details.detected ? 'confusion détectée' : 'pas de confusion');
      if (details.answer_length != null) detailParts.push(`${details.answer_length} caractères`);
      if (details.audio_bytes != null) detailParts.push(`${details.audio_bytes} octets audio`);
      if (details.question_length != null) detailParts.push(`${details.question_length} caractères question`);
      if (details.rag_enabled === false) detailParts.push('RAG désactivé');

      if (details.answer_preview) {
        detailParts.push(`Aperçu: ${details.answer_preview}`);
      }

      const detailLine = detailParts.length ? this._escapeHtml(detailParts.join(' • ')) : '';

      return `
        <div class="reasoning-block reasoning-status-${status}" data-state="${this._escapeHtml(state)}">
          <div class="reasoning-top">
            <div>
              <div class="reasoning-title">${index + 1}. ${title}</div>
              <div class="reasoning-sub">${summary}</div>
            </div>
            <div class="reasoning-time">${duration ? `${duration.toFixed(0)} ms` : '—'}</div>
          </div>
          <div class="reasoning-badges">
            <span class="reasoning-chip reasoning-chip-state">${this._escapeHtml(state.toUpperCase())}</span>
            <span class="reasoning-chip reasoning-chip-status">${this._escapeHtml(status.toUpperCase())}</span>
            ${confidence != null ? `<span class="reasoning-chip reasoning-chip-confidence">CONF ${confidence.toFixed(2)}</span>` : ''}
          </div>
          ${detailLine ? `<div class="reasoning-detail">${detailLine}</div>` : ''}
        </div>
      `;
    }).join('');

    const latest = steps[steps.length - 1] || {};
    stateManager.setState('lastStateMain', this._normalizeState(latest));
    stateManager.setState('lastSubstep', latest?.summary || latest?.title || null);
  }

  clearReasoningTrace() {
    this.setReasoningTrace([]);
  }

  expand() {
    if (!this.isCollapsed) {
      return;
    }

    this.toggle();
  }

  collapse() {
    if (this.isCollapsed) {
      return;
    }

    this.toggle();
  }

  _attachListeners() {
    this.query('#chatToggle')?.addEventListener('click', () => this.toggle());
    this.query('#chatSendBtn')?.addEventListener('click', () => this.sendMessage());
    this.query('#chatInput')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.sendMessage();
    });
  }

  toggle() {
    this.isCollapsed = !this.isCollapsed;
    const col = this.container.classList.contains('chat-col') ? this.container : this.query('#chatColumn');
    if (col) {
      col.classList.toggle('collapsed', this.isCollapsed);
    }

    const icon = this.query('#chatToggleIcon');
    if (icon) {
      icon.textContent = this.isCollapsed ? '▶' : '◀';
    }
  }

  addMessage(text, type = 't', label = '') {
    const msgs = this.query('#cChat');
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
    body.textContent = text;
    msg.appendChild(body);

    msgs.appendChild(msg);
    msgs.scrollTop = msgs.scrollHeight;

    return msg;
  }

  _normalizeLabel(label) {
    const value = (label || '').trim().toLowerCase();
    if (value === 'teacher' || value === 'professeur') return 'Professeur';
    if (value === 'student' || value === 'étudiant' || value.startsWith('voice')) return 'Étudiant';
    if (value === 'system' || value === 'sys') return 'Système';
    return (label || '').trim();
  }

  clearMessages() {
    const msgs = this.query('#cChat');
    if (msgs) msgs.innerHTML = '';
  }

  setStatus(state, text) {
    const dot = this.query('#chatStatus');
    if (dot) {
      dot.className = 'sd';
      if (state === 'listening') dot.classList.add('li');
      if (state === 'processing') dot.classList.add('po');
      if (state === 'presenting') dot.classList.add('pr');
    }

    const statusText = this.query('#chatStatusText');
    if (statusText) {
      const labels = {
        'idle': 'En attente',
        'listening': 'Écoute',
        'processing': 'Traitement',
        'presenting': 'Présentation'
      };
      statusText.textContent = labels[state] || text || 'En attente';
    }
  }

  sendMessage() {
    const input = this.query('#chatInput');
    if (!input) return;

    const text = input.value.trim();
    if (!text) return;

    // Add message to chat
    this.addMessage(text, 's', 'Vous');

    // Emit event
    if (this.onSendMessage) {
      this.onSendMessage(text);
    }

    // Clear input
    input.value = '';
    input.focus();
  }

  setInputDisabled(disabled) {
    const input = this.query('#chatInput');
    if (input) input.disabled = disabled;

    const btn = this.query('#chatSendBtn');
    if (btn) btn.disabled = disabled;
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

  _escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

export default ChatPanel;
