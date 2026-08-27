from .clients import router as clients_router
from .field_mapping import router as field_mapping_router
from .plugins import router as plugins_router
from .quality import router as quality_router
from .registry import router as registry_router

__all__ = ["clients_router", "field_mapping_router", "plugins_router", "quality_router", "registry_router"]
