from collections import deque
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
# 视觉主流程：
# 1. 调用 vision_core 做检测和判断
# 2. 调用 vision_bridge 做报警联动和记录
# 3. 控制显示、播报、退出
# =========================


def initialize_runtime():
    """初始化运行环境并检查关键资源。"""
    ensure_output_dir()
    validate_config(check_camera=False)
    print("运行前检查完成：模型和输出目录可用")


def format_label_text(text):
    """把下划线标签转成更友好的显示文本。"""
    if not text:
        return text
    return text.replace("_", " ")


def draw_hazard_zone(image, hazard_zone):
    """在画面上绘制禁区矩形。"""
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
    """统计进入禁区的人数。"""
    top_left = hazard_zone["top_left"]
    bottom_right = hazard_zone["bottom_right"]
    hit_count = 0
    for center in person_centers:
        if point_in_rect(center, top_left, bottom_right):
            hit_count += 1
    return hit_count, hit_count > 0


def box_overlap_ratio(box, top_left, bottom_right):
    x1, y1, x2, y2 = box
    zx1, zy1 = top_left
    zx2, zy2 = bottom_right

    inter_w = max(0.0, min(x2, zx2) - max(x1, zx1))
    inter_h = max(0.0, min(y2, zy2) - max(y1, zy1))
    inter_area = inter_w * inter_h
    box_area = max(1.0, (x2 - x1) * (y2 - y1))
    return inter_area / box_area


def point_in_zone(point, top_left, bottom_right):
    x, y = point
    x1, y1 = top_left
    x2, y2 = bottom_right
    return x1 <= x <= x2 and y1 <= y <= y2


def count_intrusions(person_boxes, hazard_zone):
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


def build_socket_status(decision, current_person_count):
    """Build the small status payload shared with the voice module.

    The voice module should not have to parse images or local cache. It only
    needs the current alarm state, person count, reason and timestamp. Keeping
    this payload tiny makes the socket contract stable and easy to test.
    """
    return {
        "status": decision.status,
        "person_count": current_person_count,
        "reason": decision.reason,
        "zone_name": decision.zone_name or "",
        "intruded_people": decision.intruded_people,
        "alarm_frame_count": decision.alarm_frame_count,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_status_style(status):
    """根据状态返回显示颜色。"""
    if status == "ALARM":
        return (0, 0, 255), (255, 255, 255)
    if status == "ABNORMAL":
        return (0, 165, 255), (255, 255, 255)
    if status == "NORMAL":
        return (0, 180, 0), (255, 255, 255)
    return (80, 80, 80), (255, 255, 255)


def draw_status_panel(image, decision, current_person_count, no_person_count):
    """在画面左上角绘制更明显的状态面板。

    重要参数：
    - current_person_count：当前帧人数，直接显示给你看
    - no_person_count：连续没检测到人的帧数，便于判断“无人”是否稳定
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
    """在画面顶部绘制醒目的报警横幅。"""
    if decision.status != "ALARM":
        return image
    h, w = image.shape[:2]
    cv2.rectangle(image, (0, 0), (w, 30), (0, 0, 255), -1)
    cv2.putText(image, "ALARM ACTIVE", (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def draw_latest_preview(image, preview_path):
    """在右下角显示最近一次报警截图路径提示。

    这个函数主要用于演示场景：
    - 有报警时，右下角提示最近一张报警图已经保存
    - 后面如果你想真正把缩略图画出来，也可以在这里继续扩展
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
    """处理单帧图像并返回结果。

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

    alarm_label, alarm_name, alarm_score = None, None, None
    current_alarm_signal = zone_hit

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
        decision.zone_hit = True
        decision.zone_name = HAZARD_ZONE["name"]
        if zone_hit:
            decision.reason = f"Intrusion into hazard zone: {format_label_text(HAZARD_ZONE['name'])}"
        else:
            decision.reason = f"Zone intrusion confirmed by {ALARM_FRAMES_REQUIRED}-frame vote"
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
        if decision.zone_hit:
            speech_text = f"当前状态报警。检测到人员进入禁区：{format_label_text(HAZARD_ZONE['name'])}。"
        else:
            speech_text = f"当前状态报警。检测到报警目标：{format_label_text(alarm_name)}。"
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
    """视觉主入口。"""
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

    bridge = VisionBridge(output_dir=output_dir)
    bridge.no_person_counter = 0

    # Start the socket server used by voice/vision_control.py.
    # Without this server the voice module can only read old JSONL/CSV files,
    # so a live visual alarm may be missed until a record is written. Publishing
    # the latest status on every frame keeps "有没有报警" synchronized with the
    # current visual state.
    socket_server = VisionSocketServer()
    socket_server.start()

    window_name = "YOLO11 Voice Broadcast"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 960, 720)

    try:
        while True:
            frame = read_one_frame(cap)

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

            if current_person_count == 0:
                bridge.no_person_counter += 1
            else:
                bridge.no_person_counter = 0

            socket_status = build_socket_status(decision, current_person_count)
            socket_server.update_status(socket_status)
            socket_server.send_result(socket_status)

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

            cv2.imshow(window_name, result_image)

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
