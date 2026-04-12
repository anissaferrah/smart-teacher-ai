#!/bin/bash
# Initialize Ollama with Mistral model on first startup

echo "🚀 Initializing Ollama with Mistral..."

# Wait for Ollama to be ready
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama is ready"
        break
    fi
    echo "⏳ Waiting for Ollama... ($i/30)"
    sleep 2
done

# Pull Mistral model
echo "📥 Pulling Mistral model (this takes a few minutes)..."
ollama pull mistral

echo "✅ Mistral model ready!"
echo "🎓 Smart Teacher is ready to use!"
