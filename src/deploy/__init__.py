"""Деплой на VPS после задач планировщика / агента."""

from src.deploy.vps_deploy import run_deploy, run_deploy_after_job

__all__ = ["run_deploy", "run_deploy_after_job"]
