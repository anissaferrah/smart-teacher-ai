"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Analyse des Métriques CSV                ║
║                                                                      ║
║  Génère des graphiques de performance pour :                         ║
║    - Distribution du temps total (KPI 5s)                           ║
║    - Comparaison STT / LLM / TTS                                    ║
║    - Performance par langue                                          ║
║    - Taux de respect des KPIs                                        ║
║    - Évolution dans le temps (tendance)                              ║
║    - RTF (Real-Time Factor) — spécifique STT                        ║
║                                                                      ║
║  Usage : python analyze_metrics.py [--stt]                          ║
║    --stt : analyse stt_metrics.csv en plus                          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

from config import Config

# ── Chemins par défaut ─────────────────────────────────────────────────────────
METRICS_CSV = Config.CSV_LOG_FILE
STT_CSV     = Config.STT_LOG_FILE
KPI_LIMIT   = Config.MAX_RESPONSE_TIME   # 5.0 s
RTF_LIMIT   = Config.TARGET_RTF          # 0.5

PALETTE = {
    "stt":   "#4e79a7",
    "llm":   "#f28e2b",
    "tts":   "#59a14f",
    "total": "#e15759",
    "kpi":   "#76b7b2",
}


# ══════════════════════════════════════════════════════════════════════
#  ANALYSE GLOBALE (metrics.csv)
# ══════════════════════════════════════════════════════════════════════

