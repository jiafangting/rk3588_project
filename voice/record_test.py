"""录音测试脚本。

运行方式：
    python voice/record_test.py

依赖：
    pip install sounddevice scipy

如果当前环境没有 sounddevice，这个脚本会给出提示，不会静默失败。
"""

from pathlib import Path


def main():
    try:
        import sounddevice as sd
        from scipy.io.wavfile import write
    except ImportError as exc:
        raise RuntimeError("录音测试需要安装 sounddevice 和 scipy：pip install sounddevice scipy") from exc

    sample_rate = 16000
    seconds = 3
    output_path = Path(__file__).resolve().parent / "record_test.wav"

    print(f"开始录音 {seconds} 秒...")
    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    write(str(output_path), sample_rate, audio)
    print(f"录音保存完成：{output_path}")


if __name__ == "__main__":
    main()
