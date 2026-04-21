/**
 * WebSocket Client Module
 * Handles all WebSocket communication with the backend
 */

import { stateManager } from './state-manager.js';

class WSClient {
  constructor() {
    this.ws = null;
    this.connected = false;
    this.sessionStarted = false;
    this._listeners = new Map();
    this._reconnectAttempts = 0;
    this._maxReconnectAttempts = 10;
    this._reconnectDelay = 3000;
  }

  // Subscribe to WebSocket events
  on(event, callback) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, []);
    }
    this._listeners.get(event).push(callback);
    return () => {
      const callbacks = this._listeners.get(event);
      const index = callbacks.indexOf(callback);
      if (index > -1) callbacks.splice(index, 1);
    };
  }

  // Emit event to listeners
  _emit(event, data) {
    if (this._listeners.has(event)) {
      this._listeners.get(event).forEach(cb => cb(data));
    }
  }

  // Connect to WebSocket server
  connect() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${protocol}://${location.host}/ws/${stateManager.sessionId}`;

    try {
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.connected = true;
        this._reconnectAttempts = 0;
        this._emit('connected', { timestamp: Date.now() });
        console.log('✅ WebSocket connected');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this._emit('message', data);
          this._emit(data.type, data);
        } catch (error) {
          console.error('❌ Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onerror = (error) => {
        this.connected = false;
        this._emit('error', { error, timestamp: Date.now() });
        console.error('❌ WebSocket error:', error);
      };

      this.ws.onclose = () => {
        this.connected = false;
        this.sessionStarted = false;
        this._emit('disconnected', { timestamp: Date.now() });
        console.log('⚠️ WebSocket disconnected, attempting reconnect...');
        this._reconnect();
      };
    } catch (error) {
      console.error('❌ Failed to create WebSocket:', error);
      this._reconnect();
    }
  }

  // Attempt to reconnect
  _reconnect() {
    if (this._reconnectAttempts >= this._maxReconnectAttempts) {
      console.error('❌ Max reconnection attempts reached');
      this._emit('reconnect-failed', {});
      return;
    }

    this._reconnectAttempts++;
    setTimeout(() => {
      console.log(`🔄 Reconnection attempt ${this._reconnectAttempts}/${this._maxReconnectAttempts}`);
      this.connect();
    }, this._reconnectDelay);
  }

  // Send message to server
  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(message));
      } catch (error) {
        console.error('❌ Failed to send WebSocket message:', error);
      }
    } else {
      console.warn('⚠️ WebSocket not ready, message queued');
    }
  }

  // Start session on server
  startSession(language = 'fr', level = 'lycée') {
    if (this.sessionStarted) return;

    const token = localStorage.getItem('token') || '';
    this.send({
      type: 'start_session',
      language,
      level,
      token,
      course_id: stateManager.courseId || '',
    });

    this.sessionStarted = true;
  }

  // Disconnect WebSocket
  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
    this.sessionStarted = false;
  }

  // Check if connected
  isConnected() {
    return this.connected && this.ws && this.ws.readyState === WebSocket.OPEN;
  }
}

// Singleton instance
export const wsClient = new WSClient();

export default wsClient;
