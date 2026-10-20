"""为 Windows 测试进程准备项目内的独立临时目录。"""
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    # 必须早于 Playwright driver 启动；它在启动时继承 TEMP/TMP。
    if sys.platform != "win32":
        return

    temp_root = Path(__file__).resolve().parent / ".runtime-tmp"
    temp_dir = temp_root / f"run-{os.getpid()}-{uuid.uuid4().hex}"
    previous_env = {name: os.environ.get(name) for name in ("TEMP", "TMP", "TMPDIR")}
    previous_tempdir = tempfile.tempdir
    previous_basetemp = config.option.basetemp

    def cleanup_temp_directory():
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        tempfile.tempdir = previous_tempdir
        config.option.basetemp = previous_basetemp
        try:
            # 只删除本次创建的绝对路径；拒绝后来被替换成链接的目录。
            if temp_dir.resolve() != temp_dir or temp_dir.parent != temp_root:
                raise OSError("临时目录路径已改变，停止清理")
            shutil.rmtree(temp_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"WARNING: 临时目录清理失败，已保留 {temp_dir}: {exc}", file=sys.stderr)

    try:
        if temp_root.resolve() != temp_root:
            raise OSError("项目临时目录不能指向其他路径")
        temp_dir.mkdir(parents=True)
        # 最先注册、最后执行：等 fixture 和其他插件收尾后再删除目录。
        # 配置或收集失败也会执行，不依赖测试会话正常完成。
        config.add_cleanup(cleanup_temp_directory)
        probe = temp_dir / ".write-check"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise pytest.UsageError(
            f"项目临时目录不可写: {temp_dir}\n"
            f"{exc}\n请检查当前进程的目录写入权限。"
        ) from exc

    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(temp_dir)
    # tempfile 可能在 pytest 插件加载期间已缓存系统 Temp，需同步更新。
    tempfile.tempdir = str(temp_dir)
    if config.option.basetemp is None:
        config.option.basetemp = str(temp_dir / "pytest")

    config._project_temp_dir = temp_dir


def pytest_report_header(config):
    temp_dir = getattr(config, "_project_temp_dir", None)
    if temp_dir is not None:
        return f"Project temporary directory: {temp_dir}"
