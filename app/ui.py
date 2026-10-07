import gradio as gr

from src.services.ai_service import generate_recycling_response, generate_recycling_response_from_image
from src.services.history import get_recent
from src.services.search_control import CancelToken, CancellableAIService

# Optional feature: nearest drop-off point finder (src/services/drop_off.py).
# To remove it, delete app/drop_off_ui.py, src/services/drop_off.py and
# tests/test_drop_off.py; this file then keeps working unchanged.
try:
    from app.drop_off_ui import add_drop_off_panel
except ModuleNotFoundError as err:
    if err.name != "app.drop_off_ui":
        raise
    add_drop_off_panel = None

THEME = gr.themes.Soft(primary_hue="emerald", secondary_hue="slate")

# Passed to demo.launch(css=...) in app/main.py. Gradio's footer shows a dot before
# "Built with Gradio" but none after "Settings"; this adds one so the footer is balanced.
CSS = """
footer::after {
    content: "·";
    color: rgb(156, 163, 175);
    font-size: 14px;
    margin: 0 4px 0 8px;
}
"""

ANSWER_HEADING = "### Answer\n\n"

INTRO_TEXT = (
    "Not sure how to dispose of something? Describe it, or upload a photo, and WasteBuddy "
    "will tell you which Finnish recycling category it belongs to and what it actually gets "
    "turned into."
)
# Only mentioned when the optional drop-off finder (app/drop_off_ui.py) is installed.
INTRO_DROP_OFF_TEXT = (
    " If it cannot be recycled at home, WasteBuddy also helps you find the nearest drop-off "
    "point or collection point, using your location or your municipality."
)


def _render_recent() -> str:
    """Reads the persisted history through the service layer and formats it for display."""
    entries = get_recent(limit=5)
    if not entries:
        return "_Nothing checked yet. Your last few items will show up here._"

    lines = []
    for entry in entries:
        recycled = f" — {entry['recycled_into']}" if entry.get("recycled_into") else ""
        lines.append(f"- **{entry['item_name']}** → {entry['disposal_category']}{recycled}")
    return "\n".join(lines)


