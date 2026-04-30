#!/usr/bin/env bash
# install_ollama.sh — Install Ollama and pull the llama3 model for BlueBird AI Insights.
# Safe to run multiple times; skips steps that are already complete.
# Usage: bash scripts/install_ollama.sh [--model <name>]
set -euo pipefail

MODEL="${AI_INSIGHTS_MODEL:-llama3}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "==> BlueBird AI Insights — Ollama setup (model: $MODEL)"

# 1. Check / install Ollama
if command -v ollama &>/dev/null; then
    echo "  ✓ Ollama already installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
else
    echo "  → Installing Ollama..."
    if [[ "$(uname)" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install ollama
        else
            curl -fsSL https://ollama.com/install.sh | sh
        fi
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    echo "  ✓ Ollama installed"
fi

# 2. Ensure Ollama service is running
if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    echo "  → Starting Ollama service..."
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: start as background process
        nohup ollama serve &>/tmp/ollama.log &
        sleep 3
    else
        # Linux: use systemd if available, otherwise background
        if command -v systemctl &>/dev/null && systemctl list-units --type=service | grep -q ollama; then
            systemctl start ollama
        else
            nohup ollama serve &>/tmp/ollama.log &
            sleep 3
        fi
    fi
fi

# Wait up to 15s for Ollama to become ready
echo "  → Waiting for Ollama API..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo "  ✓ Ollama API ready"
        break
    fi
    if [[ $i -eq 15 ]]; then
        echo "  ✗ Ollama did not become ready in time. Check /tmp/ollama.log"
        exit 1
    fi
    sleep 1
done

# 3. Pull model if not already present
EXISTING=$(curl -sf http://localhost:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
names = [m.get('name','') for m in data.get('models', [])]
print('\n'.join(names))
" 2>/dev/null || true)

if echo "$EXISTING" | grep -q "$MODEL"; then
    echo "  ✓ Model '$MODEL' already present"
else
    echo "  → Pulling model '$MODEL' (this may take several minutes)..."
    ollama pull "$MODEL"
    echo "  ✓ Model '$MODEL' pulled"
fi

echo ""
echo "==> AI Insights setup complete."
echo "    Set AI_INSIGHTS_GLOBAL_ENABLED=true in your .env to enable the feature."
echo "    Then enable per-tenant from the Super Admin dashboard."
