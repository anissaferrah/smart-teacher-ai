/**
 * Base Component Class
 * Template for all UI components
 */

export class BaseComponent {
  constructor(containerId) {
    this.container = typeof containerId === 'string'
      ? document.getElementById(containerId)
      : containerId;
    if (!this.container) {
      throw new Error(`Container with ID "${containerId}" not found`);
    }
  }

  // Render component
  render() {
    throw new Error('render() must be implemented by subclass');
  }

  // Update component
  update(data) {
    throw new Error('update() must be implemented by subclass');
  }

  // Destroy component
  destroy() {
    if (this.container) {
      this.container.innerHTML = '';
    }
  }

  // Create element helper
  createElement(tag, className = '', parent = this.container) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (parent) parent.appendChild(el);
    return el;
  }

  // Query element in container
  query(selector) {
    return this.container.querySelector(selector);
  }

  // Query all elements in container
  queryAll(selector) {
    return this.container.querySelectorAll(selector);
  }
}

export default BaseComponent;
