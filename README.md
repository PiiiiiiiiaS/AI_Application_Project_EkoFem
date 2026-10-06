# WasteBuddy

Starter template for the **Development of AI Applications** course final group project.

## Team members

- Aava
- Marjaana
- Patrik
- Piia  

## Problem

Many people struggle with recycling and are unsure how to correctly sort waste items, especially ones that don't clearly fall into a single category. Waste categorization is governed by national legislation, but generic AI advice often gets the specifics wrong, creating real friction and environmental cost when items are sorted incorrectly.

### Intended users
Residents and passers-by who want a quick way to check how to dispose of an item, wherever they happen to be.

### Problem statement
The application solves the problem of not knowing how to correctly categorize and dispose of a waste item, and additionally shows what the material actually becomes after recycling.

### Why AI is appropriate
Identifying an item from a photo or a short, informal description requires flexible, natural-language and visual understanding that rigid, rule-based software can't provide. The specific disposal rule returned will still be grounded in real national regulatory content, not the model's own unverified claims.

## Solution

A user photographs an item, uploads an existing photo or picture, or types a short description. The app identifies the item, classifies it into one disposal category from a fixed list, and returns that category plus what the material is recycled into.

## Main user workflow

1. **User Input:** The user submits a short description of a waste item via the Gradio interface (photo input planned as a next step).
2. **Processing & Guardrails:** The application service layer (`src/services/ai_service.py`) validates the input and formats it into a classification prompt restricted to a fixed list of disposal categories.
3. **Model Response:** The model client calls Ollama locally (`qwen3:8b`) and returns the matched category, which the service layer pairs with the grounded disposal and recycling information before it's returned to the UI.

## Architecture

Below is the initial starter architecture. As your project evolves with additional capabilities, replace or extend this diagram in [`docs/architecture.md`](docs/architecture.md).

```text
User (text, photo support planned)
  ↓
Gradio UI (app/ui.py)
  ↓
Application / AI Service (src/services/ai_service.py)
  ↓
Model Client (src/models/model_client.py)
  ↓
Ollama (Local LLM Server) — qwen3:8b

  + data/finland_waste_categories.json (grounding lookup, not model-generated)
```

> **Core Architectural Rule:** The user interface must NEVER communicate directly with the model client or Ollama. All interactions must pass through the service layer (`ai_service.py`).


## Model

- **Model used:** `qwen3:8b`, run locally via Ollama.
- **Selection rationale:** qwen3:8b is a middle-ground choice. A smaller model risks missing informal phrasing or off-topic input; a larger model would be slower and more hardware-demanding without much expected benefit for a narrow, single-label classification task. qwen3:8b should be capable enough for this task while staying practical to run locally on the team's laptops. This hasn't been tested yet across model sizes and that comparison is planned as part of the evaluation work ahead.

## Additional AI capability

Select at least one additional capability to implement for your final project:

- [ ] RAG (Retrieval-Augmented Generation)
- [ ] Tools / External API integration
- [ ] Model Context Protocol (MCP)
- [ ] Agentic workflow (Model-selected actions based on observations)
- [x] Memory / Persistent state
- [x] Multimodal interaction (Text + Images)
- [ ] Other: ______________________

### Capability justification
Users often find it easier to photograph an item than to describe it themselves, especially for ambiguous items like mixed-material packaging. Memory is useful too: a user often checks several items in one sitting, or comes back later — a small local history of past lookups avoids making them re-describe anything. We plan to add both once the core text-based flow is working end-to-end.

## Setup

### 1. Create the Conda environment

```bash
conda env create -f environment.yml
```

### 2. Activate the environment

```bash
conda activate dev-ai-project
```

### 3. Configure environment variables

Copy `.env.example` to create your local `.env` configuration file:

On Linux / macOS:
```bash
cp .env.example .env
```

On Windows (Command Prompt / PowerShell):
```powershell
copy .env.example .env
```

Ensure `.env` contains valid values for `OLLAMA_BASE_URL` and `MODEL_NAME`:
```env
OLLAMA_BASE_URL=http://localhost:11434
MODEL_NAME=llama3.2
```

### 4. Start Ollama

Make sure Ollama is installed and running locally, then pull your configured model:

```bash
ollama run llama3.2
```

### 5. Run the application

Run the application from the root directory of the project:

```bash
python -m app.main
```

Then open your browser at `http://localhost:7860`.

### 6. Run automated tests

```bash
pytest
```

## Evaluation

Describe your evaluation methodology and summarize key results. Starter test cases can be found in [`evaluation/test_cases.json`](evaluation/test_cases.json).

Refer to [`evaluation/README.md`](evaluation/README.md) for guidelines on defining success, edge cases, and failure scenarios.

## Known limitations

- Highlight known system limitations, unhandled edge cases, or boundaries of current capabilities.

## Future improvements

- List planned feature enhancements, architectural refactorings, or future capabilities.
