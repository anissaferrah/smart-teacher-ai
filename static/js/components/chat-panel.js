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
}

export default ChatPanel;
