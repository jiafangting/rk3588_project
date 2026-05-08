"""识别 test.wav 的最小 ASR 测试脚本。"""

from pathlib import Path


def main():
    from faster_whisper import WhisperModel

    wav_path = Path(__file__).resolve().parents[1] / "test.wav"
    if not wav_path.exists():
        raise FileNotFoundError(f"没有找到录音文件：{wav_path}")

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(wav_path), language="zh", beam_size=5, vad_filter=True)
    text = "".join(segment.text for segment in segments).strip()

    print(f"识别语言：{info.language}")
    print(f"置信度：{info.language_probability:.2f}")
    print(f"识别文本：{text}")


if __name__ == "__main__":
    main()
