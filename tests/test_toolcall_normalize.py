"""测试工具调用规范化功能"""

import pytest
import json
from app.api.toolcall_normalize import (
    canonicalize_tool_name,
    coerce_tool_parameters,
    coerce_by_schema,
    is_parameter_polluted,
    filter_polluted_parameters,
    normalize_tool_call,
    deduplicate_tool_calls,
)


class TestToolNameCanonicalization:
    """测试工具名称规范化"""

    def test_exact_match(self):
        """测试精确匹配"""
        available = ["Read", "Write", "Bash"]
        assert canonicalize_tool_name("Read", available) == "Read"
        assert canonicalize_tool_name("read", available) == "Read"
        assert canonicalize_tool_name("READ", available) == "Read"

    def test_alias_mapping(self):
        """测试别名映射"""
        available = ["Bash", "Read", "Write"]
        assert canonicalize_tool_name("shell", available) == "Bash"
        assert canonicalize_tool_name("shell_run", available) == "Bash"
        assert canonicalize_tool_name("read_file", available) == "Read"
        assert canonicalize_tool_name("fs_open_file", available) == "Read"
        assert canonicalize_tool_name("create_file", available) == "Write"

    def test_fuzzy_match(self):
        """测试模糊匹配（移除特殊字符）"""
        available = ["ReadFile", "WriteFile"]
        assert canonicalize_tool_name("read_file", available) == "ReadFile"
        assert canonicalize_tool_name("read-file", available) == "ReadFile"
        assert canonicalize_tool_name("Read File", available) == "ReadFile"

    def test_unknown_tool(self):
        """测试未知工具"""
        available = ["Read", "Write"]
        assert canonicalize_tool_name("UnknownTool", available) is None
        assert canonicalize_tool_name("", available) is None
        assert canonicalize_tool_name(None, available) is None


class TestParameterCoercion:
    """测试参数名称修复"""

    def test_read_parameter_aliases(self):
        """测试 Read 工具的参数别名"""
        params = {"path": "/tmp/test.txt"}
        fixed = coerce_tool_parameters("Read", params)
        assert fixed["file_path"] == "/tmp/test.txt"
        assert "path" not in fixed

    def test_write_parameter_aliases(self):
        """测试 Write 工具的参数别名"""
        params = {"path": "/tmp/test.txt", "text": "Hello"}
        fixed = coerce_tool_parameters("Write", params)
        assert fixed["file_path"] == "/tmp/test.txt"
        assert fixed["content"] == "Hello"
        assert "path" not in fixed
        assert "text" not in fixed

    def test_bash_parameter_aliases(self):
        """测试 Bash 工具的参数别名"""
        params = {"cmd": "ls -la"}
        fixed = coerce_tool_parameters("Bash", params)
        assert fixed["command"] == "ls -la"
        assert "cmd" not in fixed

    def test_canonical_name_preserved(self):
        """测试标准名称已存在时不修改"""
        params = {"file_path": "/tmp/test.txt", "path": "/tmp/other.txt"}
        fixed = coerce_tool_parameters("Read", params)
        # 标准名称已存在，不应被别名覆盖
        assert fixed["file_path"] == "/tmp/test.txt"

    def test_unknown_tool(self):
        """测试未知工具不修改参数"""
        params = {"path": "/tmp/test.txt"}
        fixed = coerce_tool_parameters("UnknownTool", params)
        assert fixed == params


class TestSchemaCoercion:
    """测试 Schema 驱动的类型转换"""

    def test_string_to_array(self):
        """测试字符串转数组"""
        tools = [{
            "name": "TestTool",
            "parameters": {
                "properties": {
                    "items": {"type": "array"}
                }
            }
        }]

        # 字符串 JSON 转数组
        params = {"items": '["a", "b", "c"]'}
        fixed = coerce_by_schema("TestTool", params, tools)
        assert fixed["items"] == ["a", "b", "c"]

    def test_object_to_array(self):
        """测试对象包装成数组"""
        tools = [{
            "name": "TestTool",
            "parameters": {
                "properties": {
                    "items": {"type": "array"}
                }
            }
        }]

        params = {"items": {"key": "value"}}
        fixed = coerce_by_schema("TestTool", params, tools)
        assert fixed["items"] == [{"key": "value"}]

    def test_string_to_object(self):
        """测试字符串转对象"""
        tools = [{
            "name": "TestTool",
            "parameters": {
                "properties": {
                    "config": {"type": "object"}
                }
            }
        }]

        params = {"config": '{"key": "value"}'}
        fixed = coerce_by_schema("TestTool", params, tools)
        assert fixed["config"] == {"key": "value"}

    def test_no_schema(self):
        """测试无 Schema 时不修改"""
        tools = []
        params = {"key": "value"}
        fixed = coerce_by_schema("TestTool", params, tools)
        assert fixed == params


