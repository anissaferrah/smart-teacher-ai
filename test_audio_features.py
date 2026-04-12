"""
TEST & DEMO — Audio Features Extraction

Ce script démontre comment utiliser le module audio_features.py
pour extraire features prosodiques d'un fichier audio.

Usage:
    python test_audio_features.py

Output:
    ✅ Features extraites et affichées
    💾 Sauvegardées dans Redis (si connecté)
"""

import asyncio
import sys
from pathlib import Path

# Ajouter parent dir au path
sys.path.insert(0, str(Path(__file__).parent))

from modules.audio_features import AudioFeatures, AllAudioFeatures


async def test_audio_extraction():
    """Test extraction de features sur un fichier audio existant"""

    print("=" * 70)
    print("🧪 TEST — Audio Features Extraction (Phase 1)")
    print("=" * 70)

    # Initialiser extracteur
    extractor = AudioFeatures(sr=16000, n_mfcc=13)
    print("\n✅ AudioFeatures initialized")

    # Essayer de connecter à Redis (optionnel)
    try:
        await extractor.connect_redis("localhost", 6379)
        redis_available = True
    except:
        print("⚠️  Redis not available (skipping storage)")
        redis_available = False

    # Charger audio de test
    audio_files = list(Path("media").glob("**/*.wav")) + list(Path("media").glob("**/*.mp3"))

    if not audio_files:
        print("\n⚠️  No audio files found in media/")
        print("   Create a sample or use: python -c \"import librosa; librosa.tone(frequency=440, duration=5, sr=16000)\"\n")
        return

    audio_file = audio_files[0]
    print(f"\n📂 Loading audio: {audio_file}")

    try:
        with open(audio_file, "rb") as f:
            audio_bytes = f.read()

        # Extract all features
        print("\n🎙️  Extracting features...")
        features = await extractor.extract_all(audio_bytes)

        # Display results
        print("\n" + "=" * 70)
        print("📊 EXTRACTED FEATURES")
        print("=" * 70)

        print(f"\n⏱️  Duration: {features.duration:.2f} seconds")
        print(f"📅 Timestamp: {features.timestamp}")

        print(f"\n🎵 PITCH FEATURES:")
        print(f"   F0 Mean: {features.pitch.f0_mean:.1f} Hz")
        print(f"   F0 Std:  {features.pitch.f0_std:.1f} Hz (variability)")
        print(f"   F0 Range: {features.pitch.f0_min:.1f} - {features.pitch.f0_max:.1f} Hz")
        if features.pitch.vibrato_rate:
            print(f"   Vibrato: {features.pitch.vibrato_rate:.1f} Hz @ {features.pitch.vibrato_extent:.1f} semitones")

        print(f"\n🔊 PAUSE FEATURES:")
        print(f"   Speech ratio: {features.pauses.speech_ratio*100:.1f}% (vs silence)")
        print(f"   Pause count: {features.pauses.pause_count}")
        print(f"   Avg pause: {features.pauses.pause_duration_mean:.2f} sec")
        print(f"   Max pause: {features.pauses.max_silence:.2f} sec")

        print(f"\n⚡ SPEECH RATE:")
        print(f"   Words/min: {features.speech_rate.speech_rate_words_per_min:.0f}")
        print(f"   Phonemes/sec: {features.speech_rate.speech_rate_phonemes_per_sec:.1f}")
        print(f"   Articulation rate: {features.speech_rate.articulation_rate:.2f}")

        print(f"\n📢 LOUDNESS:")
        print(f"   RMS Mean: {features.loudness.rms_mean:.4f}")
        print(f"   RMS Std: {features.loudness.rms_std:.4f} (variability)")
        print(f"   RMS Max: {features.loudness.rms_max:.4f}")
        print(f"   Dynamic range: {features.loudness.dynamic_range:.4f}")

        print(f"\n🎼 MFCC (13 Mel-Frequency Cepstral Coefficients):")
        print(f"   Mean: {[f'{x:.2f}' for x in features.mfcc.mean[:5]]} ... (5/13)")
        print(f"   Std:  {[f'{x:.2f}' for x in features.mfcc.std[:5]]} ... (5/13)")

        # Save to Redis if available
        if redis_available:
            print(f"\n💾 Saving to Redis...")
            session_id = "test_session_001"
            saved = await extractor.save_to_redis(session_id, features)
            if saved:
                print(f"   ✅ Features saved under key: session:{session_id}:audio_features:...")

                # Try to retrieve
                retrieved = await extractor.get_latest_features(session_id)
                if retrieved:
                    print(f"   ✅ Retrieved successfully: F0_mean={retrieved.pitch.f0_mean:.1f}Hz")

        print("\n" + "=" * 70)
        print("✅ TEST SUCCESSFUL")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


async def test_confusion_simulation():
    """Simulation: extraire features et prédire confusion (mock)"""

    print("\n\n" + "=" * 70)
    print("🧠 SIMULATION — Confusion Detection (Phase 4 preview)")
    print("=" * 70)

    print("\nPhase 4 utilisera ces features pour détecter confusion:")
    print("  Score = w1*pitch_std + w2*pause_count + w3*speech_rate + w4*loudness_std")
    print("\nExemples:")

    # Mock features: étudiant confus
    print("\n📌 ÉTUDIANT CONFUS:")
    print("   • F0 Std: 15.0 Hz (variabilité élevée)")
    print("   • Pause count: 8 (beaucoup)")
    print("   • Speech rate: 80 wpm (ralenti)")
    print("   • Loudness variability: 0.002 (dynamique faible)")
    print("   → Confusion score: 0.85 (très confus) ❌")

    # Mock features: étudiant clair
    print("\n📌 ÉTUDIANT CLAIR:")
    print("   • F0 Std: 5.0 Hz (stable)")
    print("   • Pause count: 2 (peu)")
    print("   • Speech rate: 150 wpm (normal)")
    print("   • Loudness variability: 0.008 (expressif)")
    print("   → Confusion score: 0.15 (clair) ✅")

    print("\nPhase 4 workflow:")
    print("  1. Extract audio features (THIS module) ✅")
    print("  2. Extract text signals (intent + confusion keywords)")
    print("  3. Extract temporal signals (reaction time)")
    print("  4. Fuse with PSO-weighted sum → confusion_score")
    print("  5. Adapt response: slow TTS, more examples, etc.")


if __name__ == "__main__":
    print("\n🚀 Smart Teacher — Audio Features Testing\n")

    # Run async tests
    asyncio.run(test_audio_extraction())
    asyncio.run(test_confusion_simulation())

    print("\n\n💡 NEXT STEPS:")
    print("   1. Create agent/perception.py (intent + confusion from TEXT)")
    print("   2. Create modules/confusion_detector.py (FUSE audio+text+time)")
    print("   3. Create modules/decision_engine.py (GA/PSO optimization)")
    print("\n✅ Phase 1 Foundation complete!")
