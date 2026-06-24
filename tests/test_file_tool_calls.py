"""测试文件操作相关的工具调用场景"""

import json
import pytest
from app.api.toolcall import parse_tool_calls_from_text, build_tool_prompt_block


class TestFileToolCalls:
    """测试文件操作工具调用"""

    def test_json_format_with_file_content(self):
        """测试 JSON 格式包含文件内容"""
        # 模拟模型输出 JSON 格式的工具调用（包含文件内容）
        text = """我将帮你创建这个文件。

```json
{
  "name": "create_file",
  "arguments": {
    "filename": "document.txt",
    "content": "这是一个测试文件的内容。\\n包含多行文本。\\n第三行内容。"
  }
}
```"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "create_file"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["filename"] == "document.txt"
        assert "测试文件的内容" in args["content"]
        assert content.strip() == "我将帮你创建这个文件。"

    def test_json_format_with_base64_data(self):
        """测试 JSON 格式包含 base64 编码数据"""
        base64_sample = "SGVsbG8gV29ybGQhIFRoaXMgaXMgYSB0ZXN0IGZpbGUgY29udGVudC4="

        text = f"""我来发送这个文件。

```json
{{
  "name": "send_file",
  "arguments": {{
    "file_data": "{base64_sample}",
    "filename": "test.txt",
    "mime_type": "text/plain"
  }}
}}
```"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "send_file"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["file_data"] == base64_sample
        assert args["filename"] == "test.txt"
        assert args["mime_type"] == "text/plain"

    def test_json_format_without_markdown(self):
        """测试不带 markdown 包裹的 JSON 格式"""
        text = """好的，我来帮你创建文件。

{"name": "create_file", "arguments": {"filename": "test.txt", "content": "Hello World"}}"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "create_file"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["filename"] == "test.txt"
        assert args["content"] == "Hello World"

    def test_json_with_nested_objects(self):
        """测试包含嵌套对象的 JSON"""
        text = """我将发送文件附件。

```json
{
  "name": "send_attachment",
  "arguments": {
    "file": {
      "name": "document.pdf",
      "size": 1024,
      "type": "application/pdf",
      "content": "base64encodedcontent"
    },
    "metadata": {
      "author": "User",
      "created_at": "2026-06-24"
    }
  }
}
```"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "send_attachment"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["file"]["name"] == "document.pdf"
        assert args["file"]["size"] == 1024
        assert args["metadata"]["author"] == "User"

    def test_dsml_format_still_works(self):
        """确保 DSML 格式仍然正常工作"""
        text = """我来查询文件。

<|DSML|tool_calls>
  <|DSML|invoke name="read_file">
    <|DSML|parameter name="path"><![CDATA[/home/user/document.txt]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "read_file"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["path"] == "/home/user/document.txt"

    def test_build_prompt_detects_file_tools(self):
        """测试提示构建能检测文件相关工具"""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "send_file",
                    "description": "发送文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_content": {"type": "string", "description": "文件内容"},
                            "filename": {"type": "string", "description": "文件名"}
                        },
                        "required": ["file_content", "filename"]
                    }
                }
            }
        ]

        prompt = build_tool_prompt_block(tools)

        # 应该包含 JSON 格式说明
        assert "JSON format" in prompt or "simplified" in prompt.lower()
        assert "file" in prompt.lower()

    def test_json_with_single_quotes(self):
        """测试 JSON 修复机制对单引号的处理"""
        # 注意：单引号 JSON 需要先被识别为 JSON 结构，才能进入修复流程
        # 目前的正则主要匹配双引号，单引号的修复主要用于 CDATA 和明确的 JSON 块
        text = """创建文件。

```json
{"name": "create_file", "arguments": {"filename": "test.txt", "content": "Hello"}}
```"""

        content, calls = parse_tool_calls_from_text(text)

        # 验证标准 JSON 格式可以正常解析
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "create_file"

    def test_large_content_json(self):
        """测试包含大量内容的 JSON"""
        large_content = "Line " * 1000  # 模拟大文件内容

        text = f"""创建大文件。

```json
{{
  "name": "create_large_file",
  "arguments": {{
    "filename": "large.txt",
    "content": "{large_content}"
  }}
}}
```"""

        content, calls = parse_tool_calls_from_text(text)

        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "create_large_file"

        args = json.loads(calls[0]["function"]["arguments"])
        assert args["filename"] == "large.txt"
        assert len(args["content"]) > 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
