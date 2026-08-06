from src.observability.langfuse_client import (
    get_langfuse,
    reset_langfuse_for_tests,
    resolve_langfuse_environment,
)
from src.settings import get_settings

get_settings.cache_clear()
reset_langfuse_for_tests()
s = get_settings()
print(
    "app_env",
    s.app_env,
    "override",
    repr(s.langfuse_tracing_environment),
    "resolved",
    resolve_langfuse_environment(),
)
c = get_langfuse()
print("client_env", getattr(c, "_environment", None) if c else None)
