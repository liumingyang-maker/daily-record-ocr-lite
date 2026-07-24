"""兼容入口：转发到轻量应用。"""

from lite_app.main import app, run

__all__ = ["app", "run"]

if __name__ == "__main__":
    run()
