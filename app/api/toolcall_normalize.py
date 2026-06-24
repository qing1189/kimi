"""
工具调用规范化模块

参考 qwen2API 项目的优秀实践，实现：
1. 工具名称规范化（Tool Name Canonicalization）
2. 参数名称修复（Parameter Name Coercion）
3. Schema 驱动的类型转换
4. 参数污染检测

这些功能显著提升工具调用的容错性和成功率。
"""

import re
import json
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# 工具名称别名映射
# ============================================================================

TOOL_ALIASES = {
    # Bash 相关
    "bash": "Bash",
    "shell": "Bash",
    "shell_run": "Bash",
    "run_command": "Bash",
    "execute": "Bash",
    "run_bash": "Bash",
    "execute_command": "Bash",

    # Read 相关
    "read": "Read",
    "read_file": "Read",
    "fs_open_file": "Read",
    "open_file": "Read",
    "get_file": "Read",
    "load_file": "Read",
    "view_file": "Read",

    # Write 相关
    "write": "Write",
    "write_file": "Write",
    "fs_put_file": "Write",
    "create_file": "Write",
    "save_file": "Write",
    "put_file": "Write",

    # Edit 相关
    "edit": "Edit",
    "edit_file": "Edit",
    "fs_patch_file": "Edit",
    "modify_file": "Edit",
    "update_file": "Edit",
    "patch_file": "Edit",
    "change_file": "Edit",

    # Grep 相关
    "grep": "Grep",
    "search": "Grep",
    "text_search": "Grep",
    "find_text": "Grep",
    "search_text": "Grep",

    # Glob 相关
    "glob": "Glob",
    "find": "Glob",
    "path_find": "Glob",
    "find_files": "Glob",
    "list_files": "Glob",

    # WebFetch 相关
    "webfetch": "WebFetch",
    "fetch": "WebFetch",
    "http_get": "WebFetch",
    "http_get_url": "WebFetch",
    "get_url": "WebFetch",

    # WebSearch 相关
    "websearch": "WebSearch",
    "web_search": "WebSearch",
    "web_query": "WebSearch",
    "search_web": "WebSearch",
    "google": "WebSearch",

    # NotebookEdit 相关
    "notebookedit": "NotebookEdit",
    "notebook_edit": "NotebookEdit",
    "notebook_patch": "NotebookEdit",
    "edit_notebook": "NotebookEdit",
}


# ============================================================================
# 参数名称别名映射
# ============================================================================

PARAMETER_ALIASES = {
    "Read": {
        "file_path": ["path", "filename", "file", "filepath", "target", "target_file"],
    },
    "Write": {
        "file_path": ["path", "filename", "file", "filepath", "target", "target_file"],
        "content": ["text", "body", "data", "file_content", "contents", "value"],
    },
    "Bash": {
        "command": ["cmd", "script", "code", "shell_command", "bash_command"],
    },
    "Edit": {
        "file_path": ["path", "filename", "file", "filepath", "target", "target_file"],
        "old_string": ["old", "search", "pattern", "find", "search_text"],
        "new_string": ["new", "replace", "replacement", "substitute", "replace_text"],
    },
    "Grep": {
        "pattern": ["search", "query", "text", "search_text", "find"],
    },
    "Glob": {
        "pattern": ["path", "search", "query", "glob_pattern", "file_pattern"],
    },
    "WebFetch": {
        "url": ["link", "uri", "address", "web_url"],
    },
    "WebSearch": {
        "query": ["search", "q", "search_query", "search_text"],
    },
}


# ============================================================================
# 污染检测模式
# ============================================================================

POLLUTION_MARKERS = [
    # 格式标记
    "<|dsml|", "</|dsml|", "<![cdata[", "]]>",
    "<tool_calls>", "</tool_calls>",
    "<invoke", "</invoke>", "<parameter", "</parameter>",
    "qnml|", "|qnml",
    "function.name:", "function.arguments:",

    # 自然语言（中文）
    "我将", "我会", "我先", "首先", "现在", "接下来", "然后", "继续执行",
    "开始执行", "让我", "我需要", "目录已创建",

    # 自然语言（英文）
    "i will", "i'll", "i am going to", "now i", "next i", "first i",
    "let me", "i need to", "i'm going to", "i should",
]


# ============================================================================
# 工具名称规范化
# ============================================================================

def canonicalize_tool_name(name: str, available_tools: List[str]) -> Optional[str]:
    """
    规范化工具名称，支持：
    1. 精确匹配（忽略大小写）
    2. 别名映射
    3. 模糊匹配（移除特殊字符）

    参考 qwen2API 的实现
    """
    if not name or not isinstance(name, str):
        return None

    name = name.strip()
    if not name:
        return None

    # 创建工具名称的小写映射
    available_lower = {tool.lower(): tool for tool in available_tools}

    # 1. 精确匹配（忽略大小写）
    if name.lower() in available_lower:
        return available_lower[name.lower()]

    # 2. 检查别名映射
    canonical = TOOL_ALIASES.get(name.lower())
    if canonical and canonical.lower() in available_lower:
        return available_lower[canonical.lower()]

    # 3. 模糊匹配（移除特殊字符和空格）
    normalized_name = _normalize_identifier(name)
    for tool in available_tools:
        if _normalize_identifier(tool) == normalized_name:
            return tool

    return None


def _normalize_identifier(text: str) -> str:
    """移除特殊字符，只保留字母和数字"""
    return re.sub(r'[^a-z0-9]+', '', text.lower())


