"""
Smart Teacher — Performance Metrics Analysis Tool.

Analyzes CSV logs from learning sessions and generates comprehensive
visualization dashboard for KPI tracking and performance optimization.

Metrics Tracked:
    - Total response time distribution (vs KPI 5s threshold)
    - Component timing breakdown (STT / LLM / TTS)
    - Performance by language
    - KPI compliance rate
    - Real-Time Factor (RTF) for STT
    - Temporal trends

Output:
    - Console statistics and summaries
    - Multi-panel matplotlib dashboard
    - PNG export to logs/metrics_dashboard.png

Usage:
    # Analyze main metrics.csv
    python analyze_metrics.py
    
    # Include STT-specific analysis
    python analyze_metrics.py --stt
    
    # Analyze custom CSV
    python analyze_metrics.py <path_to_csv>

Requires:
    - pandas, matplotlib, numpy
    - CSV files from logger (metrics.csv, stt_metrics.csv)

Output Files:
    - Dashboard figure displayed/saved
    - Statistics printed to stdout
"""

import argparse
import logging
import os
import sys
from __future__ import annotations
from pathlib import Path
from typing import Optional

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import Config

# ════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("SmartTeacher.Metrics")

METRICS_CSV: str = Config.CSV_LOG_FILE
STT_CSV: str = Config.STT_LOG_FILE
KPI_LIMIT: float = Config.MAX_RESPONSE_TIME  # 5.0s
RTF_LIMIT: float = Config.TARGET_RTF  # 0.5

PALETTE: dict = {
    "stt": "#4e79a7",
    "llm": "#f28e2b",
    "tts": "#59a14f",
    "total": "#e15759",
    "kpi": "#76b7b2",
}


# ════════════════════════════════════════════════════════════════════════
# GLOBAL METRICS ANALYSIS
# ════════════════════════════════════════════════════════════════════════


def analyze_global(csv_path: str) -> Optional[pd.DataFrame]:
    """
    Analyze global performance metrics from main CSV.
    
    Generates console statistics and visualization dashboard.
    
    Parameters
    ----------
    csv_path : str
        Path to metrics.csv file
    
    Returns
    -------
    pd.DataFrame or None
        Loaded dataframe if successful, None if file not found/empty
    """
    if not os.path.exists(csv_path):
        log.error(f"File not found: {csv_path}")
        log.info("Launch server and perform interactions first.")
        return None

    df = pd.read_csv(csv_path)
    if df.empty:
        log.warning("CSV is empty — no data to analyze")
        return None

    # Console statistics
    print("\n" + "=" * 70)
    print("📊 SMART TEACHER — PERFORMANCE ANALYSIS")
    print("=" * 70)
    print(f"\n📁 File: {csv_path}")
    print(f"📈 Interactions: {len(df)}")

    # Timing statistics
    timing_cols = [c for c in ["stt_time", "llm_time", "tts_time", "total_time"] if c in df.columns]
    if timing_cols:
        print("\n⏱️  TIMING (seconds):")
        print(df[timing_cols].describe().round(3).to_string())

    # KPI compliance
    if "meets_kpi" in df.columns:
        kpi_rate = df["meets_kpi"].mean() * 100
        print(f"\n🎯 KPI Compliance (<{KPI_LIMIT}s): {kpi_rate:.1f}%")

    # Language distribution
    if "language" in df.columns:
        print(f"\n🌍 Languages Detected:")
        print(df["language"].value_counts().to_string())

    # Visualization
    create_dashboard(df)

    return df


