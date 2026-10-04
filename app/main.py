from app.ui import THEME, build_ui

def main() -> None:
    """Entry point script for launching the application."""
    demo = build_ui()
    demo.launch(theme=THEME)

if __name__ == "__main__":
    main()
