"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Dashboard Professeur                        ║
║                                                                      ║
║  Routes FastAPI pour le tableau de bord du professeur :             ║
║    GET  /dashboard              — page HTML du dashboard            ║
║    GET  /dashboard/stats        — statistiques globales             ║
║    GET  /dashboard/sessions     — sessions actives                  ║
║    GET  /dashboard/analytics    — métriques d'apprentissage         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import logging, time, json
from pathlib import Path

log = logging.getLogger("SmartTeacher.Dashboard")
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Stats en mémoire (complétées par PostgreSQL si dispo) ─────────────
_SESSIONS_CACHE: list[dict] = []

def record_session_event(event: dict):
    """Appelé depuis main.py à chaque interaction."""
    _SESSIONS_CACHE.append({**event, "ts": time.time()})
    if len(_SESSIONS_CACHE) > 1000:
        _SESSIONS_CACHE.pop(0)


@router.get("/stats")
async def get_stats():
    """Statistiques globales pour le dashboard."""
    total    = len(_SESSIONS_CACHE)
    kpi_ok   = sum(1 for e in _SESSIONS_CACHE if e.get("meets_kpi"))
    avg_time = (sum(e.get("total_time", 0) for e in _SESSIONS_CACHE) / total) if total else 0

    # Par langue
    langs: dict[str, int] = {}
    for e in _SESSIONS_CACHE:
        l = e.get("language", "unknown")
        langs[l] = langs.get(l, 0) + 1

    # Par matière
    subjects: dict[str, int] = {}
    for e in _SESSIONS_CACHE:
        s = e.get("subject") or "unknown"
        subjects[s] = subjects.get(s, 0) + 1

    # Tentatives PostgreSQL
    try:
        from database.init_db import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            r = await db.execute(text("SELECT COUNT(*) FROM interactions"))
            total_db = r.scalar() or 0
            r2 = await db.execute(text("SELECT COUNT(*) FROM learning_sessions"))
            sessions_db = r2.scalar() or 0
    except Exception:
        total_db = total
        sessions_db = len(set(e.get("session_id","") for e in _SESSIONS_CACHE))

    return {
        "total_interactions": total_db,
        "total_sessions":     sessions_db,
        "kpi_rate_pct":       round(kpi_ok / total * 100, 1) if total else 0,
        "avg_response_time":  round(avg_time, 2),
        "by_language":        langs,
        "by_subject":         subjects,
        "last_24h":           sum(1 for e in _SESSIONS_CACHE if time.time() - e.get("ts",0) < 86400),
    }


@router.get("/sessions")
async def get_active_sessions():
    """Sessions récentes (dernières 24h)."""
    cutoff = time.time() - 86400
    recent = [e for e in _SESSIONS_CACHE if e.get("ts", 0) > cutoff]

    # Grouper par session_id
    by_session: dict[str, list] = {}
    for e in recent:
        sid = e.get("session_id", "unknown")
        by_session.setdefault(sid, []).append(e)

    sessions = []
    for sid, events in list(by_session.items())[-20:]:
        sessions.append({
            "session_id":   sid[:8],
            "language":     events[-1].get("language", "?"),
            "turns":        len(events),
            "avg_time":     round(sum(e.get("total_time",0) for e in events) / len(events), 2),
            "kpi_rate":     round(sum(1 for e in events if e.get("meets_kpi")) / len(events) * 100, 1),
            "last_activity": events[-1].get("ts", 0),
        })
    return {"sessions": sorted(sessions, key=lambda x: -x["last_activity"])}


