"""Тесты автодеплоя на VPS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import DeployConfig, reload_config
from src.deploy import vps_deploy


@pytest.fixture
def deploy_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        "dry_run: true\ndeploy:\n  enabled: true\n  min_interval_minutes: 15\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SETTINGS_PATH", str(yaml_path))
    monkeypatch.setenv("DEPLOY_ENABLED", "true")
    monkeypatch.setenv("VPS_HOST", "test.example.com")
    monkeypatch.setenv("VPS_USER", "deploy")
    reload_config()


def test_run_deploy_after_job_skips_failed(deploy_cfg: None) -> None:
    _ = deploy_cfg
    with patch.object(vps_deploy, "run_deploy") as mock_deploy:
        assert vps_deploy.run_deploy_after_job("price_snapshot", job_success=False) is False
        mock_deploy.assert_not_called()


def test_run_deploy_after_job_triggers(deploy_cfg: None) -> None:
    _ = deploy_cfg
    with patch.object(vps_deploy, "run_deploy", return_value=True) as mock_deploy:
        assert vps_deploy.run_deploy_after_job("price_snapshot", job_success=True) is True
        mock_deploy.assert_called_once_with(trigger="job:price_snapshot")


def test_run_deploy_debounce(deploy_cfg: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = deploy_cfg
    state = tmp_path / "data" / "last_deploy.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        '{"deployed_at": "'
        + (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        + '"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(vps_deploy, "_project_root", lambda: tmp_path)
    with patch("subprocess.run") as mock_run:
        assert vps_deploy.run_deploy(trigger="manual") is False
        mock_run.assert_not_called()


def test_run_deploy_ssh_success(deploy_cfg: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = deploy_cfg
    monkeypatch.setattr(vps_deploy, "_project_root", lambda: tmp_path)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        assert vps_deploy.run_deploy(trigger="manual", force=True) is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "ssh"
        assert "deploy@test.example.com" in args[3]


def test_deploy_config_defaults() -> None:
    cfg = DeployConfig()
    assert cfg.enabled is False
    assert "price_snapshot" in cfg.job_ids
