from app.api.routes.crawls import router as crawls_router
from app.api.routes.contacts import router as contacts_router
from app.api.routes.stats import router as stats_router
from app.api.routes.metrics import router as metrics_router

__all__ = ["crawls_router", "contacts_router", "stats_router", "metrics_router"]
