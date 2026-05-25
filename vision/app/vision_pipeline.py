from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
import time

import cv2

from config import (
    ALARM_CLIP_DIR,
    ALARM_CLIP_FPS,
    ALARM_CLIP_SECONDS,
    ALARM_COOLDOWN_FRAMES,
    ALARM_COOLDOWN_SECONDS,
    ALARM_FRAMES_REQUIRED,
    CAMERA_INDEX,
    CSV_PATH,
    ENABLE_VIDEO_CLIP_SAVE,
    HAZARD_ZONE,
    HAZARD_ZONE_MIN_OVERLAP_RATIO,
    JSONL_PATH,
    LIVE_FRAME_INTERVAL_SECONDS,
    LIVE_FRAME_PATH,
    MIN_PERSON_SCORE,
    MODEL_PATH,
    NO_PERSON_FRAMES_REQUIRED,
    OUTPUT_DIR,
    SPEAK_ABNORMAL_STATUS,
    SPEAK_NORMAL_STATUS,
    ABNORMAL_COOLDOWN_SECONDS,
    STABLE_FRAMES_REQUIRED,
    YOLO_CONF,
    ensure_output_dir,
    validate_config,
)
from vision_bridge import VisionBridge
from vision_socket import VisionSocketServer
from vision_core import (
    build_decision,
    build_speech_text,
    create_alarm_window,
    create_stability_window,
    draw_result,
    draw_timestamp,
    extract_person_boxes,
    init_tts,
    load_model,
    open_camera,
    parse_result,
    preprocess_frame,
    read_one_frame,
    run_inference,
    speak_text,
    tts_worker,
)


# =========================
# vision_pipeline.py
# 视觉主流程说明
#
# 这个文件是视觉模块真正的“运行主循环”。
# 它把 vision_core、vision_bridge、vision_socket 这些工具串起来，形成一条完整的数据流：
#
# 摄像头取帧 -> YOLO 推理 -> 视觉决策 -> 报警联动 -> 画面显示 -> Socket 发布 -> 语音播报 -> 日志保存
#
# 为什么要单独分出这个文件：
# - vision_core.py 负责“工具函数”；
# - vision_bridge.py 负责“记录和联动”；
# - vision_socket.py 负责“对外通信”；
# - vision_pipeline.py 负责“把它们真正跑起来”。
#
# 新手阅读建议：
# 1. 先看 main()，理解启动流程；
# 2. 再看 process_one_frame()，理解单帧是怎么处理的；
# 3. 再看 handle_socket_command()，理解外部怎么触发巡检；
# 4. 最后看 while True 主循环，理解每一帧怎么轮转。
# =========================


def initialize_runtime():
    """初始化视觉运行环境。

    作用：
    - 创建输出目录；
    - 检查模型和配置是否可用；
    - 在真正跑推理前，先把基础环境准备好。

    返回值：
    - 无；成功就继续，失败会在 `validate_config()` 里抛异常。
    """
    ensure_output_dir()
    validate_config(check_camera=False)
    print("运行前检查完成：模型和输出目录可用")


def format_label_text(text):
    """把下划线标签转成更友好的显示文本。

    例如：
    - `right_third_zone` -> `right third zone`

    作用：
    - 让画面上的英文标签更容易读。
    """
    if not text:
        return text
    return text.replace("_", " ")


