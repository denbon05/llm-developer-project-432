from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


def bootstrap() -> Settings:
    """Configure logging and settings"""
    configure_logging()
    return get_settings()