def build_ui() -> gr.Blocks:
    """
    Constructs the Gradio web interface for WasteBuddy.

    Architectural Principle: The UI communicates strictly with the AI service
    layer (generate_recycling_response / generate_recycling_response_from_image)
    and the history module's read-only get_recent() helper — never directly
    with Ollama, the model client, or the underlying data files.

    Page layout, top to bottom: "Check an item" (inputs) next to the "Answer", then
    the optional drop-off finder, which appears after an answer for the item's
    category, and finally "History", a collapsed section opened with its arrow.
    While a search is running, a "Stop search" button appears in the Answer section.

    Accessibility note: all inputs use explicit `label=` values, which Gradio
    exposes as proper accessible labels, and every component, including the
    Tabs used below, is natively keyboard-operable. Processing feedback is
    shown immediately on click/submit so the interface never appears silently
    frozen during a slow model response.
    """
    with gr.Blocks(title="WasteBuddy") as demo:
        intro = INTRO_TEXT + (INTRO_DROP_OFF_TEXT if add_drop_off_panel is not None else "")
        gr.Markdown(f"# WasteBuddy\n\n{intro}")

        # Holds the CancelToken of the search that is currently running.
        search_state = gr.State(None)
        # Holds the waste category id (e.g. "hazardous_waste") of the item that was just
        # checked, or None. The optional drop-off section reads it; nothing else needs it.
        category_state = gr.State(None)

        with gr.Row(equal_height=False):
            with gr.Column(scale=3, variant="panel"):
                gr.Markdown("### Check an item")
                with gr.Tabs():
                    with gr.Tab("Describe it"):
                        user_input = gr.Textbox(
                            lines=2,
                            placeholder="e.g. 'pizza box', 'glass jar', 'old t-shirt'...",
                            label="Describe the item",
                        )
                        with gr.Row():
                            text_submit_btn = gr.Button("Check item", variant="primary", scale=3)
                            clear_text_btn = gr.Button("Clear", scale=1)

                    with gr.Tab("Upload a photo"):
                        image_input = gr.Image(
                            type="filepath",
                            label="Photo of the item",
                        )
                        image_submit_btn = gr.Button("Check photo", variant="primary")

                gr.Markdown(
                    "_Responses can take a few minutes on modest hardware. WasteBuddy is scoped "
                    "to Finland's national household waste rules and to waste-sorting questions._"
                )

            with gr.Column(scale=2):
                with gr.Column(variant="panel"):
                    output_box = gr.Markdown(
                        ANSWER_HEADING + "_The answer will appear here._",
                    )
                    # Only visible while a search is running.
                    stop_btn = gr.Button("Stop search", variant="stop", visible=False)

        # Optional: drop-off point finder, shown on this same page (see the import at the top).
        if add_drop_off_panel is not None:
            add_drop_off_panel(category_state)

        # History comes last, below the answer and the drop-off finder. It is collapsed
        # by default; the user opens it with the arrow.
        with gr.Accordion("History (last 5 checked items)", open=False):
            recent_box = gr.Markdown(_render_recent())

        # Controls that are locked while a search runs, so a second search cannot
        # start on top of the first one.
        locked_controls = [user_input, text_submit_btn, image_submit_btn]

        def _unlocked():
            return [gr.update(interactive=True) for _ in locked_controls]

        def _start(message: str):
            """Shows the status message, reveals the Stop button, locks the inputs."""
            return [
                ANSWER_HEADING + message,
                gr.update(visible=True),
                CancelToken(),
                None,  # category_state: hides the drop-off section while a new search runs
                *[gr.update(interactive=False) for _ in locked_controls],
            ]

        def _start_text():
            return _start("_Checking... this can take a few minutes._")

        def _start_image():
            return _start("_Checking your photo... this can take a little while._")

        def _answer_text(message: str, token: CancelToken):
            """Returns the answer text and the waste category id (None if there was no real answer)."""
            service = CancellableAIService(token)
            answer = generate_recycling_response(message, service=service)
            return ANSWER_HEADING + answer, service.category_id

        def _answer_image(image_path, token: CancelToken):
            """Reads the uploaded photo's bytes, then hands off to the AI service layer."""
            if not image_path:
                return ANSWER_HEADING + "Please upload a photo before sending.", None
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            service = CancellableAIService(token)
            answer = generate_recycling_response_from_image(image_bytes, service=service)
            return ANSWER_HEADING + answer, service.category_id

        def _finish():
            """Search done: refresh History, hide the Stop button, unlock the inputs."""
            return [_render_recent(), gr.update(visible=False), *_unlocked()]

        def _stop(token: CancelToken):
            """Search stopped by the user: the answer is discarded and nothing is recorded."""
            if token is not None:
                token.cancel()
            return [
                ANSWER_HEADING + "_Search stopped. Nothing was saved to History._",
                gr.update(visible=False),
                None,
                *_unlocked(),
            ]

        start_outputs = [output_box, stop_btn, search_state, category_state, *locked_controls]
        finish_outputs = [recent_box, stop_btn, *locked_controls]

        # Connect UI actions exclusively to the service layer functions.
        # Each submission first shows an immediate status message, then
        # replaces it with the real answer once the model responds, then
        # refreshes the History section — so the interface never looks
        # silently frozen during a slow request, and memory stays in view.
        # `running` collects the model-calling steps so Stop can cancel them.
        running = []
        for trigger in (text_submit_btn.click, user_input.submit):
            step = trigger(
                fn=_start_text,
                outputs=start_outputs,
            ).then(
                fn=_answer_text,
                inputs=[user_input, search_state],
                outputs=[output_box, category_state],
            )
            step.then(fn=_finish, outputs=finish_outputs)
            running.append(step)

        step = image_submit_btn.click(
            fn=_start_image,
            outputs=start_outputs,
        ).then(
            fn=_answer_image,
            inputs=[image_input, search_state],
            outputs=[output_box, category_state],
        )
        step.then(fn=_finish, outputs=finish_outputs)
        running.append(step)

        stop_btn.click(
            fn=_stop,
            inputs=search_state,
            outputs=[output_box, stop_btn, category_state, *locked_controls],
            cancels=running,
        )

        clear_text_btn.click(
            fn=lambda: "",
            outputs=user_input,
        )

    return demo
