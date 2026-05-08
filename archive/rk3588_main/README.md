# RK3588 C Main Controller

This directory contains the C main process for the industrial inspection system.

## Build

Linux / RK3588:

```bash
cd rk3588_main
make
```

Windows MSYS2:

```powershell
PowerShell -ExecutionPolicy Bypass -File E:\rk3588_project\rk3588_main\build_windows_msys2.ps1
```

## Run Order

Start Python vision first:

```bash
python run_vision.py
```

Then start the C process:

```bash
cd rk3588_main
./rk3588_main
```

Default socket path:

```text
/tmp/vision_inspection.sock
```

## Menu

- `g`: get current vision status
- `t`: trigger one inspection snapshot
- `w`: wait for one pushed vision result
- `a`: auto monitor vision status 10 times
- `s`: ask Python vision module to shutdown
- `q`: quit C process only
