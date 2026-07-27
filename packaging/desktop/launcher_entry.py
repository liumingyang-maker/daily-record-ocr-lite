"""PyInstaller entry point that preserves the lite_app package context."""

from lite_app.desktop_launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
