import gradio as gr

from src.services.ai_service import generate_recycling_response, generate_recycling_response_from_image
from src.services.history import get_recent

THEME = gr.themes.Soft(primary_hue="emerald", secondary_hue="slate")


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

    Accessibility note: all inputs use explicit `label=` values, which Gradio
    exposes as proper accessible labels, and every component, including the
    Tabs used below, is natively keyboard-operable. Processing feedback is
    shown immediately on click/submit so the interface never appears silently
    frozen during a slow model response.
    """
    with gr.Blocks(title="WasteBuddy") as demo:
        gr.Markdown(
            """
            # WasteBuddy

            Not sure how to dispose of something? Describe it, or upload a photo,
            and WasteBuddy will tell you which Finnish recycling category it
            belongs to and what it actually gets turned into.
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
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
                output_box = gr.Markdown(
                    "### Your answer\n\n_Your result will appear here._",
                )
                recent_box = gr.Markdown(
                    "### Recently checked\n\n" + _render_recent(),
                )

        def _show_text_loading():
            return "### Your answer\n\n_Checking... this can take a few minutes._"

        def _show_image_loading():
            return "### Your answer\n\n_Checking your photo... this can take a little while._"

        def _answer_text(message: str) -> str:
            return "### Your answer\n\n" + generate_recycling_response(message)

        def _answer_image(image_path):
            """Reads the uploaded photo's bytes, then hands off to the AI service layer."""
            if not image_path:
                return "### Your answer\n\nPlease upload a photo before sending."
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            return "### Your answer\n\n" + generate_recycling_response_from_image(image_bytes)

        def _refresh_recent() -> str:
            return "### Recently checked\n\n" + _render_recent()

        # Connect UI actions exclusively to the service layer functions.
        # Each submission first shows an immediate status message, then
        # replaces it with the real answer once the model responds, then
        # refreshes the recent-items panel — so the interface never looks
        # silently frozen during a slow request, and memory stays in view.
        text_submit_btn.click(
            fn=_show_text_loading,
            outputs=output_box,
        ).then(
            fn=_answer_text,
            inputs=user_input,
            outputs=output_box,
        ).then(
            fn=_refresh_recent,
            outputs=recent_box,
        )
        user_input.submit(
            fn=_show_text_loading,
            outputs=output_box,
        ).then(
            fn=_answer_text,
            inputs=user_input,
            outputs=output_box,
        ).then(
            fn=_refresh_recent,
            outputs=recent_box,
        )
        image_submit_btn.click(
            fn=_show_image_loading,
            outputs=output_box,
        ).then(
            fn=_answer_image,
            inputs=image_input,
            outputs=output_box,
        ).then(
            fn=_refresh_recent,
            outputs=recent_box,
        )
        clear_text_btn.click(
            fn=lambda: "",
            outputs=user_input,
        )

    return demo
