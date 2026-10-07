# Architecture Documentation

This document describes the baseline architectural layer of the application and provides guidance on extending it for your team project.

## Baseline Architecture

The starter application follows a clean layered separation of concerns:

```text
User
  ↓
Gradio UI (app/ui.py)
  ↓
Application / AI Service (src/services/ai_service.py)
  ↓
Model Client (src/models/model_client.py)
  ↓
Ollama (Local Inference Server)
  ↓
Local Model (e.g., llama3.2)
```

### Core Design Rules

1. **Strict UI Isolation:** The Gradio user interface (`app/ui.py`) MUST NOT directly instantiate `OllamaModelClient` or make direct API calls to Ollama. Instead, it delegates work to the service layer.
2. **Controlled Failure Handling:** The model client handles low-level runtime exceptions (e.g., connection errors or missing models). The service layer then transforms these technical issues into messages users can understand.
3. **Data Schemas:** Request inputs and response structures are validated using Pydantic models in `src/schemas/responses.py`.

---

## Current Implementation: WasteBuddy

WasteBuddy extends the baseline architecture with a second, vision-capable model for image input, a grounding step that keeps disposal facts out of the model's hands entirely, a scope check that keeps off-topic input out of the classifier's hands, a small local memory of what a user has already checked, an external-API step that finds the nearest drop-off point, and a Stop button that lets the user abandon a running search:

```text
User (photo or text)
  ↓
Gradio UI (app/ui.py, app/drop_off_ui.py)
  ↓
Service layer
  ├─ src/services/ai_service.py       classification + grounding
  ├─ src/services/search_control.py   Stop search (cancellable wrapper)
  ├─ src/services/history.py          local memory of past lookups
  └─ src/services/drop_off.py         drop-off point lookup
  ↓                                        ↓
Model Client (src/models/model_client.py)   Kierrätys.info API (external, read-only)
  ├─ moondream  (vision model: photo path only, names the item, nothing else)
  └─ qwen3:8b   (text model: picks ONE category label from a fixed list,
                 or flags the input as off_topic)
  ↓
Ollama (Local Inference Server)

  + data/finland_waste_categories.json  (deterministic lookup: belongs/
    excludes/recycled_into facts for all 12 Finnish household waste
    categories, sourced from InfoFinland, Rinki, HSY, LSJH and others)
  + data/user_history.json  (local log of the user's own past lookups,
    read and written only by src/services/history.py)
```

The UI only talks to the service layer. The drop-off section (`app/drop_off_ui.py`) is an optional module: `app/ui.py` imports it inside a guarded `try/except`, so deleting that file (together with `src/services/drop_off.py` and `tests/test_drop_off.py`) removes the feature without breaking the rest of the app.

### Main flow, step by step

1. The user types a description or uploads a photo in the "Check an item" section.
2. For a photo, `moondream` first produces a short item description. For text, the typed description is used directly.
3. `qwen3:8b` picks one category id from the fixed list, or flags the input as off topic.
4. The category id is looked up in `data/finland_waste_categories.json`, which supplies the category name and the `recycled_into` fact.
5. The answer is shown in the "Answer" section and, if it is a real classification, saved to the history file.
6. The category id is also passed to the UI. If that category has a drop-off option, the "Where to take it" section appears directly below, already knowing what is being dropped off, so the user is never asked again.
7. The user can press "Stop search" at any point while step 2 or 3 is running.

### UI sections

The page is a single column of clearly separated sections, in this order: **Check an item** (text and photo tabs) next to **Answer** (with the Stop search button shown only while a search runs), then **Where to take it** (only after an answer with a drop-off option), then **History** (the last 5 checked items, collapsed by default, at the very bottom so it does not push the drop-off section out of sight).

### Grounding principle

