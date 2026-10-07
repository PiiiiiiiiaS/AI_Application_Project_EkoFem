"""
Gradio section for the optional drop-off point finder.

It appears on the main page, below the "Check an item" / "Answer" / "History"
sections, but only after an item has been checked and only for waste categories
that have a drop-off option. The user is not asked what they want to drop off:
the category comes from the answer they just got. Biowaste and mixed waste go in
the household bins, so for those the section stays hidden.

Architectural rule: this module talks only to the service layer
(src/services/drop_off.py), never to the model client, Ollama or the API.
"""
import gradio as gr

from src.services.drop_off import (
    MATERIAL_CHOICES,
    drop_off_intro,
    lookup_by_location,
    lookup_by_text,
    supports_drop_off,
)

RESULTS_PLACEHOLDER = (
    "_Press **Use my location** to see the nearest points first, "
    "or enter your municipality below._"
)

# Runs in the visitor's browser. Resolves to "lat, lon", or "denied" /
# "unavailable". The browser itself asks for permission, and the coordinates
# are only passed on to the lookup function; nothing is stored.
GPS_JS = """
() => new Promise((resolve) => {
  if (!navigator.geolocation) { resolve("unavailable"); return; }
  // The browser's own timeout only starts after permission is granted, so an
  // ignored permission prompt would otherwise leave the button hanging forever.
  const giveUp = setTimeout(() => resolve("unavailable"), 20000);
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      clearTimeout(giveUp);
      resolve(pos.coords.latitude.toFixed(5) + ", " + pos.coords.longitude.toFixed(5));
    },
    (err) => {
      clearTimeout(giveUp);
      resolve(err && err.code === 1 ? "denied" : "unavailable");
    },
    { timeout: 10000, maximumAge: 600000 }
  );
})
"""


def add_drop_off_panel(category_state: gr.State) -> None:
    """
    Adds the finder as a full-width section. Call it inside the open gr.Blocks() context.

    `category_state` holds the id of the waste category of the item that was just
    checked (or None). The section shows and hides itself when that value changes.
    """
    with gr.Column(visible=False, variant="panel") as section:
        heading = gr.Markdown("### Where to take it")
        with gr.Row(equal_height=False):
            with gr.Column(scale=2):
                gps_btn = gr.Button("Use my location", variant="primary")
                gr.Markdown("_Or search by place:_")
                with gr.Row():
                    municipality = gr.Textbox(label="Municipality (kunta)", placeholder="e.g. Tampere")
                    postal_code = gr.Textbox(label="Postal code (optional)", placeholder="e.g. 33100")
                find_btn = gr.Button("Find by place")
                location_box = gr.Textbox(
                    label="Detected location (nearest points first)",
                    interactive=False,
                    placeholder="Not shared yet",
                )
            with gr.Column(scale=3):
                results = gr.Markdown(RESULTS_PLACEHOLDER)

    def _on_category_change(category_id):
        """Shows the section with the right text for this category, or hides it."""
        if not supports_drop_off(category_id):
            return gr.update(visible=False), gr.update(), RESULTS_PLACEHOLDER
        label = MATERIAL_CHOICES[category_id][0]
        text = f"### Where to take it: {label}\n\n{drop_off_intro(category_id)}"
        return gr.update(visible=True), text, RESULTS_PLACEHOLDER

    # Fires whenever a new search starts (state reset to None) or finishes (new category).
    category_state.change(
        fn=_on_category_change,
        inputs=category_state,
        outputs=[section, heading, results],
    )

    find_btn.click(
        fn=lookup_by_text,
        inputs=[category_state, municipality, postal_code],
        outputs=results,
    )
    gps_btn.click(
        fn=None,
        inputs=None,
        outputs=location_box,
        js=GPS_JS,
    ).then(
        fn=lookup_by_location,
        inputs=[category_state, location_box],
        outputs=results,
    )
