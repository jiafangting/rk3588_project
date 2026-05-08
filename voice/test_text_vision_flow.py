"""自动测试文本模式下的语音状态机和视觉命令解析。"""

from pathlib import Path
import sys


VOICE_DIR = Path(__file__).resolve().parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

from voice_loop import VoiceAssistant


class FakeBroadcaster:
    def __init__(self):
        self.messages = []

    def start(self):
        pass

    def speak(self, text):
        self.messages.append(text)
        print(f"[FAKE_SPEAK] {text}")

    def stop(self):
        pass


class FakeVisionClient:
    def get_status(self):
        return {
            "status": "NORMAL",
            "person_count": 1,
            "reason": "模拟视觉状态正常",
            "timestamp": "2026-05-08 00:00:00",
        }

    def trigger_inspection(self):
        return {
            "status": "ALARM",
            "person_count": 1,
            "reason": "模拟检测到人员进入右侧禁区",
            "timestamp": "2026-05-08 00:00:00",
        }


def main():
    assistant = VoiceAssistant(text_mode=True)
    assistant.broadcaster = FakeBroadcaster()
    assistant.vision_client = FakeVisionClient()

    assistant.handle_text("wake")
    assistant.handle_text("mode")
    assistant.handle_text("vision")
    assistant.handle_text("inspect")
    assistant.handle_text("stop")

    assert assistant.mode == "work"
    assert not assistant.running
    assert any("工作模式" in msg for msg in assistant.broadcaster.messages)
    assert any("当前视觉状态" in msg for msg in assistant.broadcaster.messages)
    assert any("巡检完成" in msg for msg in assistant.broadcaster.messages)
    print("[TEST] text vision flow passed")


if __name__ == "__main__":
    main()