The model is never trusted to state a disposal fact on its own. Its only
job, in both the text and photo paths, is to output a short item name and
pick a single category id from a fixed list supplied in the prompt (see
`_build_classification_prompt` in `ai_service.py`), or to flag that the
input isn't a waste item at all. Once a category id comes back,
`_parse_classification_response` looks it up directly in
`data/finland_waste_categories.json` and pulls the real `recycled_into`
fact from there. If the model returns anything that isn't a recognized
category id (and isn't the off-topic flag either), the system falls back
safely to `mixed_waste` rather than guessing. This means the disposal
information a user sees was written by a human source (InfoFinland /
Rinki / HSY / LSJH and others), never generated freeform by the LLM.

The dataset has 12 categories. Construction and renovation waste and
garden waste were added after the first version. Both carry a note that
rules differ between municipalities and waste companies, and the garden
waste note is also shown to the user as a disclaimer in the drop-off
section.

**Response structure:** Following the project's Pydantic convention
(`src/schemas/responses.py`), the result is validated against a
structured schema rather than parsed as free-form text:

```python
class RecyclingResponse(BaseModel):
    identified_item: str
    disposal_category: str
    recycled_into: str | None = None
```

`identified_item` and `disposal_category` come from the model's
classification step; `recycled_into` is looked up from the reference
dataset, not generated by the model. It describes where the material
actually ends up (e.g. "melted down into new glass bottles"), not a
personal reuse idea for the user.

**Image path:** When a photo is provided, `moondream` is called first
with a prompt asking only for a short item-plus-material description
(e.g. "cardboard pizza box"), and explicitly told to ignore any printed
text or branding on the item. That description is then classified using
the exact same `process_recycling_query` logic used for typed text
input, so both input paths converge on one shared, tested classification
path (off-topic check included) rather than diverging into separate
handling. This two-step design (vision names the item; the text model
classifies it) was adopted after testing showed `moondream` could not
reliably do both identification and category selection in a single
combined call.

### Scope handling (off-topic input)

An earlier evaluation round (`evaluation/evaluation_results.md`, case-12)
found that a question unrelated to waste sorting, such as "What is the
capital of France?", was still forced into a nonsensical category like
"Mixed waste" instead of being recognized as out of scope. The fix keeps
the same single-model-call architecture rather than adding a second model
or a separate classifier: `_build_classification_prompt` now instructs
the model that if the input does not describe a physical waste item at
all, it should respond with the sentinel `Category: off_topic` instead of
picking from the real category list. `_parse_classification_response`
checks for that sentinel explicitly and returns `None` for the matched
category (distinct from an unrecognized reply, which still falls back to
`mixed_waste`, since a malformed answer is not the same thing as a
deliberate off-topic judgment). `AIService.process_recycling_query` then
raises `OutOfScopeInput`, which `generate_recycling_response` and
`generate_recycling_response_from_image` catch and turn into a short,
friendly redirect back to waste sorting.

**Honest limitation:** this scope check is not a separate, independently
verified filter. It is the same model call that also does the
classification, just given an extra option, so its judgment of what
counts as "off topic" is only as reliable as the model itself. Unusual or
borderline phrasing may occasionally be misrouted in either direction.
This is documented in the README's Known limitations rather than
overstated as a solved problem.

### Memory (persistent state)

`src/services/history.py` is WasteBuddy's memory / persistent-state
capability: a small local JSON file, `data/user_history.json`, storing the
user's last 50 successfully classified items (never an off-topic redirect
or an error), each with its disposal category, `recycled_into` fact, and
a timestamp. The UI never reads or writes this file directly. It only
calls `history.get_recent(limit)`, matching the same core design rule
already used for the model client and the waste-category dataset. The
file is written only after a real, grounded classification succeeds
(`ai_service._record_history_safely`), and a write failure never breaks
the user-facing response, since remembering past lookups is a convenience
on top of the current answer, not a requirement for it. This file is
per-machine, local-only, and excluded from version control in
`.gitignore`, the same treatment as any other user-specific runtime data.

The History section in the UI shows the five most recent entries and is collapsed by default. A search that is stopped by the user is never written to it.

### External API: drop-off point finder

`src/services/drop_off.py` is WasteBuddy's tool / external API integration. It looks up public collection points from the **Kierrätys.info open API v3.1** (maintained by Suomen Kiertovoima ry, KIVO), a free, read-only API that needs an API key.

