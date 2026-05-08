"""Small menu for vision test scripts."""

import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent

TESTS = {
    "1": ("Camera open/read test", TEST_DIR / "vision_camera_test.py"),
    "2": ("Save one frame test", TEST_DIR / "vision_save_frame_test.py"),
    "3": ("Vision alarm voice broadcast test", TEST_DIR / "vision_voice_broadcast_test.py"),
    "4": ("Mock vision socket server", TEST_DIR / "mock_vision_socket_server.py"),
}


def print_menu():
    print("========== Vision Test Menu ==========")
    for key, (name, _path) in TESTS.items():
        print(f"{key}. {name}")
    print("q. quit")
    print("======================================")


def main():
    while True:
        print_menu()
        choice = input("Select test > ").strip()
        if choice.lower() == "q":
            return
        if choice not in TESTS:
            print("Unknown selection")
            continue
        _name, path = TESTS[choice]
        subprocess.run([sys.executable, str(path)], check=False)


if __name__ == "__main__":
    main()
