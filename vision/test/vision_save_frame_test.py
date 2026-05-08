"""Capture one camera frame and save it to disk."""

from datetime import datetime
from pathlib import Path

import cv2


def open_camera(camera_index=0):
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Camera open failed, index={camera_index}")
    return cap


def read_one_frame(cap):
    ret, frame = cap.read()
    if not ret or frame is None:
        raise RuntimeError("Failed to read camera frame")
    return frame


def save_frame(frame, output_dir=None):
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"frame_{timestamp}.jpg"

    ok = cv2.imwrite(str(path), frame)
    if not ok:
        raise RuntimeError(f"Image save failed: {path}")
    return path


def main():
    cap = open_camera(0)
    try:
        frame = read_one_frame(cap)
        path = save_frame(frame)
        print(f"Saved frame: {path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Camera released")


if __name__ == "__main__":
    main()
