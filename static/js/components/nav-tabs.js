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
        <button class="nav-tab" id="quizBtn" data-panel="quiz" data-label="📝 Quiz" disabled>📝 Quiz</button>
      </div>
    `;
    
    this._attachListeners();
  }

  _attachListeners() {
    const tabs = this.queryAll('.nav-tab');
    tabs.forEach((tab) => {
      tab.addEventListener('click', (e) => {
        if (!tab.disabled) {
          if (tab.dataset.panel === 'quiz') {
            this._openQuizPage();
            return;
          }

          this.switchTo(tab.dataset.panel);
        }
      });
    });
  }

  _openQuizPage() {
    const course = stateManager.course || {};
    const params = new URLSearchParams({
      course_id: stateManager.courseId || '',
      chapter_index: String(stateManager.chapterIndex ?? 0),
      section_index: String(stateManager.sectionIndex ?? 0),
      chapter: course.chapter || course.chapter_title || `Chapitre ${Number(stateManager.chapterIndex || 0) + 1}`,
      section_title: stateManager.slideTitle || '',
      slide_title: stateManager.slideTitle || '',
      slide_content: stateManager.slideText || '',
      slide_path: stateManager.slidePath || '',
      image_url: stateManager.slidePath || '',
      course_title: course.name || course.title || '',
      course_domain: course.domain || '',
      language: course.language || 'fr',
      level: course.level || 'lycée',
    });

    window.open(`/static/quiz.html?${params.toString()}`, '_blank', 'noopener,noreferrer');
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
