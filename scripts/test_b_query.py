"""阶段 B:语音查询测试。

1. 先往 alarm_records.jsonl 写 3 条假报警记录(模拟系统已经跑了一段时间)
2. 进入文本查询模式,你可以输入问题,听 TTS 回答

放在 scripts/ 目录,和 alarm_voice_demo.py 同级。
"""
import json
from datetime import datetime
from pathlib import Path

from alarm_voice_demo import OUTPUT_DIR, JSONL_PATH, ensure_output_dir, run_query_mode


def insert_fake_records():
    """塞 3 条今天的假报警记录,模拟系统已经检测到过几次异常。"""
    ensure_output_dir()

    today = datetime.now().strftime("%Y-%m-%d")
    fake_records = [
        {
            "timestamp": f"{today} 09:15:30",
            "alarm_type": "zone",
            "alarm_name": "人员进入禁区",
            "reason": "禁区 right_zone 内有 1 人",
            "raw_path": "",
            "result_path": "",
        },
        {
            "timestamp": f"{today} 11:42:08",
            "alarm_type": "fire",
            "alarm_name": "检测到明火",
            "reason": "标签=fire, 置信度=0.87",
            "raw_path": "",
            "result_path": "",
        },
        {
            "timestamp": f"{today} 14:32:55",
            "alarm_type": "occlusion",
            "alarm_name": "画面遮挡",
            "reason": "画面过暗 (亮度=12.3)",
            "raw_path": "",
            "result_path": "",
        },
    ]

    # 写入 JSONL(追加模式,如果之前有记录不会覆盖)
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        for r in fake_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[INIT] 已写入 3 条假报警记录到 {JSONL_PATH}")
    print()


class _Args:
    """模拟命令行参数对象。"""
    pass


if __name__ == "__main__":
    insert_fake_records()
    print("=" * 50)
    print("现在你可以输入下列问题,系统会用 TTS 回答:")
    print("  1. 有没有报警")
    print("  2. 最近一次报警是什么")
    print("  3. 报警几次了")
    print("  4. 帮我保存")
    print("输入 q 退出")
    print("=" * 50)
    run_query_mode(_Args())
