from app.ui import CSS, THEME, build_ui

def main() -> None:
    """Entry point script for launching the application."""
    demo = build_ui()
    demo.launch(theme=THEME, css=CSS, footer_links=["settings", "gradio"])

if __name__ == "__main__":
    main()
