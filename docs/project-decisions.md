# Project decisions

Use this decision log to document significant technical and architectural choices made by your team during development.

## Decision 1 — Model selection

**Decision:** `qwen3:8b` as the text model and `moondream` as the vision model, both run locally through Ollama.

**Alternatives considered:**

- Using `moondream` for both identifying the item and choosing the category in one call (tested; it was not reliable enough).
- A fallback text model if `qwen3:8b` turned out to be unreliable (not needed in practice).

**Why we chose this:** `qwen3:8b` was slow for open-ended questions, but evaluation showed it is reliable for the narrower task WasteBuddy gives it: pick one category id from a fixed list. `moondream` (about 1.6B parameters) leaves VRAM headroom for the text model. Testing showed it cannot reliably identify an item and choose a category in one call, so it only names the item and the text model classifies it.

---

## Decision 2 — Additional AI capability

**Decision:** Multimodal interaction (text and photo), memory / persistent state, and tools / external API integration (drop-off point finder).

**Why it is needed:**

- Photographing an item is often easier than describing it, especially for mixed-material packaging.
- A returning user can see the last few items they checked.
- Knowing the right category is only half of the answer. Users also need to know where to take the item when it cannot be recycled at home.

**Alternatives considered:**

- RAG over full national regulatory documents (kept as a future improvement; a curated reference table is used instead).
- A static list of drop-off points in the data file (collection points change and vary by area, while the Kierrätys.info API is maintained and covers the whole country).

---

## Decision 3 — Architecture

**Decision:** A layered architecture: Gradio UI → service layer → model client → Ollama. The UI never talks to the model client, Ollama, the API or the data files directly.

**Why:** It keeps the interface replaceable, makes the service layer testable without a running model (fake clients and fake API fetchers), and puts all error handling in one place.

---

## Decision 4 — Disposal facts come from a dataset, not from the model

**Decision:** The model only names the item and picks a category id from a fixed list (or flags the input as off topic). The category name and the `recycled_into` fact are looked up in `data/finland_waste_categories.json`. An unrecognised model reply falls back to `mixed_waste`.

**Alternatives considered:** Letting the model write the disposal advice freely.

**Why we chose this:** Generic AI advice often gets Finnish specifics wrong. Grounding every disposal fact in curated sources (InfoFinland, Rinki, HSY, LSJH and others) keeps the answer correct and traceable. The dataset now has 12 categories; construction and renovation waste and garden waste were added so the drop-off finder covers common cases. Both carry a note that rules differ between municipalities and waste companies.

---

## Decision 5 — Off-topic input is handled in the same model call

**Decision:** The classification prompt gives the model an `off_topic` option instead of adding a second model or a separate filter. Off-topic input gets a friendly redirect and is never saved to History.

**Why:** Evaluation case 12 ("What is the capital of France?") was forced into "Mixed waste". A second model would add several minutes of waiting on this hardware.

**Trade-off:** The check is only as reliable as the model. Borderline input can be misrouted either way. This is listed in the README's known limitations.

---

## Decision 6 — The drop-off point is driven by the item's category

**Decision:** After an answer, the "Where to take it" section appears on the main page and already knows the category, so the user is never asked again what they want to drop off. It uses the Kierrätys.info open API (v3.1) and offers "Use my location" (nearest first) or a search by municipality or postal code. Biowaste and mixed waste have no section because they go in the household bins. For packaging materials the wording is softer: "if your home has no collection for it, take it to a collection point".

**Alternatives considered:** A separate page or a dropdown where the user picks the material again.

**Why we chose this:** It removes a repeated question and keeps the answer and the next step in one place. The wording stays positive and practical.

**Privacy:** The location is used only for the request. It is not stored, not written to History and never sent to the language model.

**Consequences:** Each installation needs its own free Kierrätys.info API key in `.env`. Without a key the rest of the app still works and the section explains how to get one. The feature is optional: removing `app/drop_off_ui.py`, `src/services/drop_off.py` and `tests/test_drop_off.py` leaves the rest of the app intact.

---

## Decision 7 — Stop search

**Decision:** A "Stop search" button, shown only while a search is running. It cancels the running event and discards the result, nothing is saved to History, and the inputs are unlocked again.

**Alternatives considered:** Streaming responses from Ollama so the model call can really be interrupted.

**Why we chose this:** Responses can take minutes, so users need a way out. Streaming would need larger changes to the model client. The limitation is documented: the model may keep running in the background until it finishes, but its result is ignored. Real cancellation through streaming is a future improvement.

---

## Decision 8 — UI layout

**Decision:** A single page of clearly separated sections: Check an item, Answer, Where to take it, and History (the last five items, collapsed) at the very bottom. "Your answer" was renamed "Answer", the "Use via API" footer link was removed and Settings was kept.

**Alternatives considered:** Five different placements for History were compared. History in the middle pushed the drop-off section out of sight, so it moved to the bottom and became collapsible.

**Why we chose this:** The user's eye follows the natural order: ask, read the answer, see where to take the item. History is secondary.

---

## Decision 9 — Language

**Decision:** The interface and the answers are English only for now. Finnish or Swedish words may be recognised by the model, but this is untested and not supported.

**Why:** The reference data, prompts and evaluation are written in English. A UI language selection is listed under future improvements in the README.
