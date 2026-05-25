"""视觉模块启动前检查。

这个文件只做“开机前体检”，不做真正的识别。
它负责确认：
1. 模型文件在不在；
2. 输出目录能不能写；
3. 摄像头是否能打开（如果要求检查）。

流程：
- 主入口调用 `run_startup_check()`；
- 这里打印参数、验证路径、验证摄像头；
- 如果失败就直接抛异常，阻止主程序进入实时识别。
"""

from pathlib import Path


def run_startup_check(camera_index, model_path, output_dir, check_camera_flag=True):
    """执行启动前检查。

    参数：
    - `camera_index`：摄像头编号
    - `model_path`：模型文件路径
    - `output_dir`：输出目录
    - `check_camera_flag`：是否检查摄像头

    返回值：
    - `True`：检查通过

    这个函数的意义：
    在真正进入视觉主流程之前，先把最容易出问题的资源检查一遍，
    这样报错会更早、更清楚。
    """
    print("Running startup check...")
    print(f"- Camera index: {camera_index}")
    print(f"- Model path  : {model_path}")
    print(f"- Output dir  : {output_dir}")

    model_path = Path(model_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    if check_camera_flag:
        import cv2

        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        ok = cap.isOpened()
        cap.release()
        if not ok:
            raise RuntimeError(f"Camera is not available: {camera_index}")

    print("Startup check passed")
    return True