def create_dashboard(df: pd.DataFrame) -> None:
    """
    Create multi-panel performance dashboard.
    
    Parameters
    ----------
    df : pd.DataFrame
        Metrics dataframe
    """
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle("SmartTeacher — Performance Dashboard", fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.35)

    # Panel 1: Total time distribution
    ax1 = fig.add_subplot(gs[0, 0])
    if "total_time" in df.columns:
        ax1.hist(
            df["total_time"].dropna(),
            bins=20,
            color=PALETTE["total"],
            edgecolor="white",
            alpha=0.85
        )
        ax1.axvline(
            KPI_LIMIT,
            color="red",
            linestyle="--",
            linewidth=2,
            label=f"KPI = {KPI_LIMIT}s"
        )
        ax1.set_title("Total Response Time Distribution")
        ax1.set_xlabel("Seconds")
        ax1.set_ylabel("Count")
        ax1.legend()

    # Panel 2: Component timing comparison
    ax2 = fig.add_subplot(gs[0, 1])
    comp_cols = [c for c in ["stt_time", "llm_time", "tts_time"] if c in df.columns]
    if comp_cols:
        means = df[comp_cols].mean()
        labels = [c.replace("_time", "").upper() for c in comp_cols]
        colors = [PALETTE.get(c.replace("_time", ""), "#999") for c in comp_cols]
        ax2.bar(labels, means, color=colors, edgecolor="white", alpha=0.85)
        ax2.set_title("Average Component Timing")
        ax2.set_ylabel("Seconds")
        ax2.tick_params(axis="x", rotation=45)

    # Panel 3: KPI compliance bar
    ax3 = fig.add_subplot(gs[0, 2])
    if "meets_kpi" in df.columns:
        kpi_counts = df["meets_kpi"].value_counts()
        labels = ["Meets KPI", "Exceeds KPI"]
        values = [kpi_counts.get(1, 0), kpi_counts.get(0, 0)]
        colors_kpi = [PALETTE["kpi"], "#d62728"]
        ax3.bar(labels, values, color=colors_kpi, edgecolor="white", alpha=0.85)
        ax3.set_title("KPI Compliance Distribution")
        ax3.set_ylabel("Count")

    # Panel 4: Performance by language
    ax4 = fig.add_subplot(gs[1, 0])
    if "language" in df.columns and "total_time" in df.columns:
        lang_perf = df.groupby("language")["total_time"].agg(["mean", "std"])
        ax4.bar(lang_perf.index, lang_perf["mean"], color=PALETTE["total"], alpha=0.85)
        ax4.set_title("Average Timing by Language")
        ax4.set_ylabel("Seconds")
        ax4.set_xlabel("Language")

    # Panel 5: Cumulative timing stacked
    ax5 = fig.add_subplot(gs[1, 1])
    time_cols = ["stt_time", "llm_time", "tts_time"]
    available_cols = [c for c in time_cols if c in df.columns]
    if available_cols:
        means = [df[c].mean() for c in available_cols]
        labels = [c.replace("_time", "").upper() for c in available_cols]
        colors = [PALETTE.get(c.replace("_time", ""), "#999") for c in available_cols]
        ax5.barh(["Average"], [sum(means)], color=colors[0], alpha=0.85, label=labels[0])
        for i, (mean, label, color) in enumerate(zip(means[1:], labels[1:], colors[1:])):
            ax5.barh(["Average"], [mean], left=sum(means[:i+1]), color=color, alpha=0.85, label=label)
        ax5.set_title("Total Time Composition")
        ax5.set_xlabel("Seconds")
        ax5.legend(loc="upper right")
        ax5.set_xlim([0, sum(means) * 1.1])

    # Panel 6: Time trend
    ax6 = fig.add_subplot(gs[1, 2])
    if "total_time" in df.columns:
        times = df["total_time"].dropna()
        if len(times) > 1:
            x = range(len(times))
            ax6.plot(x, times, marker="o", linestyle="-", color=PALETTE["total"], alpha=0.7)
            ax6.axhline(KPI_LIMIT, color="red", linestyle="--", linewidth=2, label=f"KPI={KPI_LIMIT}s")
            ax6.set_title("Response Time Over Time")
            ax6.set_xlabel("Interaction #")
            ax6.set_ylabel("Seconds")
            ax6.legend()
            ax6.grid(True, alpha=0.3)

    # Save and display
    output_path = Path(Config.LOG_DIR) / "metrics_dashboard.png"
    plt.savefig(str(output_path), dpi=100, bbox_inches="tight")
    log.info(f"Dashboard saved: {output_path}")
    plt.show()


# ════════════════════════════════════════════════════════════════════════
# STT-SPECIFIC ANALYSIS
# ════════════════════════════════════════════════════════════════════════


def analyze_stt(csv_path: str) -> Optional[pd.DataFrame]:
    """
    Analyze Speech-to-Text specific metrics (RTF, latency, accuracy).
    
    Parameters
    ----------
    csv_path : str
        Path to stt_metrics.csv file
    
    Returns
    -------
    pd.DataFrame or None
        Loaded dataframe if successful, None if file not found
    """
    if not os.path.exists(csv_path):
        log.warning(f"STT metrics file not found: {csv_path}")
        return None

    df = pd.read_csv(csv_path)
    if df.empty:
        log.warning("STT CSV is empty")
        return None

    print("\n" + "=" * 70)
    print("🎤 STT METRICS ANALYSIS")
    print("=" * 70)
    print(f"Records: {len(df)}")

    if "rtf" in df.columns:
        avg_rtf = df["rtf"].mean()
        print(f"\n📊 Real-Time Factor (RTF):")
        print(f"   Average: {avg_rtf:.3f} ({avg_rtf < RTF_LIMIT and '✅' or '⚠️'} target={RTF_LIMIT})")
        print(f"   Range:   {df['rtf'].min():.3f} to {df['rtf'].max():.3f}")

    if "duration" in df.columns:
        print(f"\n⏱️  Audio Duration:")
        print(f"   Mean:    {df['duration'].mean():.2f}s")
        print(f"   Total:   {df['duration'].sum():.0f}s")

    if "confidence" in df.columns:
        print(f"\n📈 Confidence:")
        print(f"   Mean: {df['confidence'].mean():.3f}")
        print(f"   Min:  {df['confidence'].min():.3f}")

    print("=" * 70)
    return df


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════


def main() -> int:
    """
    Main analysis workflow.
    
    Returns
    -------
    int
        Exit code (0=success, 1=error)
    """
    parser = argparse.ArgumentParser(
        description="Smart Teacher — Analyze performance metrics"
    )
    parser.add_argument(
        "--stt",
        action="store_true",
        help="Also analyze STT-specific metrics"
    )
    parser.add_argument(
        "csv",
        nargs="?",
        default=METRICS_CSV,
        help="Path to metrics CSV file"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("📊 SMART TEACHER — METRICS ANALYZER")
    print("=" * 70)

    # Analyze main metrics
    df = analyze_global(args.csv)
    if df is None:
        return 1

    # Analyze STT if requested
    if args.stt:
        analyze_stt(STT_CSV)

    return 0


if __name__ == "__main__":
    sys.exit(main())
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