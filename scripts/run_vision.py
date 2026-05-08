"""Root entry point for the vision inspection module."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VISION_DIR = PROJECT_ROOT / "vision"
APP_DIR = VISION_DIR / "app"

for path in (APP_DIR, VISION_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

try:
    from vision_main import main as vision_main
except Exception as exc:
    raise RuntimeError(
        "Cannot import vision main program. Check vision/app and Python dependencies."
    ) from exc


def print_startup_message():
    print("=" * 60)
    print("Vision inspection program starting")
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Vision dir   : {VISION_DIR}")
    print(f"App dir      : {APP_DIR}")
    print("=" * 60)


def main():
    print_startup_message()
    vision_main()


if __name__ == "__main__":
    main()
