/**
 * Audio Manager Module
 * Handles audio playback, recording, and waveform animation
 */

import { stateManager } from './state-manager.js';

class AudioManager {
  constructor() {
    this.waveformBars = 26;
    this.waveformInterval = null;
    this.animationState = 'off'; // off, speaking, listening, processing
  }

  // Initialize waveform bars
  initWaveform() {
    const waveform = document.getElementById('wf');
    if (!waveform) return;

    waveform.innerHTML = Array.from(
      { length: this.waveformBars },
      (_, i) => `<div class="wb" id="wb${i}" style="height:4px"></div>`
    ).join('');
  }

  // Animate waveform
  animateWaveform(state = 'off') {
    clearInterval(this.waveformInterval);
    this.animationState = state;

    const waveform = document.getElementById('wf');
    const bars = Array.from(
      { length: this.waveformBars },
      (_, i) => document.getElementById(`wb${i}`)
    );

    if (!bars[0]) return;

    const labels = {
      'off': 'En attente',
      'presenting': 'Présentation en cours',
      'speaking': 'Professeur parle',
      'listening': 'En écoute',
      'processing': 'Traitement...',
    };

    const label = document.getElementById('wlbl');
    if (label) label.textContent = labels[state] || 'En attente';

    bars.forEach(b => b.classList.toggle('a', state !== 'off'));

    if (state === 'off') {
      bars.forEach(b => (b.style.height = '4px'));
      return;
    }

    this.waveformInterval = setInterval(() => {
      bars.forEach((bar, i) => {
        let height = 4;

        if (state === 'speaking') {
          height = 8 + Math.sin(Date.now() / 200 + i * 0.4) * 14 + Math.random() * 5;
        } else if (state === 'listening') {
          height = 4 + Math.random() * 18;
        } else if (state === 'processing' || state === 'presenting') {
          height = 4 + Math.abs(Math.sin(Date.now() / 400 + i * 0.5)) * 8;
        }

        bar.style.height = Math.max(4, height) + 'px';
      });
    }, 80);
  }

  // Stop waveform animation
  stopWaveform() {
    if (this.waveformInterval) {
      clearInterval(this.waveformInterval);
      this.waveformInterval = null;
    }
    this.animationState = 'off';
  }

