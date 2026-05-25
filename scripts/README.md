# scripts 启动脚本目录

这个目录放的是项目的常用启动、停止、测试和检查脚本。
它的作用是把“常见操作”变成一条命令，方便新手快速跑通项目。

> 说明
>
> 这里通常不放核心业务逻辑，只放“怎么启动、怎么检查、怎么演示”的脚本。

## 这个目录做什么

常见功能包括：

- 启动视觉模块；
- 启动语音模块；
- 启动整套系统；
- 停止整套系统；
- 做健康检查；
- 做文本模式演示；
- 做一键仿真演示。

## 目录中的常见脚本

- `run_device.py`：Python 侧综合启动入口；
- `run_vision.py`：仅启动视觉模块；
- `run_software_simulation.py`：软件仿真后端；
- `start_system.sh`：Linux 下一键启动 C 主控 + 视觉 + 语音；
- `stop_system.sh`：停止系统；
- `health_check.sh`：检查服务是否正常；
- `alarm_voice_demo.py`：演示报警语音闭环；
- `start_software_simulation_demo.ps1`：Windows 下的一键仿真演示。

## 如何理解这些脚本

- `run_*.py`：偏 Python 模块调试；
- `*.sh`：偏 Linux 部署和现场运行；
- `*.ps1`：偏 Windows 学习和仿真演示。

## 新手建议

先看这几个：

1. `run_software_simulation.py`：看软件仿真怎么跑；
2. `run_device.py`：看 Python 侧主流程怎么启动；
3. `start_system.sh`：看真机部署怎么串起来。
