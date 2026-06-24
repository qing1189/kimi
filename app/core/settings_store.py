"""系统设置存储模块

存储和管理 Kimi2API 的运行时设置，包括：
- 自动删除会话配置
- 其他可动态调整的系统配置
"""
import json
import os
from typing import Any, Dict, Optional

from ..config import Config

_SETTINGS_FILE = os.path.join(Config.DATA_DIR, "settings.json")
_settings_cache: Optional[Dict[str, Any]] = None


def _default_settings() -> Dict[str, Any]:
    """默认设置"""
    return {
        "auto_delete_chat": "disabled",  # disabled, on_completion, always
        "version": 1,
    }


def load_settings() -> Dict[str, Any]:
    """加载设置"""
    global _settings_cache

    if _settings_cache is not None:
        return _settings_cache.copy()

    if not os.path.exists(_SETTINGS_FILE):
        _settings_cache = _default_settings()
        return _settings_cache.copy()

    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                data = _default_settings()
            # 确保所有默认键都存在
            defaults = _default_settings()
            for key, value in defaults.items():
                if key not in data:
                    data[key] = value
            _settings_cache = data
            return _settings_cache.copy()
    except Exception:
        _settings_cache = _default_settings()
        return _settings_cache.copy()


def save_settings(settings: Dict[str, Any]) -> None:
    """保存设置"""
    global _settings_cache

    os.makedirs(Config.DATA_DIR, exist_ok=True)

    # 验证设置值
    validated = _default_settings()

    # 验证 auto_delete_chat
    auto_delete = settings.get("auto_delete_chat", "disabled")
    if auto_delete in {"disabled", "on_completion", "always"}:
        validated["auto_delete_chat"] = auto_delete

    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)
        _settings_cache = validated
    except Exception as exc:
        raise RuntimeError(f"Failed to save settings: {exc}") from exc


def get_setting(key: str, default: Any = None) -> Any:
    """获取单个设置项"""
    settings = load_settings()
    return settings.get(key, default)


def update_setting(key: str, value: Any) -> None:
    """更新单个设置项"""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)


def reset_settings() -> None:
    """重置为默认设置"""
    global _settings_cache
    _settings_cache = None
    if os.path.exists(_SETTINGS_FILE):
        os.remove(_SETTINGS_FILE)


def get_auto_delete_chat_mode() -> str:
    """获取自动删除会话模式

    Returns:
        str: disabled, on_completion, always
    """
    # 优先使用数据库设置，如果没有则使用环境变量
    db_mode = get_setting("auto_delete_chat", None)
    if db_mode is not None and db_mode in {"disabled", "on_completion", "always"}:
        return db_mode

    # 回退到环境变量配置
    return getattr(Config, "AUTO_DELETE_CHAT", "disabled")
