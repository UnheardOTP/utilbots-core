from pathlib import Path

from utilbots_core.web import create_app

from .. import models  # noqa: F401  (register tables)
from .routes import router

HERE = Path(__file__).parent
app = create_app(routers=[router], templates_dir=HERE / "templates", static_dir=HERE / "static")