@router.get("/analytics")
async def get_analytics():
    """Métriques d'apprentissage détaillées."""
    if not _SESSIONS_CACHE:
        return {"message": "Pas encore de données"}

    times = [e["total_time"] for e in _SESSIONS_CACHE if e.get("total_time")]
    stt_t = [e["stt_time"]   for e in _SESSIONS_CACHE if e.get("stt_time")]
    llm_t = [e["llm_time"]   for e in _SESSIONS_CACHE if e.get("llm_time")]
    tts_t = [e["tts_time"]   for e in _SESSIONS_CACHE if e.get("tts_time")]

    def stats(lst):
        if not lst: return {}
        return {"min": round(min(lst),2), "max": round(max(lst),2),
                "avg": round(sum(lst)/len(lst),2)}

    return {
        "total_time": stats(times),
        "stt_time":   stats(stt_t),
        "llm_time":   stats(llm_t),
        "tts_time":   stats(tts_t),
        "kpi_threshold_s": 5.0,
        "kpi_rate_pct": round(sum(1 for e in _SESSIONS_CACHE if e.get("meets_kpi")) / len(_SESSIONS_CACHE) * 100, 1),
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """Dashboard HTML complet pour le professeur."""
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Smart Teacher — Dashboard Professeur</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d0f14;--panel:#151820;--border:#1e2330;
  --accent:#6c63ff;--accent2:#00d4aa;--accent3:#ff6b6b;
  --text:#e2e8f0;--muted:#64748b;--success:#00d4aa;--warn:#f59e0b;
}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh;padding:24px}
h1{font-size:1.6em;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}
.subtitle{color:var(--muted);font-size:.85em;margin-bottom:28px}

/* Grid */
.grid{display:grid;gap:16px}
.grid-4{grid-template-columns:repeat(4,1fr)}
.grid-2{grid-template-columns:1fr 1fr}
@media(max-width:900px){.grid-4{grid-template-columns:1fr 1fr}.grid-2{grid-template-columns:1fr}}

/* Cards */
.card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:20px}
.card-title{font-size:.72em;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}

/* KPI */
.kpi-value{font-size:2.4em;font-weight:700;font-family:'DM Mono',monospace;line-height:1}
.kpi-sub{font-size:.78em;color:var(--muted);margin-top:6px}
.green{color:var(--success)}.red{color:var(--accent3)}.yellow{color:var(--warn)}.purple{color:var(--accent)}

/* Sessions table */
table{width:100%;border-collapse:collapse;font-size:.83em}
th{color:var(--muted);font-weight:600;text-align:left;padding:8px 12px;border-bottom:1px solid var(--border)}
td{padding:8px 12px;border-bottom:1px solid var(--border)10}
tr:hover td{background:rgba(108,99,255,.06)}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.75em;font-weight:600}
.badge-green{background:rgba(0,212,170,.12);color:var(--success)}
.badge-red{background:rgba(255,107,107,.12);color:var(--accent3)}
.badge-yellow{background:rgba(245,158,11,.12);color:var(--warn)}

/* Chart bars */
.bar-group{display:flex;flex-direction:column;gap:8px}
.bar-row{display:flex;align-items:center;gap:10px;font-size:.8em}
.bar-label{width:80px;color:var(--muted);text-align:right;flex-shrink:0}
.bar-track{flex:1;background:var(--border);border-radius:4px;height:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width 1s ease}
.bar-val{width:50px;color:var(--text);font-family:'DM Mono',monospace;font-size:.85em}

/* Timeline */
.timeline{display:flex;flex-direction:column;gap:8px;max-height:280px;overflow-y:auto}
.tl-item{display:flex;gap:10px;align-items:flex-start;font-size:.8em}
.tl-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex-shrink:0;margin-top:4px}
.tl-dot.ok{background:var(--success)}.tl-dot.bad{background:var(--accent3)}
.tl-text{color:var(--muted)}.tl-time{color:var(--text);font-family:'DM Mono',monospace}

/* Refresh */
.refresh-btn{padding:6px 14px;background:var(--accent);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:.8em;font-weight:600;transition:opacity .2s}
.refresh-btn:hover{opacity:.8}
.last-update{font-size:.75em;color:var(--muted);margin-left:10px}

