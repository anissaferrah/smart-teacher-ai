"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Intégration Jitsi / WebRTC                  ║
║                                                                      ║
║  Gère la visioconférence et le streaming audio WebRTC :             ║
║    - Création de salles Jitsi                                       ║
║    - Tokens JWT pour accès sécurisé                                 ║
║    - Configuration des contraintes audio WebRTC                     ║
║    - Coordination voix/visuel via événements                        ║
║    - VAD côté serveur pour détection de parole                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import time
import logging
import hashlib
import hmac
import base64
import json
from typing import Optional

log = logging.getLogger("SmartTeacher.Jitsi")

JITSI_DOMAIN    = os.getenv("JITSI_DOMAIN",    "meet.jit.si")     # ou votre Jitsi self-hosted
JITSI_APP_ID    = os.getenv("JITSI_APP_ID",    "")                # pour JWT auth
JITSI_APP_SECRET = os.getenv("JITSI_APP_SECRET", "")
JITSI_SELF_HOSTED = os.getenv("JITSI_SELF_HOSTED", "false").lower() == "true"


class JitsiRoomManager:
    """
    Crée et gère les salles Jitsi pour les sessions SmartTeacher.
    """

    def create_room(self, session_id: str, course_title: str = "") -> dict:
        """
        Crée/configure une salle Jitsi pour la session.
        Retourne les infos de connexion.
        """
        room_name = f"smartteacher-{session_id[:12]}"
        room_url  = f"https://{JITSI_DOMAIN}/{room_name}"

        result = {
            "room_name":  room_name,
            "room_url":   room_url,
            "domain":     JITSI_DOMAIN,
            "jwt_token":  None,
        }

        # JWT token si APP_ID configuré (pour Jitsi self-hosted)
        if JITSI_APP_ID and JITSI_APP_SECRET:
            result["jwt_token"] = self._generate_jwt(room_name, course_title)

        return result

    def _generate_jwt(self, room: str, subject: str = "") -> str:
        """Génère un token JWT pour authentification Jitsi."""
        header  = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss":     JITSI_APP_ID,
            "sub":     JITSI_DOMAIN,
            "aud":     "jitsi",
            "room":    room,
            "context": {"user": {"name": "Smart Teacher AI"}},
            "iat":     int(time.time()),
            "exp":     int(time.time()) + 3600,
        }

        def b64url(data: dict) -> str:
            return base64.urlsafe_b64encode(
                json.dumps(data, separators=(',', ':')).encode()
            ).rstrip(b'=').decode()

        header_enc  = b64url(header)
        payload_enc = b64url(payload)
        msg         = f"{header_enc}.{payload_enc}"
        sig         = hmac.new(
            JITSI_APP_SECRET.encode(), msg.encode(), "sha256"
        ).digest()
        sig_enc = base64.urlsafe_b64encode(sig).rstrip(b'=').decode()
        return f"{msg}.{sig_enc}"


class WebRTCAudioConfig:
    """
    Configuration des contraintes audio WebRTC pour la session SmartTeacher.
    Optimisé pour STT (suppression du bruit, mono, 16kHz).
    """

    @staticmethod
    def get_constraints() -> dict:
        """Contraintes audio WebRTC optimales pour le STT."""
        return {
            "audio": {
                "sampleRate":           {"ideal": 16000},
                "channelCount":         {"ideal": 1},
                "echoCancellation":     True,
                "noiseSuppression":     True,
                "autoGainControl":      True,
                "latency":              {"ideal": 0.01},
                "googEchoCancellation": True,
                "googNoiseSuppression": True,
                "googHighpassFilter":   True,
            },
            "video": False,
        }

    @staticmethod
    def get_jitsi_config(room_name: str, domain: str,
                         jwt_token: Optional[str] = None) -> dict:
        """
        Configuration complète pour l'API Jitsi Meet.
        À passer à `new JitsiMeetExternalAPI()` côté client.
        """
        config = {
            "roomName":        room_name,
            "parentNode":      "jitsi-container",
            "domain":          domain,
            "configOverwrite": {
                "startWithAudioMuted":    False,
                "startWithVideoMuted":    True,
                "prejoinPageEnabled":     False,
                "disableDeepLinking":     True,
                "enableClosePage":        False,
                "p2p":                    {"enabled": True},
                "audioQuality":           {"stereo": False, "opusMaxAverageBitrate": 16000},
                "disableAudioLevels":     False,
                "enableLayerSuspension":  True,
            },
            "interfaceConfigOverwrite": {
                "TOOLBAR_BUTTONS":        ["microphone", "hangup"],
                "SHOW_JITSI_WATERMARK":   False,
                "SHOW_WATERMARK_FOR_GUESTS": False,
                "DEFAULT_BACKGROUND":     "#0d0f14",
                "DISABLE_JOIN_LEAVE_NOTIFICATIONS": True,
            },
        }
        if jwt_token:
            config["jwt"] = jwt_token
        return config


# HTML snippet à injecter dans index.html pour activer Jitsi
JITSI_HTML_SNIPPET = """
<!-- ═══════════════════════════════════════
     JITSI / WebRTC — Visioconférence
     Activer : ajouter data-jitsi="true" au body
═══════════════════════════════════════ -->
<div id="jitsi-panel" style="display:none">
  <div id="jitsi-container" style="width:100%;height:300px;border-radius:12px;overflow:hidden"></div>
  <button onclick="toggleJitsi()" style="margin-top:8px;padding:6px 14px;background:#7c6dfa;color:#fff;border:none;border-radius:7px;cursor:pointer;font-size:.8em">
    📹 Activer / Désactiver caméra
  </button>
</div>
<script>
// ── Jitsi Meet ────────────────────────────────────────────────────────
let jitsiAPI = null;

async function initJitsi(sessionId) {
  // Charger le SDK Jitsi dynamiquement
  if (!window.JitsiMeetExternalAPI) {
    const script = document.createElement('script');
    script.src = 'https://' + JITSI_DOMAIN + '/external_api.js';
    document.head.appendChild(script);
    await new Promise(res => script.onload = res);
  }

  const r = await fetch('/jitsi/room/' + sessionId).then(r => r.json());
  const panel = document.getElementById('jitsi-panel');
  panel.style.display = 'block';

  jitsiAPI = new JitsiMeetExternalAPI(r.domain, r.jitsi_config);

  // Écouter les événements Jitsi
  jitsiAPI.addEventListener('audioMuteStatusChanged', ({ muted }) => {
    if (!muted) triggerVAD();
  });

  jitsiAPI.addEventListener('participantLeft', () => {
    panel.style.display = 'none';
  });
}

function toggleJitsi() {
  const p = document.getElementById('jitsi-panel');
  if (p.style.display === 'none') {
    initJitsi(SESSION_ID);
  } else {
    if (jitsiAPI) { jitsiAPI.dispose(); jitsiAPI = null; }
    p.style.display = 'none';
  }
}

function triggerVAD() {
  // Connecter l'audio WebRTC au pipeline STT SmartTeacher
  if (window.SmartTeacher && window.st) {
    window.st.startMic();
  }
}
</script>
"""
