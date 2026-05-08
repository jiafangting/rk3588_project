"""Startup checks for the vision module."""

from pathlib import Path


def run_startup_check(camera_index, model_path, output_dir, check_camera_flag=True):
    print("Running startup check...")
    print(f"- Camera index: {camera_index}")
    print(f"- Model path  : {model_path}")
    print(f"- Output dir  : {output_dir}")

    model_path = Path(model_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    if check_camera_flag:
        import cv2

        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        ok = cap.isOpened()
        cap.release()
        if not ok:
            raise RuntimeError(f"Camera is not available: {camera_index}")

    print("Startup check passed")
    return True