/* Loading */
.loading{display:inline-block;width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div style="max-width:1200px;margin:0 auto">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:28px">
    <div>
      <h1>🎓 Dashboard Professeur</h1>
      <div class="subtitle">Smart Teacher — Monitoring des sessions en temps réel</div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <button class="refresh-btn" onclick="loadAll()">↻ Actualiser</button>
      <span class="last-update" id="lastUpdate">—</span>
    </div>
  </div>

  <!-- KPIs -->
  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">Interactions totales</div>
      <div class="kpi-value purple" id="kpi-total"><span class="loading"></span></div>
      <div class="kpi-sub" id="kpi-24h">—</div>
    </div>
    <div class="card">
      <div class="card-title">Sessions</div>
      <div class="kpi-value green" id="kpi-sessions"><span class="loading"></span></div>
      <div class="kpi-sub">sessions enregistrées</div>
    </div>
    <div class="card">
      <div class="card-title">Taux KPI (&lt; 5s)</div>
      <div class="kpi-value" id="kpi-rate"><span class="loading"></span></div>
      <div class="kpi-sub">objectif : &gt; 80%</div>
    </div>
    <div class="card">
      <div class="card-title">Temps moyen réponse</div>
      <div class="kpi-value yellow" id="kpi-avg"><span class="loading"></span></div>
      <div class="kpi-sub">STT + LLM + TTS</div>
    </div>
  </div>

  <div class="grid grid-2" style="margin-bottom:16px">
    <!-- Répartition par composant -->
    <div class="card">
      <div class="card-title">⏱ Temps par composant</div>
      <div class="bar-group" id="timeChart">
        <div style="color:var(--muted);font-size:.85em">Chargement…</div>
      </div>
    </div>

    <!-- Répartition par langue -->
    <div class="card">
      <div class="card-title">🌍 Sessions par langue</div>
      <div class="bar-group" id="langChart">
        <div style="color:var(--muted);font-size:.85em">Chargement…</div>
      </div>
    </div>
  </div>

  <!-- Sessions récentes -->
  <div class="card" style="margin-bottom:16px">
    <div class="card-title" style="display:flex;align-items:center;justify-content:space-between">
      <span>📋 Sessions récentes (24h)</span>
      <span id="sessions-count" style="font-size:.85em;color:var(--accent)"></span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Session ID</th>
          <th>Langue</th>
          <th>Tours</th>
          <th>Temps moyen</th>
          <th>KPI</th>
          <th>Dernière activité</th>
        </tr>
      </thead>
      <tbody id="sessionsTable">
        <tr><td colspan="6" style="color:var(--muted);text-align:center;padding:20px">Chargement…</td></tr>
      </tbody>
    </table>
  </div>

  <!-- Accès rapide -->
  <div class="card">
    <div class="card-title">🔗 Accès rapide</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <a href="/static/index.html" style="padding:8px 16px;background:var(--accent);color:#fff;border-radius:8px;text-decoration:none;font-size:.85em;font-weight:600">🎓 Interface Étudiant</a>
      <a href="/docs" style="padding:8px 16px;background:var(--border);color:var(--text);border-radius:8px;text-decoration:none;font-size:.85em;font-weight:600">📚 API Docs</a>
      <a href="/rag/stats" style="padding:8px 16px;background:var(--border);color:var(--text);border-radius:8px;text-decoration:none;font-size:.85em;font-weight:600">🔍 RAG Stats</a>
      <a href="/health" style="padding:8px 16px;background:var(--border);color:var(--text);border-radius:8px;text-decoration:none;font-size:.85em;font-weight:600">💚 Health Check</a>
    </div>
  </div>
</div>

<script>
async function loadAll() {
  await Promise.all([loadStats(), loadSessions(), loadAnalytics()]);
  document.getElementById('lastUpdate').textContent = 'Mis à jour : ' + new Date().toLocaleTimeString();
}

async function loadStats() {
  try {
    const d = await fetch('/dashboard/stats').then(r => r.json());
    document.getElementById('kpi-total').textContent    = d.total_interactions?.toLocaleString() || '0';
    document.getElementById('kpi-sessions').textContent = d.total_sessions?.toLocaleString() || '0';
    document.getElementById('kpi-24h').textContent      = `${d.last_24h || 0} dernières 24h`;

    const rate = d.kpi_rate_pct || 0;
    const rateEl = document.getElementById('kpi-rate');
    rateEl.textContent = rate + '%';
    rateEl.className   = 'kpi-value ' + (rate >= 80 ? 'green' : rate >= 60 ? 'yellow' : 'red');

    // Graphe langues
    const langs = d.by_language || {};
    const total = Object.values(langs).reduce((a,b)=>a+b, 0) || 1;
    const colors = {fr:'#6c63ff',ar:'#00d4aa',en:'#f59e0b',tr:'#ff6b6b'};
    document.getElementById('langChart').innerHTML = Object.entries(langs)
      .sort((a,b) => b[1]-a[1])
      .map(([lang, cnt]) => `
        <div class="bar-row">
          <div class="bar-label">${lang.toUpperCase()}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${cnt/total*100}%;background:${colors[lang]||'#888'}"></div></div>
          <div class="bar-val">${cnt}</div>
        </div>`).join('') || '<div style="color:var(--muted);font-size:.85em">Aucune donnée</div>';
  } catch(e) { console.error(e); }
}

async function loadAnalytics() {
  try {
    const d = await fetch('/dashboard/analytics').then(r => r.json());
    if (d.message) return;

    document.getElementById('kpi-avg').textContent = (d.total_time?.avg || 0) + 's';

    const components = [
      {label:'STT',  val: d.stt_time?.avg || 0,  color:'#6c63ff', max:2},
      {label:'LLM',  val: d.llm_time?.avg || 0,  color:'#00d4aa', max:3},
      {label:'TTS',  val: d.tts_time?.avg || 0,  color:'#f59e0b', max:2},
      {label:'TOTAL',val: d.total_time?.avg || 0, color:'#ff6b6b', max:5},
    ];
    document.getElementById('timeChart').innerHTML = components.map(c => `
      <div class="bar-row">
        <div class="bar-label">${c.label}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.min(c.val/c.max*100,100)}%;background:${c.color}"></div></div>
        <div class="bar-val">${c.val}s</div>
      </div>`).join('');
  } catch(e) { console.error(e); }
}

async function loadSessions() {
  try {
    const d = await fetch('/dashboard/sessions').then(r => r.json());
    const sessions = d.sessions || [];
    document.getElementById('sessions-count').textContent = sessions.length + ' sessions';

    if (!sessions.length) {
      document.getElementById('sessionsTable').innerHTML =
        '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:20px">Aucune session récente</td></tr>';
      return;
    }

    document.getElementById('sessionsTable').innerHTML = sessions.map(s => {
      const kpiClass = s.kpi_rate >= 80 ? 'badge-green' : s.kpi_rate >= 60 ? 'badge-yellow' : 'badge-red';
      const ago = Math.round((Date.now()/1000 - s.last_activity) / 60);
      const agoStr = ago < 60 ? `il y a ${ago}min` : `il y a ${Math.round(ago/60)}h`;
      return `<tr>
        <td style="font-family:'DM Mono',monospace;color:var(--accent)">${s.session_id}…</td>
        <td><span class="badge badge-green">${(s.language||'?').toUpperCase()}</span></td>
        <td>${s.turns}</td>
        <td style="font-family:'DM Mono',monospace">${s.avg_time}s</td>
        <td><span class="badge ${kpiClass}">${s.kpi_rate}%</span></td>
        <td style="color:var(--muted)">${agoStr}</td>
      </tr>`;
    }).join('');
  } catch(e) { console.error(e); }
}

loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>"""
