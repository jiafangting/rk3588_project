"""Python 视觉模块统一配置。

这个文件的作用是把所有“可调参数”集中放在一起，避免散落在各处。

你可以把它理解成视觉模块的“参数总表”：
- 路径参数：模型、输出目录、图片目录、记录目录
- 推理参数：摄像头编号、置信度阈值、人员分数阈值
- 展示参数：预览图尺寸、语音参数
- 告警参数：稳定帧数、禁区、冷却时间、视频保存开关

为什么要集中管理：
1. 后面你学习时，改参数只需要看一个地方；
2. UI、视觉、语音都可以复用同一份参数；
3. 方便调试和部署。
"""

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
VISION_DIR = APP_DIR.parent
PROJECT_ROOT = VISION_DIR.parent

MODEL_PATH = PROJECT_ROOT / "models" / "yolo11n" / "yolo11n.pt"
OUTPUT_DIR = APP_DIR / "output"
PHOTOS_DIR = OUTPUT_DIR / "photos"
RECORDS_DIR = OUTPUT_DIR / "recodes"
ALARM_CLIP_DIR = OUTPUT_DIR / "clips"
JSONL_PATH = RECORDS_DIR / "records.jsonl"
CSV_PATH = RECORDS_DIR / "records.csv"
LIVE_FRAME_PATH = PHOTOS_DIR / "live_frame.jpg"
LIVE_FRAME_INTERVAL_SECONDS = 0.10

# -----------------------------
# 关键运行参数
# -----------------------------
# 下面这些值都是“默认运行参数”。
# 如果你后续想调试识别效果，先从这些参数入手。
CAMERA_INDEX = 0
STABLE_FRAMES_REQUIRED = 5
MIN_PERSON_SCORE = 0.55
YOLO_CONF = 0.30

# 画面显示参数：
# - PREVIEW_WIDTH / PREVIEW_HEIGHT：视觉模块送入 YOLO 的预览图尺寸
# - TTS_RATE / TTS_VOLUME：语音播报的速度和音量
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 480
TTS_RATE = 180
TTS_VOLUME = 1.0

# 告警判断参数：
# - NO_PERSON_FRAMES_REQUIRED：连续多少帧没检测到人，才认为“无人状态”稳定
# - ALARM_FRAMES_REQUIRED：连续多少帧命中报警，才真正触发报警
# - ALARM_COOLDOWN_FRAMES：触发后至少隔多少帧再允许下一次报警
# - ALARM_COOLDOWN_SECONDS：触发后至少隔多少秒再允许下一次报警
# - HAZARD_ZONE_MIN_OVERLAP_RATIO：人体框和禁区重叠多少才算进入禁区
NO_PERSON_FRAMES_REQUIRED = 5
ALARM_FRAMES_REQUIRED = 5
ALARM_COOLDOWN_FRAMES = 30
ALARM_COOLDOWN_SECONDS = 5
HAZARD_ZONE_MIN_OVERLAP_RATIO = 0.12

# 视频与录像保存参数：
# - ENABLE_VIDEO_CLIP_SAVE：是否保存报警短视频
# - ALARM_CLIP_SECONDS：短视频时长
# - ALARM_CLIP_FPS：短视频帧率
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
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    ALARM_CLIP_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def validate_config(check_camera=False, camera_index=CAMERA_INDEX):
    """检查配置是否可用。

    参数：
    - `check_camera`：是否真的打开摄像头做检测
    - `camera_index`：摄像头编号，默认使用 `CAMERA_INDEX`

    返回值：
    - `True`：所有检查通过

    检查内容：
    1. 输出目录是否存在且可写；
    2. 模型文件是否存在；
    3. 如果要求检查摄像头，就尝试打开摄像头。
    """
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
