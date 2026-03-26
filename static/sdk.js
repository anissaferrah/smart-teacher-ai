/**
 * ╔══════════════════════════════════════════════════════════════════════╗
 * ║        SMART TEACHER — SDK JavaScript Client                       ║
 * ║                                                                      ║
 * ║  Usage minimal :                                                     ║
 * ║    const st = new SmartTeacher({ host: 'localhost:8000' })          ║
 * ║    await st.connect()                                                ║
 * ║    st.onTranscription = text => console.log(text)                   ║
 * ║    st.onAnswer        = text => console.log(text)                   ║
 * ║    await st.startMic()                                               ║
 * ╚══════════════════════════════════════════════════════════════════════╝
 */

class SmartTeacher {
  constructor(options = {}) {
    this.host       = options.host       || location.host;
    this.language   = options.language   || 'fr';
    this.level      = options.level      || 'lycée';
    this.sessionId  = options.sessionId  || crypto.randomUUID();

    // Callbacks publics
    this.onConnected       = options.onConnected       || (() => {});
    this.onDisconnected    = options.onDisconnected    || (() => {});
    this.onTranscription   = options.onTranscription   || (() => {});
    this.onAnswer          = options.onAnswer          || (() => {});
    this.onAudio           = options.onAudio           || (() => {});
    this.onStateChange     = options.onStateChange     || (() => {});
    this.onSlideUpdate     = options.onSlideUpdate     || (() => {});
    this.onPerformance     = options.onPerformance     || (() => {});
    this.onError           = options.onError           || ((e) => console.error(e));

    // Interne
    this._ws           = null;
    this._recorder     = null;
    this._audioBuffer  = [];
    this._currentAudio = null;
    this._recording    = false;
    this._sessionStarted = false;
  }

  // ── Connexion WebSocket ─────────────────────────────────────────────
  async connect() {
    return new Promise((resolve, reject) => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      this._ws = new WebSocket(`${proto}://${this.host}/ws/${this.sessionId}`);

      this._ws.onopen = () => {
        this._startSession();
        this.onConnected(this.sessionId);
        resolve(this);
      };

      this._ws.onclose = () => {
        this.onDisconnected();
        setTimeout(() => this.connect(), 3000);
      };

      this._ws.onerror = (e) => {
        this.onError(e);
        reject(e);
      };

      this._ws.onmessage = (ev) => {
        try { this._handleMessage(JSON.parse(ev.data)); }
        catch(e) { this.onError(e); }
      };
    });
  }

  disconnect() {
    if (this._ws) { this._ws.close(); this._ws = null; }
  }

  // ── Messages WebSocket ──────────────────────────────────────────────
  _send(obj) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN)
      this._ws.send(JSON.stringify(obj));
  }

  _startSession() {
    if (!this._sessionStarted) {
      this._send({ type: 'start_session', language: this.language, level: this.level });
      this._sessionStarted = true;
    }
  }

  _handleMessage(msg) {
    switch (msg.type) {
      case 'state_change':
        this.onStateChange(msg.state);
        break;
      case 'transcription':
        this.onTranscription(msg.text, msg.lang, msg.confidence);
        break;
      case 'answer_text':
        this._pendingAnswer = msg.text;
        this.onAnswer(msg.text, msg.subject);
        break;
      case 'audio_chunk':
        this._bufferAudio(msg.data, msg.mime, msg.final);
        break;
      case 'slide_update':
        this.onSlideUpdate(msg);
        break;
      case 'performance':
        this.onPerformance(msg);
        break;
      case 'error':
        this.onError(msg.message);
        break;
    }
  }

  // ── Microphone ──────────────────────────────────────────────────────
  async startMic() {
    if (this._recording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime   = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                   ? 'audio/webm;codecs=opus' : 'audio/webm';

    this._recorder = new MediaRecorder(stream, { mimeType: mime });

    this._recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        const reader = new FileReader();
        reader.onloadend = () => {
          this._send({ type: 'audio_chunk', data: reader.result.split(',')[1] });
        };
        reader.readAsDataURL(e.data);
      }
    };

    this._recorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      this._send({ type: 'audio_end' });
      this._recording = false;
    };

    this._recorder.start(300);
    this._recording = true;
    this._send({ type: 'interrupt' }); // interrompt la présentation
    return true;
  }

  stopMic() {
    if (this._recorder && this._recorder.state !== 'inactive') {
      this._recorder.stop();
    }
  }

  isRecording() { return this._recording; }

  // ── Texte ───────────────────────────────────────────────────────────
  sendText(text) {
    this._startSession();
    this._send({ type: 'text', content: text });
  }

  // ── Navigation cours ────────────────────────────────────────────────
  nextSection()  { this._send({ type: 'next_section' }); }
  prevSection()  { this._send({ type: 'prev_section' }); }
  interrupt()    { this._send({ type: 'interrupt' }); this.stopAudio(); }
  ping()         { this._send({ type: 'ping' }); }

  // ── Audio playback ──────────────────────────────────────────────────
  _bufferAudio(b64, mime, final) {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    this._audioBuffer.push(bytes);

    if (final) {
      const total = this._audioBuffer.reduce((s, c) => s + c.length, 0);
      const merged = new Uint8Array(total);
      let offset = 0;
      this._audioBuffer.forEach(c => { merged.set(c, offset); offset += c.length; });
      this._audioBuffer = [];

      const blob = new Blob([merged], { type: mime || 'audio/mpeg' });
      const url  = URL.createObjectURL(blob);
      this.playAudio(url);
      this.onAudio(url);
    }
  }

  playAudio(url) {
    this.stopAudio();
    this._currentAudio = new Audio(url);
    this._currentAudio.play().catch(e => this.onError('Audio play failed: ' + e));
  }

  stopAudio() {
    if (this._currentAudio) { this._currentAudio.pause(); this._currentAudio = null; }
    this._audioBuffer = [];
  }

  // ── REST API ────────────────────────────────────────────────────────
  async askText(question) {
    const fd = new FormData();
    fd.append('question', question);
    const r = await fetch(`//${this.host}/ask`, {
      method: 'POST',
      headers: { 'X-Session-ID': this.sessionId },
      body: fd,
    });
    return r.json();
  }

  async uploadCourse(file, language = 'fr', level = 'lycée') {
    const fd = new FormData();
    fd.append('files', file);
    fd.append('language', language);
    fd.append('level', level);
    const r = await fetch(`//${this.host}/course/build`, { method: 'POST', body: fd });
    return r.json();
  }

  async listCourses() {
    const r = await fetch(`//${this.host}/course/list`);
    return r.json();
  }

  async getCourseStructure(courseId) {
    const r = await fetch(`//${this.host}/course/${courseId}/structure`);
    return r.json();
  }

  async getHealth() {
    const r = await fetch(`//${this.host}/health`);
    return r.json();
  }
}

// Export pour modules ES6 et CommonJS
if (typeof module !== 'undefined' && module.exports) module.exports = SmartTeacher;
if (typeof window !== 'undefined') window.SmartTeacher = SmartTeacher;
