/**
 * Course Selector Component
 * Displays available courses and handles selection
 */

import { BaseComponent } from './base-component.js';
import { stateManager } from '../modules/state-manager.js';

export class CourseSelector extends BaseComponent {
  constructor(containerId) {
    super(containerId);
    this.courses = [];
    this.onCourseSelect = null;
  }

  render() {
    this.container.innerHTML = `
      <div class="selector-shell">
        <button class="selector-toggle" id="courseSelectorBtn">📚 Select Course</button>
        <span class="selector-hint" id="courseSelectorHint">Ouvrir la liste des cours disponibles</span>
      </div>
      <div id="courseSelectorPanel" class="course-selector-panel">
        <div class="selector-header">
          <div style="font-size:.8em;font-weight:600;color:var(--muted);text-transform:uppercase">📚 Cours Disponibles</div>
          <input class="ci" id="courseSelectorFilter" placeholder="Rechercher un cours…" style="margin-top:10px">
        </div>
        <div class="cgrid" id="coursesGrid"></div>
      </div>
    `;

    this._attachListeners();
  }

  _attachListeners() {
    this.query('#courseSelectorBtn')?.addEventListener('click', () => this.toggle());
    this.query('#courseSelectorFilter')?.addEventListener('input', (e) => this.filterCourses(e.target.value));
  }

  toggle() {
    const panel = this.query('#courseSelectorPanel');
    if (panel) {
      panel.classList.toggle('open');
      this.query('#courseSelectorBtn')?.classList.toggle('active');
    }
  }

  displayCourses(courses) {
    this.courses = courses;
    this._renderCourses(courses);
  }

  _renderCourses(courses = this.courses) {
    const grid = this.query('#coursesGrid');
    if (!grid) return;

    if (courses.length === 0) {
      grid.innerHTML = '<div style="color:var(--muted);font-size:.83em;grid-column:1/-1">Aucun cours.</div>';
      return;
    }

    grid.innerHTML = courses
      .map((course) => {
        const selected = course.id === stateManager.courseId ? 'selected' : '';
        return `
          <div class="cc ${selected}" data-course-id="${course.id}" onclick="event.stopPropagation()">
            <div class="cc-head">
              <div class="cc-title">${course.name}</div>
              ${course.domain ? `<div class="cc-domain">${course.domain}</div>` : ''}
            </div>
            <div class="cc-meta">
              <span>${course.chapters || 0} chapitres</span>
              <span>${course.sections || 0} sections</span>
            </div>
            <button class="btn btn-sm" onclick="this.parentElement.click()">Charger</button>
          </div>
        `;
      })
      .join('');

    // Attach click handlers
    this.queryAll('.cc').forEach((card) => {
      card.addEventListener('click', () => {
        this.selectCourse(card.dataset.courseId);
      });
    });
  }

  selectCourse(courseId) {
    const course = this.courses.find((c) => c.id === courseId);
    if (!course) return;

    stateManager.setState('courseId', courseId);
    stateManager.setState('course', course);
    stateManager.setState('chapterIndex', 0);
    stateManager.setState('sectionIndex', 0);

    // Update visual state
    this.queryAll('.cc').forEach((card) => {
      card.classList.toggle('selected', card.dataset.courseId === courseId);
    });

    // Emit event
    if (this.onCourseSelect) {
      this.onCourseSelect(course);
    }

    // Close selector
    this.toggle();
  }

  filterCourses(query) {
    const q = query.toLowerCase().trim();
    if (!q) {
      this._renderCourses(this.courses);
      return;
    }

    const filtered = this.courses.filter((course) =>
      course.name.toLowerCase().includes(q) ||
      (course.domain && course.domain.toLowerCase().includes(q))
    );

    this._renderCourses(filtered);
  }

  update(data) {
    if (data.courses) {
      this.displayCourses(data.courses);
    }
  }
}

export default CourseSelector;
