"""Minimal camera open/read test."""

import cv2


def main():
    camera_index = 0
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        raise RuntimeError(f"Camera open failed, index={camera_index}")

    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to read one frame")
        h, w = frame.shape[:2]
        print(f"Camera OK, frame size: {w}x{h}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
