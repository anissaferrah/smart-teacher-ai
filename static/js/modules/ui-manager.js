/**
 * UI Manager Module
 * DOM utilities and message rendering
 */

class UIManager {
  // Add message to chat area
  static addMessage(area, text, type = 't', label = '') {
    if (!area || !text) return null;

    const msg = document.createElement('div');
    msg.className = 'msg msg-' + (type === 't' ? 't' : type === 's' ? 's' : 'sys');

    if (label) {
      const labelEl = document.createElement('div');
      labelEl.className = 'msg-lbl';
      labelEl.textContent = UIManager.normalizeChatLabel(label);
      msg.appendChild(labelEl);
    }

    const body = document.createElement('div');
    body.className = 'msg-body';
    body.textContent = text;
    msg.appendChild(body);

    area.appendChild(msg);
    area.scrollTop = area.scrollHeight;
    return msg;
  }

  // Normalize chat label
  static normalizeChatLabel(label) {
    const value = (label || '').trim().toLowerCase();
    if (!value) return '';
    if (value === 'teacher') return 'Professeur';
    if (value === 'vous' || value.startsWith('voice')) return 'Étudiant';
    return (label || '').trim();
  }

  // Normalize system text
  static normalizeSystemText(text) {
    const value = (text || '').trim();
    if (!value) return '';

    const patterns = [
      /^Cours chargé\s*:/i,
      /^🔴?\s*Enregistrement/i,
      /Serveur:\s*Silero VAD/i,
      /^Pause\.?$/i,
      /^Reprise\.{3}$/i,
      /Point d['']arrêt mémorisé/i,
      /Reprise au point mémorisé/i,
      /Lecture terminée/i,
      /Reasoning Process|Language Detection|Prosody Analysis|Document Search/i,
      /Assistant indisponible/i,
      /^Question Processing Metrics:/i,
      /^Presentation Metrics:/i,
      /^Complete Metrics:/i,
    ];

    for (const pattern of patterns) {
      if (pattern.test(value)) return '';
    }

    return value;
  }

  // Update status indicator
  static updateStatus(dotId, textId, state) {
    const SC = {
      IDLE: { class: '', text: 'En attente' },
      PRESENTING: { class: 'pr', text: 'Présentation' },
      LISTENING: { class: 'li', text: 'Écoute' },
      PROCESSING: { class: 'po', text: 'Traitement' },
      RESPONDING: { class: 'pr', text: 'Réponse' },
    };

    const config = SC[state] || SC.IDLE;

    const dot = document.getElementById(dotId);
    if (dot) dot.className = 'sd ' + config.class;

    const text = document.getElementById(textId);
    if (text) text.textContent = config.text;
  }

  // Show/hide element
  static show(elementId, visible = true) {
    const el = document.getElementById(elementId);
    if (el) el.style.display = visible ? 'block' : 'none';
  }

  // Set element disabled state
  static setDisabled(elementId, disabled) {
    const el = document.getElementById(elementId);
    if (el) el.disabled = disabled;
  }

  // Set element class
  static setClass(elementId, className, active) {
    const el = document.getElementById(elementId);
    if (el) el.classList.toggle(className, active);
  }

  // Clear all messages from area
  static clearMessages(areaId) {
    const area = document.getElementById(areaId);
    if (area) {
      area.querySelectorAll('.msg').forEach((msg) => msg.remove());
    }
  }

  // Get element
  static getElement(id) {
    return document.getElementById(id);
  }

  // Query selector
  static query(selector) {
    return document.querySelector(selector);
  }

  // Query selector all
  static queryAll(selector) {
    return document.querySelectorAll(selector);
  }

  // Set text content
  static setText(elementId, text) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = text;
  }

  // Get text content
  static getText(elementId) {
    const el = document.getElementById(elementId);
    return el ? el.textContent : '';
  }

  // Set input value
  static setInputValue(elementId, value) {
    const el = document.getElementById(elementId);
    if (el) el.value = value;
  }

  // Get input value
  static getInputValue(elementId) {
    const el = document.getElementById(elementId);
    return el ? el.value : '';
  }

  // Add event listener
  static listen(elementId, event, handler) {
    const el = document.getElementById(elementId);
    if (el) {
      el.addEventListener(event, handler);
      return () => el.removeEventListener(event, handler);
    }
  }

  // Create and append element
  static createElement(tag, className = '', parent = null) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (parent) parent.appendChild(el);
    return el;
  }

  // Show notification
  static showNotification(message, type = 'info', duration = 5000) {
    const colors = {
      info: '#3b82f6',
      success: '#10b981',
      warning: '#f59e0b',
      error: '#ef4444',
    };

    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: ${colors[type] || colors.info};
      color: white;
      padding: 14px 18px;
      border-radius: 8px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
      font-weight: 600;
      z-index: 9999;
      animation: slideInUp 0.3s ease;
    `;
    notification.textContent = message;

    document.body.appendChild(notification);

    if (duration > 0) {
      setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s ease';
        setTimeout(() => notification.remove(), 300);
      }, duration);
    }

    return notification;
  }
}

export default UIManager;
