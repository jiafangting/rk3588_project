"""阶段 A:只测 TTS 能不能说话。
放在 scripts/ 目录下,和 alarm_voice_demo.py 同级。
"""
import time
from alarm_voice_demo import TTSBroadcaster

print("启动 TTS...")
t = TTSBroadcaster()
t.start()
t.speak("你好,工业巡检系统启动")
t.speak("这是第二句话,如果你能听到,说明语音播报正常")
time.sleep(6)
t.stop()
print("测试完成")
