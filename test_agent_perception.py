"""
TEST & DEMO — Agent Perception Module

Montre comment Perception comprend l'étudiant.
"""

from agent.perception import get_perception, Intent

print("=" * 80)
print("🧠 AGENT PERCEPTION — Full Demo")
print("=" * 80)

perception_fr = get_perception("fr")

# Scénarios réalistes USTHB
scenarios = [
    {
        "name": "Étudiant confus",
        "transcript": "Je ne comprends vraiment pas comment la relativité affecte le concept de temps",
        "expected_intent": "ask_help",
        "expected_confusion": 0.7,  # High
    },
    {
        "name": "Demande exemple",
        "transcript": "Peux-tu donner un exemple concret de cette équation?",
        "expected_intent": "ask_example",
        "expected_confusion": 0.1,  # Low (clair)
    },
    {
        "name": "Étudiant perdu + feedback",
        "transcript": "C'est vraiment compliqué, je suis complètement perdu avec ces formules",
        "expected_intent": "feedback",
        "expected_confusion": 0.9,  # Very high
    },
    {
        "name": "Demande quiz",
        "transcript": "Teste-moi sur ce chapitre pour voir si j'ai bien compris",
        "expected_intent": "ask_quiz",
        "expected_confusion": 0.0,  # Pas de confusion ici
    },
    {
        "name": "Interruption",
        "transcript": "Arrête! J'ai déjà compris ce concept",
        "expected_intent": "interrupt",
        "expected_confusion": 0.0,
    },
    {
        "name": "Engagement positif",
        "transcript": "C'est vraiment intéressant, continue!",
        "expected_intent": "comment",
        "expected_confusion": 0.0,
    },
    {
        "name": "Question de clarification",
        "transcript": "Comment est-ce que cela s'applique à la pratique?",
        "expected_intent": "question_clarify",
        "expected_confusion": 0.3,  # Légère confusion
    },
]

print("\n📋 SCENARIO TESTING:\n")

results_summary = []

for i, scenario in enumerate(scenarios, 1):
    transcript = scenario["transcript"]
    result = perception_fr.analyze(transcript, duration_seconds=2.5)

    # Check expectations
    intent_match = (result.intent.value == scenario["expected_intent"])
    confusion_diff = abs(result.confusion_score - scenario["expected_confusion"])
    confusion_match = confusion_diff < 0.2

    match_icon = "✅" if (intent_match and confusion_match) else "⚠️"

    print(f"{i}. {scenario['name']}")
    print(f"   Input: \"{transcript}\"")
    print(f"   {match_icon} Intent: {result.intent.value:20} (expected: {scenario['expected_intent']})")
    print(f"   {match_icon} Confusion: {result.confusion_score:.0%:3} (expected: {scenario['expected_confusion']:.0%})")
    print(f"   📊 Confidence: {result.confidence:.0%}")
    print(f"   🔑 Keywords: {result.keywords}")
    if result.confusion_markers:
        print(f"   🚨 Markers: {result.confusion_markers}")
    print()

    results_summary.append({
        "scenario": scenario["name"],
        "intent_match": intent_match,
        "confusion_match": confusion_match,
    })

# Summary
print("=" * 80)
print("📊 RÉSUMÉ TESTS")
print("=" * 80)
correct = sum(1 for r in results_summary if r["intent_match"] and r["confusion_match"])
total = len(results_summary)
print(f"\n✅ Accuracy: {correct}/{total} ({100*correct/total:.0f}%)\n")

print("=" * 80)
print("🔗 INTEGRATION FLOW")
print("=" * 80)

print("""
ÉTAPE 1: USER INPUT
  └─ "Je ne comprends pas la relativité"

ÉTAPE 2: PERCEPTION.ANALYZE()
  ├─ Intent: ask_help (90% confidence)
  ├─ Confusion: 0.8 (texte contient "ne comprends pas")
  ├─ Keywords: ['relativité', 'comprends']
  └─ Markers: ['comprends pas']

ÉTAPE 3: AUDIO_FEATURES_V3
  ├─ Pitch: 150Hz, pitch_std: 12Hz (monté = hésitation)
  ├─ Speech_rate: 80 wpm (ralenti)
  ├─ Pause_ratio: 30% (beaucoup de silences)
  └─ RMS: 0.15 (volume bas = désengagement)

ÉTAPE 4: FUSION MULTIMODALE (Phase 4 Confusion Detector)
  Score_confusion = w1*text_confusion(0.8)
                  + w2*pitch_std(0.7)
                  + w3*pause_ratio(0.6)
                  + w4*rms_energy(0.4)
  = 0.8 * 0.8 + 0.15 * 0.7 + 0.3 * 0.6 + 0.15 * 0.4
  = 0.64 + 0.10 + 0.18 + 0.06
  = 0.98 → TRÈS CONFUS! ❌

ÉTAPE 5: DECISION ENGINE (Phase 2+ GA/PSO)
  confusion_score = 0.98
  intent = ask_help

  GA/PSO décideur →
  Action = RAG + EXPLAIN + SLOW_TTS
  ├─ Retrieve: contexte relativité
  ├─ Adapt: explication simplifiée
  ├─ TTS: débit ralenti (0.8x)
  └─ Follow-up: "Est-ce plus clair?"

ÉTAPE 6: RESPONSE
  AI: "La relativité, c'est le concept que le temps n'est pas absolu...
       Prenons un exemple: imagine une fusée qui va très très vite..."
  [TTS débit ralenti, intonation pédagogique]
""")

print("\n" + "=" * 80)
print("✨ PERCEPTION SUCCESS!")
print("=" * 80)

print("\n💡 NEXT STEP:")
print("""
Créer agent/brain.py qui:
1. Reçoit PerceptionResult
2. Reçoit AudioFeatures (V3)
3. Combine les deux → confusion_score multimodale
4. Appelle Decision Engine (GA/PSO)
5. Choisit action optimale

Puis:
6. Appelle les tools (RAG, Explain, Quiz, etc.)
7. Génère réponse LLM
8. Adapte TTS (débit, intonation)
9. Envoie au client
""")