**How the category drives the lookup.** The category id from the classification step is mapped to a Kierrätys.info material code (`MATERIAL_CHOICES`):

| Category id | Drop-off section | Notes |
|---|---|---|
| `hazardous_waste`, `electrical_equipment`, `textiles` | yes | Cannot be recycled at home |
| `construction_waste`, `garden_waste` | yes | Regional rules differ; disclaimer shown, garden waste especially |
| `paper`, `cardboard`, `glass`, `metal`, `plastic` | yes, softer wording | "If your home has no collection for it, take it to a collection point near you" |
| `biowaste`, `mixed_waste` | no | Go in the household bins |

The intro text for each category (`drop_off_intro`) is written to be positive and practical rather than a warning.

**Two ways to search.** "Use my location" asks the browser for coordinates (the browser asks the user for permission; the code that runs in the browser lives in `app/drop_off_ui.py`). The service then searches by radius, starting at 10 km and widening to 30 km and 100 km until something is found, and sorts the results by distance. "Find by place" searches by municipality or postal code; those results are not sorted by distance, and the UI says so.

**Design points.**

- The UI never calls the API. It calls `lookup_by_location` and `lookup_by_text`, which return ready-to-show Markdown and never raise: a missing API key, a network error, a timeout (10 s) or an empty result all become a short, friendly message.
- The API key comes from `KIERRATYS_INFO_API_KEY` in the local `.env` file and is never committed. Each installation needs its own key. Without a key, the rest of the app works and the drop-off section explains how to get one.
- **Privacy:** the location is used only to build the request. It is not stored, not written to the history file and never sent to the language model.
- The API does not label places as "ekopiste" or "sorttiasema"; it lists generic collection spots with the material codes each accepts, which is why the search is by material code.

### Stop search (cancellation)

`src/services/search_control.py` lets the user abandon a running search with the "Stop search" button.

- `CancelToken` wraps a `threading.Event`. The UI creates one per search.
- `CancellableAIService` subclasses `AIService` and checks the token before and after the model call. If the user has pressed Stop, it raises `SearchCancelled` before the result is returned. `ai_service.py` does not need to know about this exception: its existing catch-all error handling turns it into an error string, and because the exception is raised before `_record_history_safely` runs, a stopped search is never saved to History. The wrapper also stores the category id of a successful classification so the UI can show the drop-off section.
- In `app/ui.py` the button is hidden until a search starts. Pressing it cancels the token and uses Gradio's `cancels=` to drop the running event, shows "Search stopped. Nothing was saved to History.", unlocks the input fields again and keeps the drop-off section hidden.

**Honest limitation:** the model call itself cannot be interrupted, because the Ollama client is called without streaming. After Stop the model may keep running in the background until it finishes, but its result is discarded. Real cancellation would need streaming responses (listed under future improvements in the README).

### Testing

Automated tests (`pytest`) cover the AI service, history, the drop-off service (every category code and intro, wording rules, parsing and error handling, with a fake API fetcher so no network or key is needed) and search cancellation. `tests/test_drop_off.py` also checks that the category keys in `MATERIAL_CHOICES` match the data file, so the two cannot silently drift apart.

---

## Extension Points for Course Projects

As your project team designs and implements your additional AI capability, extend this baseline architecture. Potential capability extensions include:

- **RAG (Retrieval-Augmented Generation):** Insert document parsing, chunking, vector embeddings, and vector database retrieval into the service layer to ground model responses in domain documents.
- **Tools & External APIs:** Integrate tool execution functions into the service layer allowing the model to query web services or local python utilities. **(Implemented: see "External API: drop-off point finder" above.)**
- **Model Context Protocol (MCP):** Connect your service layer to standard MCP servers to access external tools and context providers.
- **Agent Workflows:** Implement observation-action loops controlled by application code to handle dynamic multi-step tasks.
- **Memory & Conversation State:** Store session history or persistent state across user interactions. **(Implemented: see "Memory (persistent state)" above.)**
- **Multimodal Models:** Update the model client and UI payload to pass image data to vision-enabled local models. **(Implemented: see "Current Implementation" above.)**
