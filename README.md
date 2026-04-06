# CrewAI Skeleton (CrewAI v0.30+) — Gemini Multi-tier Example

This repository provides a clean, modular skeleton for a CrewAI-style
application that manages multiple Google Gemini models (tiers) with a focus
on token optimization, clear separation of concerns, and structured outputs
ready for microservice integration.

## 🤖 LLM Cascade Strategy

Nia (el agente de triage) usa una cascada de 3 niveles:

1. **LM Studio (primario)** — Modelo local que ejecutas en tu máquina
   - Sin límites de cuota
   - Privacidad total (no sale de tu red)
   - Recomendado: modelos 7B-14B con contexto >= 8K tokens
   - Ejemplos: `qwen/qwen2.5-14b`, `mistral/mistral-7b-instruct`
   
2. **Gemini (fallback)** — API de Google AI Studio
   - Usa cuando el modelo local no está disponible o falla
   - Free tier: 20 requests/día con `gemini-2.5-flash`
   
3. **Stub determinístico (último recurso)**
   - Clasificador basado en keywords cuando ambos LLMs fallan
   - Útil para tests y desarrollo offline

### ⚠️ Problema común: contexto insuficiente

Si ves este error:
```
WARNING: The number of tokens to keep from the initial prompt is greater 
than the context length. Try to load the model with a larger context length
```

**Solución**: En LM Studio, carga un modelo con más contexto:
- `gemma-3-1b` → contexto pequeño (4K), no recomendado para producción
- `qwen/qwen2.5-14b` → contexto 32K, excelente balance
- `mistral/mistral-7b-instruct` → contexto 32K, rápido

## ⚙️ What's Included

- `.env.example` — example environment variables
- `requirements.txt` — minimal dependencies (works without CrewAI for demo)
- `config/agents.yaml` — sample agent roles and backstories
- `config/tasks.yaml` — sample tasks for Analyst and Architect
- `src/crew.py` — core orchestration, agent classes, model tier factory, and structured output model
- `src/config_models.py` — Pydantic validation models for configs
- `tests/test_crew.py` — unit tests for env loading, LLM creation, and structured output
- `main.py` — entry point to run the crew
- `.github/workflows/ci.yml` — CI workflow for automated testing

## 🎯 Key Design Features

- **Model tiers**: `standard` -> `gemini-1.5-flash`, `premium` -> `gemini-1.5-pro`
- **Agents wired to tiers**: Analyst -> standard, Architect -> premium
- **Structured outputs**: Architect task returns a validated Pydantic model ready for JSON serialization
- **Environment loading**: Resilient loading from `.env` for local dev with Colab fallback
- **Stub LLMs**: Works without external APIs for testing and development
- **Clean architecture**: Lazy imports, no-op decorators, defensive coding

## 📋 Requirements

- **Python 3.10-3.13** (CrewAI >=0.30 requires Python <=3.13)
- For Python 3.14+: The skeleton runs with stub LLMs (no real CrewAI needed for demo)

## 🚀 Run Locally

### 1. Setup Environment

Copy `.env.example` to `.env` and set your Gemini API key (optional for stub demo):

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here
```

### 2. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note**: The current `requirements.txt` excludes CrewAI to support Python 3.14+. The skeleton uses stub LLMs for demonstration. To use real CrewAI and Gemini:

1. Use Python 3.10-3.13
2. Uncomment `crewai>=0.30.0` and `langchain-google-genai` in `requirements.txt`
3. Provide a valid `GEMINI_API_KEY`

### 4. Run the Project

```bash
python main.py
```

**Expected output**:
```
--- Running task_001 -> analyst (Analista)
{
  "task_id": "task_001",
  "model": "gemini-1.5-flash",
  "raw": {...}
}
--- Running task_002 -> architect (Arquitecto)
{
  "decision": "Propuesta de pipeline multi-LLM (tiered routing + prompt cache)",
  "rationale": "[stub response from gemini-1.5-pro]",
  "estimated_tokens": 100,
  "next_steps": [...]
}
```

### 5. Run Tests

```bash
python -m pytest -v
```

**Expected output**:
```
tests/test_crew.py::test_load_env_and_get_key PASSED
tests/test_crew.py::test_create_gemini_client_returns_stub PASSED
tests/test_crew.py::test_architect_output_model PASSED
========================= 3 passed in 0.04s =========================
```

## ☁️ Run on Google Colab

### Option 1: Upload from GitHub

1. In a Colab notebook, clone the repo:
   ```python
   !git clone https://github.com/your-username/crewia-boche.git
   %cd crewia-boche
   ```

2. Set your Gemini API key:
   ```python
   import os
   os.environ['GEMINI_API_KEY'] = 'your_key_here'
   ```

3. Install dependencies and run:
   ```python
   !pip install -r requirements.txt
   !python main.py
   ```

### Option 2: Use Colab Secrets

```python
from google.colab import userdata
import os
os.environ['GEMINI_API_KEY'] = userdata.get('GEMINI_API_KEY')
```

## 🔧 Production Integration

To use real LLM providers instead of stubs:

1. **For CrewAI**: Replace the stub in `create_gemini_client` with:
   ```python
   from crewai import LLM
   return LLM(model=model_name, api_key=api_key)
   ```

2. **For LangChain**: Replace with:
   ```python
   from langchain_google_genai import ChatGoogleGenerativeAI
   return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
   ```

3. Update `requirements.txt` to include the necessary packages

## 📁 Project Structure

```
crewia-boche/
├── .env.example          # Environment template
├── .gitignore           # Git ignore rules
├── requirements.txt     # Python dependencies
├── main.py             # Entry point
├── README.md           # This file
├── config/
│   ├── agents.yaml     # Agent configurations
│   └── tasks.yaml      # Task definitions
├── src/
│   ├── __init__.py
│   ├── crew.py         # Main Crew orchestration
│   └── config_models.py # Pydantic validation models
├── tests/
│   └── test_crew.py    # Unit tests
└── .github/
    └── workflows/
        └── ci.yml      # GitHub Actions CI

```

## 🧪 Testing Strategy

- **Unit tests**: Validate env loading, LLM client creation, and Pydantic models
- **CI/CD**: GitHub Actions runs tests on every push/PR
- **Stub LLMs**: Enable testing without API keys or network calls

## 🎓 Next Steps

1. **Add real LLM integration**: Uncomment CrewAI/LangChain in requirements
2. **Extend validation**: Add more Pydantic models for config files
3. **Add logging**: Integrate structured logging (e.g., structlog)
4. **Add metrics**: Track token usage, latency, and costs
5. **Add retry logic**: Implement exponential backoff for API calls
6. **Add async support**: Use async/await for concurrent task execution

## 📝 Notes

- The code uses defensive programming with lazy imports and fallback stubs
- Pydantic v2 is used for all data validation
- The architecture is designed to be modular and easily extensible
- Config files use YAML for human-friendly editing

---

**Status**: ✅ Fully functional with stub LLMs. Ready for real LLM integration.
