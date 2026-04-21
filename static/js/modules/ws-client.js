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
    this.sessionToken = '';
    this.sessionLanguage = 'fr';
    this.sessionLevel = 'lycée';
    this._listeners = new Map();
    this._reconnectAttempts = 0;
    this._maxReconnectAttempts = 10;
    this._reconnectDelay = 3000;
    this._manualDisconnect = false;
    this._reconnectTimer = null;
    this._heartbeatTimer = null;
    this._heartbeatInterval = 60000;
  }

  async prepareSession(language = 'fr', level = 'lycée') {
    this.sessionLanguage = language;
    this.sessionLevel = level;

    const response = await fetch('/session', { method: 'POST' });
    if (!response.ok) {
      throw new Error(`Session negotiation failed (${response.status})`);
    }

    const payload = await response.json();
    if (!payload.session_id || !payload.token) {
      throw new Error('Session negotiation returned an invalid payload');
    }

    stateManager.sessionId = payload.session_id;
    this.sessionToken = payload.token;
    localStorage.setItem('session_id', payload.session_id);
    localStorage.setItem('token', payload.token);
    return payload;
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
      this._manualDisconnect = false;
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.connected = true;
        this._reconnectAttempts = 0;
        this._emit('connected', { timestamp: Date.now() });
        console.log('✅ WebSocket connected');
        this._startHeartbeat();
        this._maybeStartSession();
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

      this.ws.onclose = (event) => {
        this.connected = false;
        this.sessionStarted = false;
        this._stopHeartbeat();
        this._emit('disconnected', {
          timestamp: Date.now(),
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        });
        console.log(`⚠️ WebSocket disconnected (code ${event.code}${event.reason ? `, reason: ${event.reason}` : ''})`);

        if (!this._manualDisconnect) {
          console.log('↻ Attempting reconnect...');
          this._reconnect(event.code === 1008 || /Invalid token/i.test(event.reason || ''));
        }
      };
    } catch (error) {
      console.error('❌ Failed to create WebSocket:', error);
      this._reconnect();
    }
  }

  // Attempt to reconnect
  _reconnect(forceNewSession = false) {
    if (this._reconnectAttempts >= this._maxReconnectAttempts) {
      console.error('❌ Max reconnection attempts reached');
      this._emit('reconnect-failed', {});
      return;
    }

    this._reconnectAttempts++;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
    }

    this._reconnectTimer = setTimeout(async () => {
      console.log(`🔄 Reconnection attempt ${this._reconnectAttempts}/${this._maxReconnectAttempts}`);

      if (forceNewSession) {
        try {
          this.sessionStarted = false;
          this.sessionToken = '';
          await this.prepareSession(this.sessionLanguage, this.sessionLevel);
        } catch (error) {
          console.error('❌ Failed to refresh session before reconnect:', error);
          this._reconnect(false);
          return;
        }
      }

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

  _startHeartbeat() {
    this._stopHeartbeat();
    this._heartbeatTimer = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: 'ping' });
      }
    }, this._heartbeatInterval);
  }

  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
  }

  // Start session on server
  startSession(language = 'fr', level = 'lycée') {
    this.sessionLanguage = language;
    this.sessionLevel = level;

    if (this.sessionStarted) return true;

    if (!this.isConnected()) {
      console.warn('⚠️ WebSocket not ready for session start');
      return false;
    }

    const token = this.sessionToken || localStorage.getItem('token') || '';
    if (!token) {
      console.warn('⚠️ Missing session token, cannot authenticate websocket session');
      return false;
    }

    this.send({
      type: 'start_session',
      language,
      level,
      token,
      course_id: stateManager.courseId || '',
    });

    this.sessionStarted = true;
    this.sessionToken = token;
    localStorage.setItem('token', token);
    return true;
  }

  _maybeStartSession() {
    if (this.sessionStarted) return;
    if (!this.sessionToken) {
      this.sessionToken = localStorage.getItem('token') || '';
    }
    if (!stateManager.sessionId) {
      stateManager.sessionId = localStorage.getItem('session_id') || stateManager.sessionId;
    }
    if (this.sessionToken) {
      this.startSession(this.sessionLanguage, this.sessionLevel);
    }
  }

  // Disconnect WebSocket
  disconnect() {
    this._manualDisconnect = true;
    this._stopHeartbeat();
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
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
