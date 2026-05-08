"""Unified configuration for the Python vision module."""

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
VISION_DIR = APP_DIR.parent
PROJECT_ROOT = VISION_DIR.parent

MODEL_PATH = PROJECT_ROOT / "models" / "yolo11n" / "yolo11n.pt"
OUTPUT_DIR = APP_DIR / "output"
ALARM_CLIP_DIR = OUTPUT_DIR / "clips"
JSONL_PATH = OUTPUT_DIR / "records.jsonl"
CSV_PATH = OUTPUT_DIR / "records.csv"

CAMERA_INDEX = 0
STABLE_FRAMES_REQUIRED = 5
MIN_PERSON_SCORE = 0.55
YOLO_CONF = 0.30

PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 480
TTS_RATE = 180
TTS_VOLUME = 1.0

NO_PERSON_FRAMES_REQUIRED = 5
ALARM_FRAMES_REQUIRED = 5
ALARM_COOLDOWN_FRAMES = 30
ALARM_COOLDOWN_SECONDS = 5
HAZARD_ZONE_MIN_OVERLAP_RATIO = 0.12

ENABLE_VIDEO_CLIP_SAVE = False
ALARM_CLIP_SECONDS = 5
ALARM_CLIP_FPS = 15

# 设备正式运行策略：
# - 正常状态不播报，保持安静；
# - 异常/报警才播报；
# - 避免同一种异常反复刷屏式播报。
SPEAK_NORMAL_STATUS = False
SPEAK_ABNORMAL_STATUS = False
ABNORMAL_COOLDOWN_SECONDS = 8

HAZARD_ZONE = {
    "name": "right_third_zone",
    "top_left": (420, 80),
    "bottom_right": (630, 420),
}


def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ALARM_CLIP_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def validate_config(check_camera=False, camera_index=CAMERA_INDEX):
    ensure_output_dir()

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

    test_file = OUTPUT_DIR / "_config_write_test.tmp"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(f"Output directory is not writable: {OUTPUT_DIR}") from exc

    if check_camera:
        import cv2

        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        ok = cap.isOpened()
        cap.release()
        if not ok:
            raise RuntimeError(f"Camera is not available: {camera_index}")

    return True