class TestPollutionDetection:
    """测试参数污染检测"""

    def test_format_marker_pollution(self):
        """测试格式标记污染"""
        assert is_parameter_polluted("path", "<|DSML|invoke name='Read'>")
        assert is_parameter_polluted("path", "<![CDATA[/tmp/test]]>")
        assert is_parameter_polluted("path", "</tool_calls>")

    def test_natural_language_pollution_chinese(self):
        """测试中文自然语言污染"""
        assert is_parameter_polluted("command", "我将执行 ls 命令")
        assert is_parameter_polluted("command", "首先我会列出文件")
        assert is_parameter_polluted("command", "现在开始执行")

    def test_natural_language_pollution_english(self):
        """测试英文自然语言污染"""
        assert is_parameter_polluted("command", "I will execute ls")
        assert is_parameter_polluted("command", "Let me list the files")
        assert is_parameter_polluted("command", "First I need to")

    def test_clean_parameters(self):
        """测试干净的参数"""
        assert not is_parameter_polluted("path", "/tmp/test.txt")
        assert not is_parameter_polluted("command", "ls -la")
        assert not is_parameter_polluted("content", "Hello World")

    def test_filter_polluted_parameters(self):
        """测试过滤污染参数"""
        params = {
            "path": "/tmp/test.txt",  # 干净
            "command": "我将执行 ls",  # 污染
            "content": "Hello"  # 干净
        }
        filtered = filter_polluted_parameters(params)
        assert "path" in filtered
        assert "command" not in filtered
        assert "content" in filtered


class TestNormalizeToolCall:
    """测试综合规范化"""

    def test_full_normalization(self):
        """测试完整的规范化流程"""
        available_tools = ["Read", "Write", "Bash"]
        tools_schema = [{
            "name": "Read",
            "parameters": {
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }]

        # 输入：错误的工具名 + 错误的参数名
        result = normalize_tool_call(
            tool_name="read_file",  # 别名
            parameters={"path": "/tmp/test.txt"},  # 别名
            available_tools=available_tools,
            tools_schema=tools_schema
        )

        assert result is not None
        assert result["name"] == "Read"  # 规范化后的名称
        assert result["parameters"]["file_path"] == "/tmp/test.txt"  # 规范化后的参数名

    def test_unknown_tool_returns_none(self):
        """测试未知工具返回 None"""
        result = normalize_tool_call(
            tool_name="UnknownTool",
            parameters={},
            available_tools=["Read", "Write"],
            tools_schema=[]
        )
        assert result is None

    def test_pollution_filtering(self):
        """测试污染参数被过滤"""
        result = normalize_tool_call(
            tool_name="Bash",
            parameters={"command": "我将执行 ls 命令"},
            available_tools=["Bash"],
            tools_schema=[]
        )

        assert result is not None
        # 污染的参数应该被移除
        assert "command" not in result["parameters"]


class TestDeduplication:
    """测试去重功能"""

    def test_deduplicate_identical_calls(self):
        """测试去重相同的工具调用"""
        calls = [
            {
                "function": {
                    "name": "Read",
                    "arguments": '{"file_path": "/tmp/test.txt"}'
                }
            },
            {
                "function": {
                    "name": "Read",
                    "arguments": '{"file_path": "/tmp/test.txt"}'
                }
            },
        ]

        unique = deduplicate_tool_calls(calls)
        assert len(unique) == 1

    def test_deduplicate_different_calls(self):
        """测试不去重不同的工具调用"""
        calls = [
            {
                "function": {
                    "name": "Read",
                    "arguments": '{"file_path": "/tmp/test1.txt"}'
                }
            },
            {
                "function": {
                    "name": "Read",
                    "arguments": '{"file_path": "/tmp/test2.txt"}'
                }
            },
        ]

        unique = deduplicate_tool_calls(calls)
        assert len(unique) == 2

    def test_deduplicate_case_insensitive(self):
        """测试大小写不敏感的去重"""
        calls = [
            {
                "function": {
                    "name": "Read",
                    "arguments": '{"file_path": "/tmp/test.txt"}'
                }
            },
            {
                "function": {
                    "name": "read",
                    "arguments": '{"file_path": "/tmp/test.txt"}'
                }
            },
        ]

        unique = deduplicate_tool_calls(calls)
        assert len(unique) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
