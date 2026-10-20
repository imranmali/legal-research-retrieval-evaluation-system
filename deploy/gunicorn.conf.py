"""Gunicorn settings for the Ground Truth API container.

Every value can be overridden through the environment so the image stays
configurable without rebuilding. Application settings use the ``GROUNDTRUTH_``
prefix and are read by ``groundtruth.config.Settings``; the variables below
only tune the process manager.
"""

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


bind = f"0.0.0.0:{_int_env('PORT', 8000)}"
worker_class = "uvicorn.workers.UvicornWorker"
workers = _int_env("WEB_CONCURRENCY", 2)

# Requests are evaluated in-process; allow long evaluations before the
# arbiter kills a worker, and give in-flight requests time to finish on
# SIGTERM (Kubernetes waits terminationGracePeriodSeconds = 30).
timeout = _int_env("GUNICORN_TIMEOUT", 120)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 25)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)

# Recycle workers periodically to bound memory growth from large payloads.
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 2000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 200)

# The root filesystem is read-only in production: keep worker heartbeat
# files in memory and do not create a control socket under $HOME.
worker_tmp_dir = "/dev/shm"
control_socket_disable = True

# Logs go to stdout/stderr for the container runtime to collect.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Trust X-Forwarded-* only from addresses the operator lists (ingress/LB).
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
