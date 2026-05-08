# 已废弃代码归档

这里的内容不再参与构建，留作历史备查。

## rk3588_main/

旧的 C 单体主控（`vision_client` + `decision_engine` + `actuator_control`），在多线程版本 [`rk3588/`](../rk3588/) 完成后停止维护。
保留原因：里面的 Unix Socket 客户端、build_windows_msys2.ps1 还可能拿来参考。

## tools_use_cbuild.ps1

旧的 Windows 构建包装脚本，只是调用 `archive/rk3588_main/build_windows_msys2.ps1`。

---

如果确认这些都不再需要，可以直接删掉整个 `archive/` 目录。
