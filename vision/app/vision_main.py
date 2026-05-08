"""Formal Python vision entry point."""

from config import CAMERA_INDEX, MODEL_PATH, OUTPUT_DIR, validate_config
from startup import run_startup_check
from vision_pipeline import main as pipeline_main


def main():
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