def draw_hazard_zone(image, hazard_zone):
    """在画面上绘制禁区矩形。

    参数：
    - `image`：要绘制的图像
    - `hazard_zone`：禁区配置，包含坐标和名称

    返回值：
    - 绘制后的图像

    原理：
    - 用 OpenCV 画红色矩形框；
    - 在框上方写禁区名称；
    - 这样用户能直观看到“危险区域”在哪里。
    """
    top_left = hazard_zone["top_left"]
    bottom_right = hazard_zone["bottom_right"]
    cv2.rectangle(image, top_left, bottom_right, (0, 0, 255), 3)
    cv2.putText(
        image,
        f'Zone: {format_label_text(hazard_zone["name"])}',
        (top_left[0], max(24, top_left[1] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def count_intrusions(person_centers, hazard_zone):
    """统计点位是否进入禁区。

    参数：
    - `person_centers`：人员中心点坐标列表
    - `hazard_zone`：禁区坐标配置

    返回值：
    - `hit_count`：命中禁区的人数
    - `hit_count > 0`：是否至少有 1 人进入禁区

    原理：
    - 先把人框中心点拿出来；
    - 再判断中心点是否落在禁区矩形内；
    - 这里是一个简单、直观的几何判定。
    """
    top_left = hazard_zone["top_left"]
    bottom_right = hazard_zone["bottom_right"]
    hit_count = 0
    for center in person_centers:
        if point_in_rect(center, top_left, bottom_right):
            hit_count += 1
    return hit_count, hit_count > 0


def box_overlap_ratio(box, top_left, bottom_right):
    """计算目标框与禁区的重叠比例。

    作用：
    - 当人的脚点没完全落入禁区，但身体框和禁区有较大重叠时，也可视为进入禁区。

    返回值：
    - 重叠面积 / 目标框面积
    """
    x1, y1, x2, y2 = box
    zx1, zy1 = top_left
    zx2, zy2 = bottom_right

    inter_w = max(0.0, min(x2, zx2) - max(x1, zx1))
    inter_h = max(0.0, min(y2, zy2) - max(y1, zy1))
    inter_area = inter_w * inter_h
    box_area = max(1.0, (x2 - x1) * (y2 - y1))
    return inter_area / box_area


def point_in_zone(point, top_left, bottom_right):
    """判断一个点是否在矩形区域内。

    参数：
    - `point`：点坐标 `(x, y)`
    - `top_left`：矩形左上角
    - `bottom_right`：矩形右下角

    返回值：
    - `True` / `False`
    """
    x, y = point
    x1, y1 = top_left
    x2, y2 = bottom_right
    return x1 <= x <= x2 and y1 <= y <= y2


def count_intrusions(person_boxes, hazard_zone):
    """统计人框是否进入禁区。

    参数：
    - `person_boxes`：人框列表，每个元素是 `(x1, y1, x2, y2)`
    - `hazard_zone`：禁区配置

    返回值：
    - `hit_count`：命中禁区的人数
    - `hit_count > 0`：是否进入报警状态的依据之一

    原理：
    - 取人体框底部中点作为“脚点”；
    - 若脚点在禁区内，认为进入禁区；
    - 或者人体框和禁区重叠比例超过阈值，也认为进入禁区；
    - 这样比只看一个点更稳。
    """
    top_left = hazard_zone["top_left"]
    bottom_right = hazard_zone["bottom_right"]
    hit_count = 0

    for box in person_boxes:
        x1, y1, x2, y2 = box
        foot_point = ((x1 + x2) / 2, y2)
        overlap_ratio = box_overlap_ratio(box, top_left, bottom_right)
        if point_in_zone(foot_point, top_left, bottom_right) or overlap_ratio >= HAZARD_ZONE_MIN_OVERLAP_RATIO:
            hit_count += 1

    return hit_count, hit_count > 0


def save_live_frame(image, output_path=LIVE_FRAME_PATH):
    """保存最新处理后的画面，供 UI 预览。

    参数：
    - `image`：OpenCV 图像
    - `output_path`：保存路径，默认 `LIVE_FRAME_PATH`

    返回值：
    - 成功时返回图片路径字符串
    - 失败时返回空字符串

    原理：
    - 先写临时文件 `.tmp.jpg`；
    - 写成功后再原子替换为正式文件；
    - 这样 UI 读取时不容易读到半张图。
    """
    if image is None:
        return ""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp.jpg")
    if not cv2.imwrite(str(temp_path), image):
        return ""
    temp_path.replace(output_path)
    return str(output_path)


def build_alarm_fields(decision):
    """统一视觉报警字段，避免 C 主控从辅助字段反推报警含义。"""
    if decision.status != "ALARM":
        return "", ""

    if decision.zone_hit:
        return "zone_intrusion", "人员进入右侧禁区"

    if decision.alarm_label == "smoke":
        return "smoke", "检测到烟雾"

    if decision.alarm_label in ("fire", "flame"):
        return "fire", "检测到明火"

    if decision.alarm_label:
        return str(decision.alarm_label), decision.reason or "视觉检测到报警目标"

    if decision.alarm_name:
        return str(decision.alarm_name), decision.reason or str(decision.alarm_name)

    return "vision_alarm", decision.reason or "视觉检测到报警"


def build_socket_status(decision, current_person_count, live_frame_path=""):
    """构造发给外部模块的状态包。

    参数：
    - `decision`：视觉决策结果对象
    - `current_person_count`：当前帧人数
    - `live_frame_path`：当前预览图路径

    返回值：
    - 一个字典，作为 socket 响应体

    为什么要单独封装：
    - UI、语音、C 主控都要读这个数据；
    - 把格式统一后，外部模块只需要解析一个结构；
    - 不需要去理解完整图像或内部缓存。
    """
    alarm_type, alarm_reason = build_alarm_fields(decision)
    return {
        "status": decision.status,
        "person_count": current_person_count,
        "reason": decision.reason,
        "zone_name": decision.zone_name or "",
        "intruded_people": decision.intruded_people,
        "alarm_frame_count": decision.alarm_frame_count,
        "zone_hit": bool(decision.zone_hit),
        "alarm_type": alarm_type,
        "alarm_reason": alarm_reason,
        "live_frame_path": live_frame_path,
        "result_path": live_frame_path,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_manual_snapshot_response(decision, current_person_count, raw_path, result_path, speech_text, record, live_frame_path=""):
    """构造“手动巡检保存”后的 socket 响应。

    这个响应会返回给语音或 UI 客户端，告诉它：
    - 已经保存成功；
    - 原图和结果图放在哪里；
    - 这次记录的状态和时间是什么。
    """
    response = build_socket_status(decision, current_person_count, live_frame_path)
    response.update(
        {
            "ack": True,
            "cmd": "trigger_inspection",
            "message": "Inspection snapshot saved",
            "raw_path": str(raw_path),
            "result_path": str(result_path),
            "snapshot_path": str(result_path),
            "speech_text": speech_text,
            "record_status": record.get("status", ""),
            "record_timestamp": record.get("timestamp", ""),
        }
    )
    return response


def build_socket_error_response(cmd, message):
    """构造一个“长得像状态包”的错误响应。

    作用：
    - 让语音客户端不用一直等超时；
    - 即使出错，也能尽快拿到结构一致的返回值。
    """
    return {
        "ack": False,
        "cmd": cmd,
        "status": "UNKNOWN",
        "person_count": 0,
        "reason": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_status_style(status):
    """根据状态返回显示颜色。

    返回值：
    - `(bg_color, text_color)`

    颜色含义：
    - `NORMAL`：绿色，表示正常；
    - `ABNORMAL`：橙色，表示异常；
    - `ALARM`：红色，表示报警。
    """
    if status == "ALARM":
        return (0, 0, 255), (255, 255, 255)
    if status == "ABNORMAL":
        return (0, 165, 255), (255, 255, 255)
    if status == "NORMAL":
        return (0, 180, 0), (255, 255, 255)
    return (80, 80, 80), (255, 255, 255)


def draw_status_panel(image, decision, current_person_count, no_person_count):
    """在画面左上角绘制状态面板。

    参数：
    - `image`：原图
    - `decision`：视觉决策结果
    - `current_person_count`：当前帧人数
    - `no_person_count`：连续无人帧数

    返回值：
    - 绘制后的图像

    作用：
    - 把最重要的状态信息放在画面左上角，方便演示和排查。
    """
    bg_color, text_color = get_status_style(decision.status)
    x1, y1, x2, y2 = 10, 40, 360, 190
    overlay = image.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), bg_color, -1)
    cv2.addWeighted(overlay, 0.38, image, 0.62, 0, image)
    cv2.rectangle(image, (x1, y1), (x2, y2), bg_color, 2)

    cv2.putText(image, f"STATUS: {decision.status}", (20, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.75, text_color, 2, cv2.LINE_AA)
    cv2.putText(image, f"PERSONS: {current_person_count}", (20, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.65, text_color, 2, cv2.LINE_AA)
    cv2.putText(image, f"NO PERSON: {no_person_count}/{NO_PERSON_FRAMES_REQUIRED}", (20, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.58, text_color, 2, cv2.LINE_AA)
    cv2.putText(image, f"STABLE: {'YES' if decision.stable else 'NO'}", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.58, text_color, 2, cv2.LINE_AA)
    cv2.putText(image, f"ALARM VOTE: {decision.alarm_frame_count}/{ALARM_FRAMES_REQUIRED}", (20, 184), cv2.FONT_HERSHEY_SIMPLEX, 0.46, text_color, 1, cv2.LINE_AA)
    return image


def draw_alarm_banner(image, decision):
    """在画面顶部绘制醒目的报警横幅。

    作用：
    - 一旦进入 ALARM，顶部横幅立刻变红；
    - 让用户第一眼就知道当前是否处于报警。
    """
    if decision.status != "ALARM":
        return image
    h, w = image.shape[:2]
    cv2.rectangle(image, (0, 0), (w, 30), (0, 0, 255), -1)
    cv2.putText(image, "ALARM ACTIVE", (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def draw_latest_preview(image, preview_path):
    """在右下角显示最近一次报警截图提示。

    参数：
    - `image`：原图
    - `preview_path`：最近一次报警截图路径

    作用：
    - 演示时告诉你“最近一次报警图已经保存”；
    - 让 UI 和视觉画面之间有更强的联动感。
    """
    if not preview_path:
        return image
    h, w = image.shape[:2]
    x1, y1 = max(10, w - 320), max(10, h - 70)
    x2, y2 = w - 10, h - 10
    overlay = image.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)
    cv2.rectangle(image, (x1, y1), (x2, y2), (200, 200, 200), 1)
    cv2.putText(image, "Latest alarm screenshot saved", (x1 + 10, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(image, Path(preview_path).name[:30], (x1 + 10, y1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
    return image


def process_one_frame(
    model,
    frame,
    bridge,
    stable_person_history,
    stable_frames_required,
    stable_status,
    stable_status_count,
    last_spoken_status,
    alarm_history,
    cooldown_counter,
    last_alarm_time,
    alarm_latched,
    alarm_clear_count,
):
    """处理单帧图像并生成完整的视觉结果。

    这是视觉主流程里的核心函数之一。

    输入：
    - `model`：YOLO 模型对象
    - `frame`：摄像头原始帧
    - `bridge`：视觉联动桥，用于记录和查询
    - `stable_person_history`：稳定帧人数窗口
    - `stable_frames_required`：稳定帧要求
    - `stable_status` / `stable_status_count`：普通状态稳定计数
    - `last_spoken_status`：最近一次播报状态
    - `alarm_history`：报警投票窗口
    - `cooldown_counter`：报警冷却帧计数
    - `last_alarm_time`：最近一次报警时间
    - `alarm_latched`：报警锁定状态
    - `alarm_clear_count`：报警解除计数

    输出：
    - 一个包含画面、决策、播报、计数器更新结果的元组

    核心流程：
    1. 预处理图像；
    2. 运行 YOLO 推理；
    3. 解析结果；
    4. 统计人员数量；
    5. 计算稳定状态；
    6. 判断禁区侵入；
    7. 决定是否报警；
    8. 画结果图；
    9. 决定是否播报。
    这里把状态逻辑收口成一个简单状态机：
    1. 当前帧有报警信号就锁定 ALARM；
    2. 连续几帧都没有报警信号才解除锁定；
    3. 只有在没有报警锁定时，才做普通人数状态播报。
    """
    preview = preprocess_frame(frame)
    result = run_inference(model, preview)
    summary, labels, scores = parse_result(result)
    current_person_count = sum(1 for label, score in zip(labels, scores) if label == "person" and score >= MIN_PERSON_SCORE)

    decision = build_decision(summary, labels, scores, stable_person_history, stable_frames_required)

    person_boxes = extract_person_boxes(result)
    intruded_people, zone_hit = count_intrusions(person_boxes, HAZARD_ZONE)
    decision.intruded_people = intruded_people
    decision.zone_hit = zone_hit
    decision.zone_name = HAZARD_ZONE["name"]

    alarm_label = decision.alarm_label
    alarm_name = decision.alarm_name
    alarm_score = decision.alarm_score
    current_alarm_signal = zone_hit or decision.status == "ALARM"

    alarm_history.append(1 if current_alarm_signal else 0)
    alarm_frame_count = sum(alarm_history)
    decision.alarm_frame_count = alarm_frame_count
    alarm_required_votes = ALARM_FRAMES_REQUIRED // 2 + 1
    voted_alarm_signal = len(alarm_history) >= ALARM_FRAMES_REQUIRED and alarm_frame_count >= alarm_required_votes

    if voted_alarm_signal:
        alarm_latched = True
        alarm_clear_count = 0
    else:
        alarm_clear_count += 1
        if alarm_clear_count >= ALARM_FRAMES_REQUIRED:
            alarm_latched = False

    if alarm_latched:
        decision.status = "ALARM"
        if zone_hit:
            decision.zone_hit = True
            decision.zone_name = HAZARD_ZONE["name"]
            decision.reason = f"Intrusion into hazard zone: {format_label_text(HAZARD_ZONE['name'])}"
        elif decision.alarm_label:
            decision.zone_hit = False
            decision.zone_name = ""
            decision.reason = decision.reason or "Vision alarm target detected"
        else:
            decision.zone_hit = False
            decision.zone_name = ""
            decision.reason = f"视觉报警连续 {ALARM_FRAMES_REQUIRED} 帧投票确认"
        decision.alarm_label = alarm_label
        decision.alarm_name = alarm_name
        decision.alarm_score = alarm_score
    else:
        if decision.stable and decision.status != "ALARM":
            if decision.status == stable_status:
                stable_status_count += 1
            else:
                stable_status = decision.status
                stable_status_count = 1

    if cooldown_counter > 0:
        cooldown_counter -= 1

    now_time = time.time()
    enough_seconds = (now_time - last_alarm_time) >= ALARM_COOLDOWN_SECONDS if last_alarm_time else True
    alarm_triggered = False
    if alarm_latched and cooldown_counter == 0 and enough_seconds:
        alarm_triggered = True
        cooldown_counter = ALARM_COOLDOWN_FRAMES
        last_alarm_time = now_time

    # 画结果图：基础检测框 + 状态面板 + 报警横幅 + 时间戳 + 禁区框。
    result_image = draw_result(
        result,
        decision.status,
        format_label_text(decision.alarm_name),
        format_label_text(decision.zone_name) if decision.zone_hit else None,
    )
    result_image = draw_status_panel(result_image, decision, current_person_count, no_person_count=bridge.no_person_counter)
    result_image = draw_alarm_banner(result_image, decision)
    result_image = draw_timestamp(result_image, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    result_image = draw_hazard_zone(result_image, HAZARD_ZONE)

    latest_preview_path = bridge.get_latest_alarm_preview_path()
    if latest_preview_path:
        result_image = draw_latest_preview(result_image, latest_preview_path)

    should_speak = False
    speech_text = None

    # 普通状态播报：只有在没有报警锁定时才允许。
    if decision.stable and decision.status != "ALARM" and not alarm_latched:
        if decision.status == stable_status:
            stable_status_count += 1
        else:
            stable_status = decision.status
            stable_status_count = 1

        if stable_status_count >= stable_frames_required and stable_status != last_spoken_status:
            if decision.status == "NORMAL" and not SPEAK_NORMAL_STATUS:
                pass
            elif decision.status == "ABNORMAL" and not SPEAK_ABNORMAL_STATUS:
                pass
            else:
                should_speak = True
                speech_text = build_speech_text(decision.status, decision.reason)
                last_spoken_status = decision.status

    if alarm_triggered:
        should_speak = True
        _alarm_type, alarm_reason = build_alarm_fields(decision)
        speech_text = f"当前状态报警。{alarm_reason}。"
        last_spoken_status = "ALARM"

    return (
        result_image,
        preview,
        decision,
        stable_status,
        stable_status_count,
        last_spoken_status,
        should_speak,
        speech_text,
        cooldown_counter,
        last_alarm_time,
        alarm_triggered,
        alarm_latched,
        alarm_clear_count,
        current_person_count,
    )


def main():
    """视觉模块主入口。

    入口职责：
    - 检查环境；
    - 加载模型；
    - 打开摄像头；
    - 启动 TTS 线程；
    - 启动 socket 服务；
    - 进入逐帧处理主循环。

    这是用户真正运行视觉程序时最先进入的函数。
    """
    initialize_runtime()
    print("启动视觉巡检主流程")

    camera_index = CAMERA_INDEX
    stable_frames_required = STABLE_FRAMES_REQUIRED
    local_model_path = MODEL_PATH
    output_dir = OUTPUT_DIR
    jsonl_path = JSONL_PATH
    csv_path = CSV_PATH

    print("正在打印运行参数...")
    print(f"- 摄像头编号：{camera_index}")
    print(f"- 稳定帧数：{stable_frames_required}")
    print(f"- 人数最低置信度：{MIN_PERSON_SCORE}")
    print(f"- 报警投票窗口：{ALARM_FRAMES_REQUIRED} 帧，至少 {ALARM_FRAMES_REQUIRED // 2 + 1} 票")
    print(f"- YOLO 置信度阈值：{YOLO_CONF}")
    print(f"- 模型路径：{local_model_path}")
    print(f"- 输出目录：{output_dir}")
    print(f"- 无人状态连续帧确认数：{NO_PERSON_FRAMES_REQUIRED}")
    print(f"- 是否保存报警短视频：{ENABLE_VIDEO_CLIP_SAVE}")

    model = load_model(str(local_model_path))
    speech_queue = init_tts()
    tts_thread = threading.Thread(target=tts_worker, args=(speech_queue,), daemon=True)
    tts_thread.start()
    cap = open_camera(camera_index)
    print(f"摄像头打开成功，设备号：{camera_index}")
    print(f"模型准备完成：{local_model_path}")
    print("按 q 退出，按 s 保存当前原图、结果图和播报记录")

    stable_person_history = create_stability_window(stable_frames_required)
    stable_status = None
    stable_status_count = 0
    last_spoken_status = None
    alarm_history = create_alarm_window(ALARM_FRAMES_REQUIRED)
    cooldown_counter = 0
    last_alarm_time = 0
    alarm_latched = False
    alarm_clear_count = 0
    last_display_status = None
    last_live_frame_write = 0.0
    live_frame_path = ""

    # 视觉联动桥：负责保存记录、报警摘要和手动巡检。
    bridge = VisionBridge(output_dir=output_dir)
    bridge.no_person_counter = 0

    # frame_context 用来保存“当前这一帧”的快照。
    # 原因：外部发来 trigger_inspection 时，可能正好在主循环处理过程中，
    # 所以要用锁保护，避免读到一半的临时数据。
    frame_context_lock = threading.Lock()
    frame_context = {
        "ready": False,
        "preview": None,
        "result_image": None,
        "decision": None,
        "stable_status": None,
        "current_person_count": 0,
        "live_frame_path": "",
    }

    def handle_socket_command(cmd, payload):
        """处理来自 Socket 的外部命令。

        参数：
        - `cmd`：命令名，比如 `trigger_inspection`、`reload_config`
        - `payload`：命令附带的数据，通常是一个字典

        返回值：
        - 成功时返回一个响应字典
        - 未处理时返回 `None`

        这就是“外部怎么触发巡检保存”的实现入口。
        """
        if cmd == "trigger_inspection":
            # 手动巡检保存必须基于当前帧快照，所以先加锁取出快照。
            with frame_context_lock:
                if not frame_context["ready"]:
                    return build_socket_error_response(cmd, "视觉画面还没有准备好，暂时无法保存当前巡检记录。")

                preview_snapshot = frame_context["preview"].copy()
                result_snapshot = frame_context["result_image"].copy()
                decision_snapshot = deepcopy(frame_context["decision"])
                stable_status_snapshot = frame_context["stable_status"]
                current_person_count_snapshot = frame_context["current_person_count"]
                live_frame_path_snapshot = frame_context["live_frame_path"]

            # 保存当前帧的原图、结果图和记录。
            raw_path, result_path, snapshot_speech_text, record = bridge.manual_snapshot(
                preview=preview_snapshot,
                result_image=result_snapshot,
                stable_status=stable_status_snapshot,
                decision=decision_snapshot,
                jsonl_path=jsonl_path,
                csv_path=csv_path,
            )
            print("Voice-triggered inspection snapshot saved:")
            print(f"- Raw image: {raw_path}")
            print(f"- Result image: {result_path}")

            # 返回给外部模块一个完整响应，告诉它保存成功。
            return build_manual_snapshot_response(
                decision=decision_snapshot,
                current_person_count=current_person_count_snapshot,
                raw_path=raw_path,
                result_path=result_path,
                speech_text=snapshot_speech_text,
                record=record,
                live_frame_path=live_frame_path_snapshot,
            )

        if cmd == "reload_config":
            # UI 保存阈值后会发这个命令。
            # 这里不直接重新加载，而是给出确认信息，真正重载由上层流程处理。
            return {
                "ack": True,
                "cmd": cmd,
                "message": "Reload config accepted. Restart vision pipeline if threshold values changed.",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        return None

    # 启动对外 Socket 服务。
    # UI / 语音模块 / C 主控都通过这个服务查询当前状态。
    # 如果不启动，外部只能读旧日志，无法实时知道当前有没有报警。
    socket_server = VisionSocketServer(command_callback=handle_socket_command)
    socket_server.start()

    # 窗口标题和大小设置。
    window_name = "YOLO11 Voice Broadcast"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 960, 720)

    try:
        # 主循环：每次循环处理一帧。
        while True:
            # 1) 读取摄像头原始帧。
            frame = read_one_frame(cap)

            # 2) 调用单帧处理函数，完成检测、判断、绘图、播报状态更新。
            (
                result_image,
                preview,
                decision,
                stable_status,
                stable_status_count,
                last_spoken_status,
                should_speak,
                speech_text,
                cooldown_counter,
                last_alarm_time,
                alarm_triggered,
                alarm_latched,
                alarm_clear_count,
                current_person_count,
            ) = process_one_frame(
                model=model,
                frame=frame,
                bridge=bridge,
                stable_person_history=stable_person_history,
                stable_frames_required=stable_frames_required,
                stable_status=stable_status,
                stable_status_count=stable_status_count,
                last_spoken_status=last_spoken_status,
                alarm_history=alarm_history,
                cooldown_counter=cooldown_counter,
                last_alarm_time=last_alarm_time,
                alarm_latched=alarm_latched,
                alarm_clear_count=alarm_clear_count,
            )

            # 3) 无人连续计数：用于 UI 显示和稳定状态判断。
            if current_person_count == 0:
                bridge.no_person_counter += 1
            else:
                bridge.no_person_counter = 0

            # 4) 周期性保存最新结果图，供 UI 直接读取。
            now_for_live_frame = time.time()
            if now_for_live_frame - last_live_frame_write >= LIVE_FRAME_INTERVAL_SECONDS:
                live_frame_path = save_live_frame(result_image)
                last_live_frame_write = now_for_live_frame

            # 5) 更新当前帧快照，供外部 trigger_inspection 使用。
            with frame_context_lock:
                frame_context.update(
                    {
                        "ready": True,
                        "preview": preview,
                        "result_image": result_image,
                        "decision": decision,
                        "stable_status": stable_status,
                        "current_person_count": current_person_count,
                        "live_frame_path": live_frame_path,
                    }
                )

            # 6) 构造 socket 状态包，更新缓存，并广播给已连接客户端。
            socket_status = build_socket_status(decision, current_person_count, live_frame_path)
            socket_server.update_status(socket_status)
            socket_server.send_result(socket_status)

            # 7) 如果状态变了，就打印一组调试信息，方便你观察流程。
            if decision.status != last_display_status:
                print(f"Current status: {decision.status} | Reason: {decision.reason}")
                print(f"- Current frame person count: {current_person_count}")
                print(f"- No person stable count: {bridge.no_person_counter}/{NO_PERSON_FRAMES_REQUIRED}")
                for item in decision.summary:
                    print(f"- {item}")
                if decision.alarm_name:
                    print(f"- Alarm: {decision.alarm_name} ({decision.alarm_label}, {decision.alarm_score:.2f})")
                if decision.zone_hit:
                    print(f"- Zone hit: {decision.zone_name}, people={decision.intruded_people}")
                last_display_status = decision.status

            # 8) 需要播报时，把文本交给 TTS 队列。
            if should_speak and speech_text:
                speak_text(speech_queue, speech_text)
                bridge.push_record(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": decision.status,
                        "reason": decision.reason,
                        "speech_text": speech_text,
                        "person_count": decision.person_count,
                        "summary": decision.summary,
                    }
                )

            # 9) 报警触发时，保存报警截图/记录，并可选保存短视频。
            if alarm_triggered:
                alarm_record = bridge.handle_alarm(
                    preview=preview,
                    result_image=result_image,
                    stable_status=stable_status,
                    decision=decision,
                    jsonl_path=jsonl_path,
                    csv_path=csv_path,
                    speech_text=speech_text or "当前状态报警。",
                )
                print("Alarm snapshot saved:")
                print(f"- Raw image: {alarm_record['raw_path']}")
                print(f"- Result image: {alarm_record['result_path']}")
                print(f"- Alarm reason: {alarm_record['alarm_reason']}")

                # 如果开启短视频保存，就从当前缓存里保存报警片段。
                if ENABLE_VIDEO_CLIP_SAVE:
                    clip_frames = deque(maxlen=ALARM_CLIP_SECONDS * ALARM_CLIP_FPS)
                    clip_frames.append(result_image.copy())
                    clip_path = bridge.save_alarm_video_if_enabled(list(clip_frames))
                    if clip_path:
                        print(f"Alarm clip saved: {clip_path}")

            # 10) 把当前结果图显示到 OpenCV 窗口里。
            cv2.imshow(window_name, result_image)

            # 11) 读取按键：q 退出，s 手动保存当前巡检。
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

            if key == ord("s"):
                raw_path, result_path, speech_text, record = bridge.manual_snapshot(
                    preview=preview,
                    result_image=result_image,
                    stable_status=stable_status,
                    decision=decision,
                    jsonl_path=jsonl_path,
                    csv_path=csv_path,
                )
                print("Saved images and record:")
                print(f"- Raw image: {raw_path}")
                print(f"- Result image: {result_path}")
                print(f"- Speech text: {speech_text}")
                print(f"- Current status: {record['status']}")
                print(f"- Reason: {record['reason']}")

    finally:
        # 退出收尾：
        # 1) 让语音线程结束；
        # 2) 关闭 socket 服务；
        # 3) 释放摄像头；
        # 4) 销毁窗口。
        try:
            speech_queue.put(None)
            tts_thread.join(timeout=2)
        except Exception:
            pass
        socket_server.shutdown()
        cap.release()
        cv2.destroyAllWindows()
        print("摄像头已释放")


if __name__ == "__main__":
    main()