def analyze_global(csv_path: str) -> None:
    if not os.path.exists(csv_path):
        print(f"❌ Fichier non trouvé : {csv_path}")
        print("   Lancez le serveur et faites quelques interactions d'abord.")
        return

    df = pd.read_csv(csv_path)
    if df.empty:
        print("⚠️  Le CSV est vide — aucune donnée à analyser.")
        return

    # ── Statistiques console ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("📊 SMART TEACHER — ANALYSE DES PERFORMANCES")
    print("=" * 60)
    print(f"\n📁 Fichier : {csv_path}")
    print(f"📈 Interactions : {len(df)}")

    cols = [c for c in ["stt_time", "llm_time", "tts_time", "total_time"] if c in df.columns]
    if cols:
        print("\n⏱️  TIMING (secondes) :")
        print(df[cols].describe().round(3).to_string())

    if "meets_kpi" in df.columns:
        kpi_rate = df["meets_kpi"].mean() * 100
        print(f"\n🎯 Respect KPI (<{KPI_LIMIT}s) : {kpi_rate:.1f}%")

    if "language" in df.columns:
        print(f"\n🌍 Langues détectées :")
        print(df["language"].value_counts().to_string())

    # ── Figures ───────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle("Smart Teacher — Tableau de Bord des Performances", fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.35)

    # 1. Distribution du temps total
    ax1 = fig.add_subplot(gs[0, 0])
    if "total_time" in df.columns:
        ax1.hist(df["total_time"].dropna(), bins=20, color=PALETTE["total"], edgecolor="white", alpha=0.85)
        ax1.axvline(KPI_LIMIT, color="red", linestyle="--", linewidth=2, label=f"KPI = {KPI_LIMIT}s")
        ax1.set_title("Distribution — Temps total")
        ax1.set_xlabel("Secondes")
        ax1.set_ylabel("Nb d'interactions")
        ax1.legend()

    # 2. Temps moyen par composant
    ax2 = fig.add_subplot(gs[0, 1])
    comp_cols = [c for c in ["stt_time", "llm_time", "tts_time"] if c in df.columns]
    if comp_cols:
        means = df[comp_cols].mean()
        labels = [c.replace("_time", "").upper() for c in comp_cols]
        colors = [PALETTE.get(c.replace("_time", ""), "#999") for c in comp_cols]
        bars = ax2.bar(labels, means, color=colors, edgecolor="white")
        for bar, val in zip(bars, means):
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                     f"{val:.2f}s", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax2.set_title("Temps moyen par composant")
        ax2.set_ylabel("Secondes")

    # 3. KPI rate par langue
    ax3 = fig.add_subplot(gs[0, 2])
    if "language" in df.columns and "meets_kpi" in df.columns:
        kpi_by_lang = df.groupby("language")["meets_kpi"].mean() * 100
        kpi_by_lang.plot(kind="bar", ax=ax3, color=PALETTE["kpi"], edgecolor="white")
        ax3.axhline(80, color="red", linestyle="--", linewidth=1.5, label="Objectif 80%")
        ax3.set_title("Taux KPI par langue (%)")
        ax3.set_ylabel("% sous KPI")
        ax3.set_ylim(0, 105)
        ax3.tick_params(axis="x", rotation=0)
        ax3.legend()
    else:
        ax3.text(0.5, 0.5, "Données insuffisantes", ha="center", va="center", transform=ax3.transAxes)
        ax3.set_title("Taux KPI par langue")

    # 4. Temps total par langue
    ax4 = fig.add_subplot(gs[1, 0])
    if "language" in df.columns and "total_time" in df.columns:
        df.groupby("language")["total_time"].mean().plot(
            kind="bar", ax=ax4, color=PALETTE["total"], edgecolor="white"
        )
        ax4.axhline(KPI_LIMIT, color="red", linestyle="--", linewidth=1.5)
        ax4.set_title("Temps total moyen par langue")
        ax4.set_ylabel("Secondes")
        ax4.tick_params(axis="x", rotation=0)

    # 5. Évolution temporelle (rolling avg)
    ax5 = fig.add_subplot(gs[1, 1])
    if "total_time" in df.columns and len(df) >= 5:
        rolling = df["total_time"].rolling(window=min(10, len(df)//2 + 1), min_periods=1).mean()
        ax5.plot(df.index, df["total_time"], alpha=0.3, color=PALETTE["total"], label="Brut")
        ax5.plot(df.index, rolling, color=PALETTE["total"], linewidth=2, label="Moyenne glissante")
        ax5.axhline(KPI_LIMIT, color="red", linestyle="--", linewidth=1.5, label=f"KPI {KPI_LIMIT}s")
        ax5.set_title("Évolution dans le temps")
        ax5.set_xlabel("Interaction #")
        ax5.set_ylabel("Secondes")
        ax5.legend(fontsize=8)

    # 6. Stacked bar par langue (STT + LLM + TTS)
    ax6 = fig.add_subplot(gs[1, 2])
    if "language" in df.columns and all(c in df.columns for c in ["stt_time", "llm_time", "tts_time"]):
        stack_data = df.groupby("language")[["stt_time", "llm_time", "tts_time"]].mean()
        stack_data.plot(
            kind="bar", stacked=True, ax=ax6,
            color=[PALETTE["stt"], PALETTE["llm"], PALETTE["tts"]],
            edgecolor="white",
        )
        ax6.set_title("Décomposition par langue")
        ax6.set_ylabel("Secondes")
        ax6.tick_params(axis="x", rotation=0)
        ax6.legend(["STT", "LLM", "TTS"], fontsize=8)

    plt.savefig("logs/performance_dashboard.png", dpi=150, bbox_inches="tight")
    print("\n💾 Dashboard sauvegardé : logs/performance_dashboard.png")
    plt.show()


# ══════════════════════════════════════════════════════════════════════
#  ANALYSE STT DÉTAILLÉE (stt_metrics.csv)
# ══════════════════════════════════════════════════════════════════════

def analyze_stt(csv_path: str) -> None:
    if not os.path.exists(csv_path):
        print(f"❌ STT CSV non trouvé : {csv_path}")
        return

    df = pd.read_csv(csv_path)
    if df.empty:
        print("⚠️  stt_metrics.csv est vide.")
        return

    print("\n" + "=" * 60)
    print("🎙️  ANALYSE STT DÉTAILLÉE")
    print("=" * 60)
    print(f"📈 Transcriptions : {len(df)}")

    if "rtf" in df.columns:
        avg_rtf = df["rtf"].mean()
        rtf_ok  = (df["rtf"] <= RTF_LIMIT).mean() * 100
        print(f"\n⚡ RTF moyen : {avg_rtf:.3f}x (objectif < {RTF_LIMIT}x)")
        print(f"   → {rtf_ok:.1f}% des transcriptions sous l'objectif")

    if "language_detected" in df.columns:
        print(f"\n🌍 Langues détectées :")
        print(df["language_detected"].value_counts().to_string())

    if "wer" in df.columns and df["wer"].notna().any():
        wer_data = df["wer"].dropna()
        print(f"\n📝 WER : mean={wer_data.mean():.3f} | min={wer_data.min():.3f} | max={wer_data.max():.3f}")

    # ── Figures STT ───────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle("Smart Teacher — Analyse STT (Whisper)", fontsize=13, fontweight="bold")

    # RTF distribution
    if "rtf" in df.columns:
        axes[0].hist(df["rtf"].dropna(), bins=20, color=PALETTE["stt"], edgecolor="white", alpha=0.85)
        axes[0].axvline(RTF_LIMIT, color="red", linestyle="--", linewidth=2, label=f"Objectif RTF={RTF_LIMIT}")
        axes[0].set_title("Distribution du RTF")
        axes[0].set_xlabel("RTF (ratio)")
        axes[0].set_ylabel("Occurrences")
        axes[0].legend()

    # STT time vs audio duration
    if "stt_time" in df.columns and "audio_duration_sec" in df.columns:
        axes[1].scatter(df["audio_duration_sec"], df["stt_time"],
                        alpha=0.5, color=PALETTE["stt"], s=20)
        max_val = max(df["audio_duration_sec"].max(), df["stt_time"].max())
        axes[1].plot([0, max_val], [0, max_val * RTF_LIMIT], "r--", linewidth=1.5, label=f"RTF = {RTF_LIMIT}")
        axes[1].set_title("STT time vs Durée audio")
        axes[1].set_xlabel("Durée audio (s)")
        axes[1].set_ylabel("Temps STT (s)")
        axes[1].legend()

    # Confiance par langue
    if "language_detected" in df.columns and "language_prob" in df.columns:
        conf_by_lang = df.groupby("language_detected")["language_prob"].mean()
        conf_by_lang.plot(kind="bar", ax=axes[2], color=PALETTE["kpi"], edgecolor="white")
        axes[2].set_title("Confiance langue par code")
        axes[2].set_ylabel("Probabilité moyenne")
        axes[2].set_ylim(0, 1.05)
        axes[2].tick_params(axis="x", rotation=0)
    else:
        axes[2].text(0.5, 0.5, "Données insuffisantes", ha="center", va="center",
                     transform=axes[2].transAxes)

    plt.tight_layout()
    plt.savefig("logs/stt_dashboard.png", dpi=150, bbox_inches="tight")
    print("\n💾 Dashboard STT sauvegardé : logs/stt_dashboard.png")
    plt.show()


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Smart Teacher — Analyse des métriques")
    parser.add_argument("--stt",     action="store_true", help="Affiche aussi l'analyse STT détaillée")
    parser.add_argument("--metrics", default=METRICS_CSV,  help=f"Chemin metrics CSV (défaut: {METRICS_CSV})")
    parser.add_argument("--stt-csv", default=STT_CSV,      help=f"Chemin STT CSV (défaut: {STT_CSV})")
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    analyze_global(args.metrics)

    if args.stt:
        analyze_stt(args.stt_csv)


if __name__ == "__main__":
    main()