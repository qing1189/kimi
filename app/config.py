import os
import re
from decimal import Decimal, InvalidOperation


_SIZE_PATTERN = re.compile(r"^\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]*)\s*$")
_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
}


def _parse_size_bytes(name: str, value: str) -> int:
    match = _SIZE_PATTERN.match(value or "")
    if not match:
        raise ValueError(f"{name} must be a size like 1024, 512KB, 1MB, or 2GiB")

    unit = match.group("unit").lower()
    multiplier = _SIZE_UNITS.get(unit)
    if multiplier is None:
        raise ValueError(f"{name} must use one of: B, KB, MB, GB, KiB, MiB, GiB")

    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must start with a valid number") from exc

    return int(amount * multiplier)


def _request_log_body_limit() -> int:
    return _parse_size_bytes("REQUEST_LOG_BODY_LIMIT", os.getenv("REQUEST_LOG_BODY_LIMIT", "1MB"))


class Config:
    KIMI_TOKEN: str = ""
    KIMI_API_BASE: str = "https://www.kimi.com"
    KIMI_ACCEPT_LANGUAGE: str = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    KIMI_MAX_CONCURRENCY: int = 2
    KIMI_MIN_REQUEST_INTERVAL: float = 0.5
    KIMI_REQUEST_INTERVAL_JITTER: float = 0.0
    KIMI_MAX_REQUESTS_PER_MINUTE: int = 0
    KIMI_MAX_REQUESTS_PER_HOUR: int = 0
    KIMI_AUTO_PROBE_INTERVAL: float = 300.0
    TIMEOUT: int = 120
    DEFAULT_MODEL: str = ""
    OPENAI_API_KEY: str = ""
    ADMIN_PASSWORD: str = ""
    SESSION_SECRET: str = ""
    SECURE_COOKIES: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = False
    DATA_DIR: str = "data"
    REQUEST_LOG_RETENTION: int = 1000
    REQUEST_LOG_BODY_LIMIT: int = 1048576
    TIMEZONE: str = "Asia/Shanghai"
    # 调试日志配置
    DEBUG_TOOL_CALLS: bool = False  # 启用工具调用详细日志
    DEBUG_LOG_LEVEL: str = "INFO"  # 日志级别: DEBUG, INFO, WARNING, ERROR
    # 会话管理配置
    AUTO_DELETE_CHAT: str = "disabled"  # 自动删除会话: disabled, on_completion, always
    # HTTP 性能配置
    HTTP_MAX_CONNECTIONS: int = 100
    HTTP_MAX_KEEPALIVE_CONNECTIONS: int = 20
    HTTP_KEEPALIVE_EXPIRY: float = 30.0
    HTTP2_ENABLED: bool = False  # 需要安装 httpx[http2]

    @classmethod
    def load(cls) -> None:
        cls.KIMI_TOKEN = os.getenv("KIMI_TOKEN", "")
        cls.KIMI_API_BASE = os.getenv("KIMI_API_BASE", "https://www.kimi.com")
        cls.KIMI_ACCEPT_LANGUAGE = os.getenv(
            "KIMI_ACCEPT_LANGUAGE",
            "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        )
        cls.KIMI_MAX_CONCURRENCY = max(int(os.getenv("KIMI_MAX_CONCURRENCY", "2")), 1)
        cls.KIMI_MIN_REQUEST_INTERVAL = max(float(os.getenv("KIMI_MIN_REQUEST_INTERVAL", "0.5")), 0.0)
        cls.KIMI_REQUEST_INTERVAL_JITTER = max(
            float(os.getenv("KIMI_REQUEST_INTERVAL_JITTER", "0.0")), 0.0
        )
        cls.KIMI_MAX_REQUESTS_PER_MINUTE = max(
            int(os.getenv("KIMI_MAX_REQUESTS_PER_MINUTE", "0")), 0
        )
        cls.KIMI_MAX_REQUESTS_PER_HOUR = max(
            int(os.getenv("KIMI_MAX_REQUESTS_PER_HOUR", "0")), 0
        )
        cls.KIMI_AUTO_PROBE_INTERVAL = max(
            float(os.getenv("KIMI_AUTO_PROBE_INTERVAL", "300")), 0.0
        )
        cls.TIMEOUT = int(os.getenv("TIMEOUT", "120"))
        cls.DEFAULT_MODEL = os.getenv("MODEL", "")
        cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        cls.ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
        cls.SESSION_SECRET = os.getenv("SESSION_SECRET") or ""
        cls.SECURE_COOKIES = os.getenv("SECURE_COOKIES", "true").lower() in {"1", "true", "yes", "on"}
        cls.HOST = os.getenv("HOST", "127.0.0.1")
        cls.PORT = int(os.getenv("PORT", "8000"))
        cls.RELOAD = os.getenv("RELOAD", "").lower() in {"1", "true", "yes", "on"}
        cls.DATA_DIR = os.getenv("DATA_DIR", "data")
        cls.REQUEST_LOG_RETENTION = int(os.getenv("REQUEST_LOG_RETENTION", "1000"))
        cls.REQUEST_LOG_BODY_LIMIT = _request_log_body_limit()
        cls.TIMEZONE = os.getenv("TIMEZONE") or os.getenv("TZ", "Asia/Shanghai")
        # 调试日志配置
        cls.DEBUG_TOOL_CALLS = os.getenv("DEBUG_TOOL_CALLS", "false").lower() in {"1", "true", "yes", "on"}
        cls.DEBUG_LOG_LEVEL = os.getenv("DEBUG_LOG_LEVEL", "INFO").upper()
        # 会话管理配置
        auto_delete = os.getenv("AUTO_DELETE_CHAT", "disabled").lower()
        if auto_delete in {"disabled", "on_completion", "always"}:
            cls.AUTO_DELETE_CHAT = auto_delete
        else:
            cls.AUTO_DELETE_CHAT = "disabled"
        # HTTP 性能配置
        cls.HTTP_MAX_CONNECTIONS = max(int(os.getenv("HTTP_MAX_CONNECTIONS", "100")), 1)
        cls.HTTP_MAX_KEEPALIVE_CONNECTIONS = max(
            int(os.getenv("HTTP_MAX_KEEPALIVE_CONNECTIONS", "20")), 1
        )
        cls.HTTP_KEEPALIVE_EXPIRY = max(float(os.getenv("HTTP_KEEPALIVE_EXPIRY", "30.0")), 0.0)
        cls.HTTP2_ENABLED = os.getenv("HTTP2_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
