"""HTTP evaluation service.

Run it through the application factory :func:`groundtruth.api.app.create_app`
(``uvicorn --factory groundtruth.api.app:create_app``); no application object
is created at import time.
"""

from groundtruth.api.app import create_app
from groundtruth.api.state import ServiceState

__all__ = ["ServiceState", "create_app"]