  // Play queued audio
  playQueuedAudio() {
    if (stateManager.answerAudioPaused) {
      return;
    }

    if (stateManager.currentAudio || !stateManager.audioQueue.length) {
      if (!stateManager.currentAudio && !stateManager.audioQueue.length) {
        this.animateWaveform('off');
      }
      return;
    }

    const url = stateManager.audioQueue.shift();
    const kind = stateManager.audioQueueKinds.shift() || 'presentation';

    stateManager.currentAudioKind = kind;
    const audio = new Audio(url);
    audio.volume = 1.0;
    audio.dataset.kind = kind;

    audio.onended = () => {
      try {
        URL.revokeObjectURL(url);
      } catch (e) {}
      stateManager.currentAudio = null;
      stateManager.currentAudioKind = null;
      if (stateManager.audioQueue.length) {
        this.playQueuedAudio();
      } else {
        this.animateWaveform('off');
      }
    };

    audio.onerror = () => {
      console.error('Audio playback error:', audio.error);
      try {
        URL.revokeObjectURL(url);
      } catch (e) {}
      stateManager.currentAudio = null;
      stateManager.currentAudioKind = null;
      if (stateManager.audioQueue.length) {
        this.playQueuedAudio();
      } else {
        this.animateWaveform('off');
      }
    };

    this.animateWaveform(kind === 'presentation' ? 'presenting' : 'speaking');
    stateManager.currentAudio = audio;

    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => {
          console.log('✅ Audio playing');
        })
        .catch((err) => {
          console.warn('⚠️ Autoplay blocked:', err);
          this.animateWaveform('off');
          // Show notification to user
        });
    }
  }

  // Stop audio playback
  stopAudio() {
    const playbackSnapshot = this._captureCurrentAudioSnapshot();
    stateManager.answerAudioPaused = false;
    stateManager.currentAudioKind = null;

    if (stateManager.currentAudio) {
      try {
        stateManager.currentAudio.pause();
      } catch (e) {}
      try {
        const src = stateManager.currentAudio.src || '';
        if (src.startsWith('blob:')) URL.revokeObjectURL(src);
      } catch (e) {}
      stateManager.currentAudio = null;
    }

    stateManager.audioQueue.forEach((url) => {
      try {
        URL.revokeObjectURL(url);
      } catch (e) {}
    });

    stateManager.audioQueue = [];
    stateManager.audioQueueKinds = [];
    stateManager.audioBuffer = [];

    this.animateWaveform('off');

    return playbackSnapshot;
  }

  _captureCurrentAudioSnapshot() {
    if (!stateManager.currentAudio) {
      return null;
    }

    const currentTime = Number.isFinite(stateManager.currentAudio.currentTime)
      ? stateManager.currentAudio.currentTime
      : 0;
    const duration = Number.isFinite(stateManager.currentAudio.duration)
      ? stateManager.currentAudio.duration
      : 0;

    return {
      kind: stateManager.currentAudioKind || 'presentation',
      currentTime,
      duration,
      playbackRatio: duration > 0 ? currentTime / duration : 0,
    };
  }

  // Add a full audio clip to the queue and play it as soon as possible
  enqueueAudioClip(base64Data, mimeType, kind = 'presentation') {
    if (!base64Data) return;

    try {
      const binaryString = atob(base64Data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: mimeType || 'audio/mpeg' });
      const objectUrl = URL.createObjectURL(blob);

      stateManager.audioQueue.push(objectUrl);
      stateManager.audioQueueKinds.push(kind);
      this.playQueuedAudio();
    } catch (error) {
      console.error('Audio clip decode error:', error);
    }
  }

  // Add audio chunk to buffer
  bufferAudioChunk(base64Data, mimeType, isFinal, streamId = null, turnId = null) {
    if (!base64Data) return;

    if (streamId !== null && streamId !== undefined) {
      if (stateManager.audioBufferStreamId === null) {
        stateManager.audioBufferStreamId = streamId;
      } else if (stateManager.audioBufferStreamId !== streamId) {
        stateManager.audioBuffer = [];
        stateManager.audioBufferStreamId = streamId;
      }
    }

    try {
      const binaryString = atob(base64Data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      stateManager.audioBuffer.push(bytes);
    } catch (error) {
      console.error('Base64 decode error:', error);
      return;
    }

    if (isFinal) {
      const totalLength = stateManager.audioBuffer.reduce((sum, chunk) => sum + chunk.length, 0);
      const mergedArray = new Uint8Array(totalLength);
      let offset = 0;

      stateManager.audioBuffer.forEach((chunk) => {
        mergedArray.set(chunk, offset);
        offset += chunk.length;
      });

      stateManager.audioBuffer = [];
      stateManager.audioBufferStreamId = null;

      const blob = new Blob([mergedArray], { type: mimeType || 'audio/mpeg' });
      const objectUrl = URL.createObjectURL(blob);

      stateManager.audioQueue.push(objectUrl);
      stateManager.audioQueueKinds.push(turnId !== null && turnId !== undefined ? 'answer' : 'presentation');

      this.playQueuedAudio();
    }
  }

  // Toggle answer audio playback
  toggleAnswerPlayback() {
    if (stateManager.answerAudioPaused) {
      stateManager.answerAudioPaused = false;
      if (stateManager.currentAudio) {
        const playPromise = stateManager.currentAudio.play();
        if (playPromise?.then) {
          playPromise
            .then(() => this.animateWaveform('speaking'))
            .catch((err) => console.warn('Resume audio blocked:', err));
        }
      } else {
        this.playQueuedAudio();
      }
    } else {
      if (stateManager.currentAudio && stateManager.currentAudioKind === 'answer') {
        try {
          stateManager.currentAudio.pause();
        } catch (e) {}
        stateManager.answerAudioPaused = true;
        this.animateWaveform('off');
      }
    }
  }
}

// Singleton instance
export const audioManager = new AudioManager();

export default audioManager;
