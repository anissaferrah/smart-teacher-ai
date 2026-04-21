/**
 * Navigation Tabs Component
 * Handles panel switching and tab management
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';

export class NavTabs extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.activeTab = 'course';
    this.onTabChange = null;
  }

  render() {
    this.container.innerHTML = `
      <div class="nav-tabs" id="navTabsContainer">
        <button class="nav-tab active" data-panel="course" data-label="📖 Cours">📖 Cours</button>
        <button class="nav-tab" data-panel="library" data-label="📚 Mes Cours">📚 Mes Cours</button>
        <button class="nav-tab" id="quizBtn" data-panel="qa" data-label="📝 Q&A" disabled>📝 Q&A</button>
      </div>
    `;
    
    this._attachListeners();
  }

  _attachListeners() {
    const tabs = this.queryAll('.nav-tab');
    tabs.forEach((tab) => {
      tab.addEventListener('click', (e) => {
        if (!tab.disabled) {
          this.switchTo(tab.dataset.panel);
        }
      });
    });
  }

  switchTo(panelName) {
    this.activeTab = panelName;
    stateManager.setState('activePanel', panelName);

    // Update tab styles
    const tabs = this.queryAll('.nav-tab');
    tabs.forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.panel === panelName);
    });

    // Emit event
    if (this.onTabChange) {
      this.onTabChange(panelName);
    }

    // Show corresponding panel
    this._showPanel(panelName);
  }

  _showPanel(panelName) {
    const panels = document.querySelectorAll('.panel');
    panels.forEach((panel) => {
      panel.classList.remove('active');
    });

    const targetPanel = document.getElementById(`panel-${panelName}`);
    if (targetPanel) {
      targetPanel.classList.add('active');
    }
  }

  enableTab(tabName) {
    const tab = this.query(`[data-panel="${tabName}"]`);
    if (tab) tab.disabled = false;
  }

  disableTab(tabName) {
    const tab = this.query(`[data-panel="${tabName}"]`);
    if (tab) tab.disabled = true;
  }

  update(data) {
    if (data.activePanel) {
      this.switchTo(data.activePanel);
    }
    if (data.enabledTabs) {
      Object.keys(data.enabledTabs).forEach((tab) => {
        if (data.enabledTabs[tab]) {
          this.enableTab(tab);
        } else {
          this.disableTab(tab);
        }
      });
    }
  }
}

export default NavTabs;
