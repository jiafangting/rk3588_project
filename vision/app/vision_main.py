"""视觉模块的正式入口。

这个文件的职责非常单一：
1. 先检查配置是否可用；
2. 再做启动前检查；
3. 最后进入视觉主流程。

你可以把它理解成“开机按钮”：真正复杂的检测逻辑不在这里，
而是在 `vision_pipeline.py` 里。
"""

from config import CAMERA_INDEX, MODEL_PATH, OUTPUT_DIR, validate_config
from startup import run_startup_check
from vision_pipeline import main as pipeline_main


def main():
    """视觉程序入口。

    流程：
    - 输入：无，全部从 `config.py` 读取全局配置；
    - 处理：检查配置、检查模型、检查输出目录；
    - 输出：进入 `vision_pipeline.main()` 开始实时检测。
    """
    validate_config(check_camera=False, camera_index=CAMERA_INDEX)
    run_startup_check(
        camera_index=CAMERA_INDEX,
        model_path=MODEL_PATH,
        output_dir=OUTPUT_DIR,
        check_camera_flag=True,
    )
    pipeline_main()


if __name__ == "__main__":
    main()