# ============================================================================
# 参数名称修复
# ============================================================================

def coerce_tool_parameters(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    修复参数名称，将常见的别名转换为标准名称

    参考 qwen2API 的 CoerceToolInput 实现
    """
    if not isinstance(params, dict):
        return params

    # 获取该工具的参数别名映射
    aliases = PARAMETER_ALIASES.get(tool_name, )
    if not aliases:
        return params

    fixed = params.copy()

    # 对每个标准参数名，检查是否存在别名
    for canonical, alias_list in aliases.items():
        if canonical in fixed:
            continue  # 标准名称已存在，不需要修复

        # 查找第一个存在的别名
        for alias in alias_list:
            if alias in fixed:
                fixed[canonical] = fixed.pop(alias)
                break

    return fixed


# ============================================================================
# Schema 驱动的类型转换
# ============================================================================

def coerce_by_schema(
    tool_name: str,
    params: Dict[str, Any],
    tools: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    根据工具 Schema 转换参数类型

    参考 qwen2API 的 coerceToolInputBySchema 实现
    """
    if not isinstance(params, dict):
        return params

    # 获取工具 Schema
    schema = _get_tool_schema(tool_name, tools)
    if not schema:
        return params

    properties = schema.get("properties", {})
    if not properties:
        return params

    fixed = params.copy()

    # 对每个参数，根据 Schema 进行类型转换
    for param_name, param_value in fixed.items():
        if param_name not in properties:
            continue

        param_schema = properties[param_name]
        if not isinstance(param_schema, dict):
            continue

        fixed[param_name] = _coerce_value_by_schema(param_value, param_schema)

    return fixed


def _coerce_value_by_schema(value: Any, schema: Dict[str, Any]) -> Any:
    """根据 Schema 转换单个值的类型"""
    param_type = schema.get("type")

    # 如果 Schema 要求 array，但值是对象，包装成数组
    if param_type == "array":
        if isinstance(value, dict):
            return [value]
        elif isinstance(value, str):
            # 尝试解析为 JSON 数组
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict):
                    return [parsed]
            except (json.JSONDecodeError, ValueError):
                pass

    # 如果 Schema 要求 object，但值是字符串，尝试解析
    elif param_type == "object":
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass

    # 如果 Schema 要求 string，但值是其他类型
    elif param_type == "string":
        if not isinstance(value, str):
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            else:
                return str(value)

    return value


def _get_tool_schema(tool_name: str, tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """获取指定工具的 Schema"""
    for tool in tools:
        # 支持两种格式：
        # 1. {"name": "Tool", "parameters": {...}}
        # 2. {"function": {"name": "Tool", "parameters": {...}}}

        name = tool.get("name")
        schema = tool.get("parameters")

        if "function" in tool and isinstance(tool["function"], dict):
            fn = tool["function"]
            if not name:
                name = fn.get("name")
            if not schema:
                schema = fn.get("parameters")

        if name == tool_name and isinstance(schema, dict):
            return schema

    return None


# ============================================================================
# 参数污染检测
# ============================================================================

def is_parameter_polluted(param_name: str, param_value: Any) -> bool:
    """
    检测参数值是否被污染（包含格式标记或自然语言）

    参考 qwen2API 的 pathLikeArgLooksPolluted 实现
    """
    if not isinstance(param_value, str):
        return False

    value = param_value.strip()
    if not value:
        return False

    # 检查是否包含空字符
    if '\x00' in value:
        return True

    # 检查是否包含换行、尖括号等
    if any(char in value for char in '\r\n<>'):
        return True

    value_lower = value.lower()

    # 检查污染标记
    for marker in POLLUTION_MARKERS:
        if marker in value_lower:
            return True

    return False


def filter_polluted_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """过滤掉被污染的参数"""
    if not isinstance(params, dict):
        return params

    filtered = {}
    for key, value in params.items():
        if not is_parameter_polluted(key, value):
            filtered[key] = value

    return filtered


# ============================================================================
# 综合规范化函数
# ============================================================================

def normalize_tool_call(
    tool_name: str,
    parameters: Dict[str, Any],
    available_tools: List[str],
    tools_schema: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    综合规范化工具调用

    返回：{"name": str, "parameters": dict} 或 None（如果无效）
    """
    # 1. 规范化工具名称
    canonical_name = canonicalize_tool_name(tool_name, available_tools)
    if not canonical_name:
        return None

    # 2. 修复参数名称
    fixed_params = coerce_tool_parameters(canonical_name, parameters)

    # 3. Schema 驱动的类型转换
    typed_params = coerce_by_schema(canonical_name, fixed_params, tools_schema)

    # 4. 过滤污染参数
    clean_params = filter_polluted_parameters(typed_params)

    return {
        "name": canonical_name,
        "parameters": clean_params
    }


# ============================================================================
# 辅助函数
# ============================================================================

def deduplicate_tool_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    去重工具调用（基于工具名 + 参数哈希）

    参考 qwen2API 的 DedupeToolCalls 实现
    """
    seen: Set[str] = set()
    unique_calls = []

    for call in calls:
        if not isinstance(call, dict):
            continue

        name = call.get("function", {}).get("name", "")
        arguments = call.get("function", {}).get("arguments", "{}")

        if not name:
            continue

        # 创建唯一键：工具名 + 参数 JSON
        key = name.lower() + "\x00" + arguments

        if key not in seen:
            seen.add(key)
            unique_calls.append(call)

    return unique_calls
