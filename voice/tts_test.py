"""语音播报最小测试脚本。

运行方式：
    python voice/tts_test.py

作用：
    只测试电脑能不能用 pyttsx3 播放一句话。
"""

from voice_broadcast import speak_once


def main():
    speak_once("语音播报测试成功。当前工业巡检系统语音模块正常。")


if __name__ == "__main__":
    main()
