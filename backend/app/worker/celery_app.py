import sys

from celery import Celery
from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "credit_analysis",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    broker_connection_retry_on_startup=True,
)
# On Windows, prefork pool (billiard) can cause PermissionError / invalid handle when
# passing task payloads to worker processes. Use solo pool (single process, no fork).
if sys.platform == "win32":
    celery_app.conf.worker_pool = "solo"
