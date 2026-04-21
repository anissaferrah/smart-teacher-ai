/**
 * Header Component
 * Logo, navigation tabs, and status indicator
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';

export class Header extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.onTabChange = null;
  }

  render() {
    this.container.innerHTML = `
      <div class="logo">🎓 Smart Teacher</div>
      <div class="nav-tabs" id="navTabs">
        <button class="nav-tab active" data-panel="course">📖 Cours</button>
        <button class="nav-tab" data-panel="library">📚 Mes Cours</button>
        <button class="nav-tab" id="quizBtn" data-panel="qa" disabled>📝 Q&A</button>
      </div>
      <div class="nav-status">
        <div class="status-dot" id="statusDot"></div>
        <span class="status-text" id="statusText">Connexion…</span>
      </div>
      <button class="nav-tab" onclick="window.open('/dashboard','_blank')">📊 Dashboard</button>
    `;

    this._attachTabListeners();
  }

  _attachTabListeners() {
    const tabs = this.queryAll('.nav-tab[data-panel]');
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        this._switchPanel(tab.dataset.panel);
      });
    });
  }

  _switchPanel(panelName) {
    const targetPanel = panelName === 'quiz' ? 'qa' : panelName;
    stateManager.setState('activePanel', targetPanel);

    const tabs = this.queryAll('.nav-tab');
    tabs.forEach((tab) => {
      const tabPanel = tab.dataset.panel === 'quiz' ? 'qa' : tab.dataset.panel;
      const isActive = tabPanel === targetPanel;
      tab.classList.toggle('active', isActive);
    });

    // Emit event
    if (this.onTabChange) {
      this.onTabChange(targetPanel);
    }
  }

  setStatus(state, text) {
    const dot = this.query('#statusDot');
    const statusText = this.query('#statusText');

    if (dot) {
      dot.className = 'status-dot';
      if (state === 'connected') dot.classList.add('on');
      else if (state === 'ws') dot.classList.add('ws');
    }

    if (statusText) {
      statusText.textContent = text || 'Connexion…';
    }
  }

  enableQuizButton() {
    const btn = this.query('#quizBtn');
    if (btn) btn.disabled = false;
  }

  disableQuizButton() {
    const btn = this.query('#quizBtn');
    if (btn) btn.disabled = true;
  }

  update(data) {
    if (data.status) {
      this.setStatus(data.status.state, data.status.text);
    }
  }
}

export default Header;
