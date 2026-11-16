from .base import Loader, Message, Trace
from .excel import ExcelLoader

__all__ = ["ExcelLoader", "Loader", "Message", "Trace"]


def get_langfuse_loader(*args, **kwargs):
    """Lazy-import Langfuse loader so the package can be used without the SDK installed."""
    from .langfuse import LangfuseLoader

    return LangfuseLoader(*args, **kwargs)
