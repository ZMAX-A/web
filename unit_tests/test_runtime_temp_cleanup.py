import os
import tempfile
from types import SimpleNamespace

import conftest as runtime_config


def _configuration(basetemp=None):
    cleanups = []
    config = SimpleNamespace(
        option=SimpleNamespace(basetemp=basetemp),
        add_cleanup=cleanups.append,
    )
    return config, cleanups


def test_cleanup_preserves_another_active_session_and_restores_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config.sys, "platform", "win32")
    sentinel = tmp_path / "other-active-session.txt"
    sentinel.write_text("keep", encoding="utf-8")
    previous_env = {name: os.environ.get(name) for name in ("TEMP", "TMP", "TMPDIR")}
    previous_tempdir = tempfile.tempdir
    config, cleanups = _configuration()
    runtime_config.pytest_configure(config)
    session_dir = config._project_temp_dir
    (session_dir / "browser-artifact.txt").write_text("temporary", encoding="utf-8")

    # 即使配置对象的路径被其他插件改动，清理仍只针对自己创建的目录。
    config._project_temp_dir = tmp_path
    cleanups[0]()

    assert not session_dir.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert {name: os.environ.get(name) for name in previous_env} == previous_env
    assert tempfile.tempdir == previous_tempdir


def test_cleanup_preserves_explicit_basetemp(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config.sys, "platform", "win32")
    explicit_temp = tmp_path / "explicit-basetemp"
    explicit_temp.mkdir()
    sentinel = explicit_temp / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    config, cleanups = _configuration(str(explicit_temp))
    runtime_config.pytest_configure(config)
    session_dir = config._project_temp_dir
    assert config.option.basetemp == str(explicit_temp)

    cleanups[0]()

    assert not session_dir.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_cleanup_permission_error_is_visible_and_keeps_directory(monkeypatch, capsys):
    monkeypatch.setattr(runtime_config.sys, "platform", "win32")
    config, cleanups = _configuration()
    runtime_config.pytest_configure(config)
    session_dir = config._project_temp_dir

    def deny_delete(path):
        raise PermissionError("directory is locked")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(runtime_config.shutil, "rmtree", deny_delete)
            cleanups[0]()
        assert session_dir.exists()
        assert "directory is locked" in capsys.readouterr().err
    finally:
        cleanups[0]()
