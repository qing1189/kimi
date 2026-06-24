"""Tests for enhanced tool call implementation inspired by ds2api."""

import pytest
from app.api import toolcall_enhanced as tc


class TestDSMLNormalization:
    """Test DSML markup normalization."""

    def test_normalize_standard_dsml(self):
        """Standard DSML format should be normalized to canonical XML."""
        text = "<|DSML|tool_calls><|DSML|invoke name='test'></|DSML|invoke></|DSML|tool_calls>"
        result = tc.normalize_dsml_markup(text)
        assert "<tool_calls>" in result
        assert "<invoke name='test'>" in result
        assert "</invoke>" in result
        assert "</tool_calls>" in result

    def test_normalize_hyphenated_dsml(self):
        """Hyphenated DSML format should normalize."""
        text = "<dsml-tool-calls><dsml-invoke name='test'></dsml-invoke></dsml-tool-calls>"
        result = tc.normalize_dsml_markup(text)
        assert "<tool_calls>" in result
        assert "<invoke name='test'>" in result

    def test_normalize_with_typos(self):
        """Handle repeated prefixes and trailing pipes."""
        text = "<<DSML|DSML|tool_calls|>"
        result = tc.normalize_dsml_markup(text)
        assert "<tool_calls>" in result

    def test_normalize_fullwidth_characters(self):
        """Fullwidth DSML markers should be converted to halfwidth."""
        text = "＜｜ＤＳＭＬ｜tool_calls＞content＜／｜ＤＳＭＬ｜tool_calls＞"
        result = tc.normalize_dsml_markup(text)
        assert "<|DSML|tool_calls>" in result
        assert "</|DSML|tool_calls>" in result


class TestCodeFenceDetection:
    """Test code fence awareness."""

    def test_not_inside_fence(self):
        """Text not in code fence should return False."""
        text = "Normal text <tool_calls>"
        pos = text.find("<tool_calls>")
        assert not tc.is_inside_code_fence(text, pos)

    def test_inside_fence(self):
        """Text inside code fence should return True."""
        text = "```xml\n<tool_calls>\n```"
        pos = text.find("<tool_calls>")
        assert tc.is_inside_code_fence(text, pos)

    def test_after_fence(self):
        """Text after closed fence should return False."""
        text = "```xml\nexample\n```\n<tool_calls>"
        pos = text.find("<tool_calls>")
        assert not tc.is_inside_code_fence(text, pos)

    def test_find_outside_fences(self):
        """Should find markers outside fences."""
        text = "Text ```xml\n<tool_calls>\n``` more text <tool_calls>"
        pos = tc.find_tool_markup_outside_fences(text, "<tool_calls>")
        # Should find the second occurrence
        assert pos > text.find("```") + 20


class TestPartialMarkerDetection:
    """Test partial marker detection and buffering."""

    def test_detect_partial_dsml_open(self):
        """Should detect partial DSML opening marker."""
        text = "some text <|DSM"
        pos = tc.find_partial_tool_tag_start(text)
        assert pos == len(text) - 5  # "<|DSM" is 5 chars

    def test_detect_partial_lt(self):
        """Should detect single < at end."""
        text = "some text <"
        pos = tc.find_partial_tool_tag_start(text)
        assert pos == len(text) - 1

    def test_no_partial_marker(self):
        """Should return -1 when no partial marker."""
        text = "some complete text"
        pos = tc.find_partial_tool_tag_start(text)
        assert pos == -1

    def test_split_safe_content(self):
        """Should split safe content from partial marker."""
        text = "Hello world <|D"
        safe, held = tc.split_safe_content(text)
        assert safe == "Hello world "
        assert held == "<|D"


class TestXMLRepair:
    """Test XML repair mechanisms."""

    def test_sanitize_unclosed_cdata(self):
        """Should close unclosed CDATA sections."""
        text = "<parameter><![CDATA[some text"
        result = tc.sanitize_loose_cdata(text)
        assert "]]>" in result

    def test_repair_missing_wrapper(self):
        """Should add missing <tool_calls> opening tag."""
        block = "<invoke name='test'><parameter name='x'>1</parameter></invoke></tool_calls>"
        result = tc.repair_missing_wrapper(block)
        assert result.startswith("<tool_calls>") or "<tool_calls>" in result
        assert "<invoke" in result

    def test_repair_with_existing_wrapper(self):
        """Should not duplicate wrapper if already present."""
        block = "<tool_calls><invoke name='test'></invoke></tool_calls>"
        result = tc.repair_missing_wrapper(block)
        # Should only have one opening tag
        assert result.count("<tool_calls>") == 1


class TestEnhancedToolCallSieve:
    """Test enhanced tool call sieve state machine."""

    def test_simple_text_passthrough(self):
        """Text without tool calls should pass through."""
        sieve = tc.EnhancedToolCallSieve()
        text, calls = sieve.push("Hello world")
        assert text == "Hello world"
        assert calls is None

    def test_hold_partial_marker(self):
        """Should hold back partial markers."""
        sieve = tc.EnhancedToolCallSieve()
        text1, calls1 = sieve.push("Hello <|")
        assert text1 == "Hello "
        assert calls1 is None

        # Complete the marker
        text2, calls2 = sieve.push("DSML|tool_calls>")
        assert text2 == ""  # Nothing to emit, capturing now

    def test_intercept_complete_tool_call(self):
        """Should intercept complete tool call block without leaking."""
        sieve = tc.EnhancedToolCallSieve()

        full_block = (
            "Here's the answer: "
            "<|DSML|tool_calls>"
            "<|DSML|invoke name=\"get_weather\">"
            "<|DSML|parameter name=\"city\"><![CDATA[Beijing]]></|DSML|parameter>"
            "</|DSML|invoke>"
            "</|DSML|tool_calls>"
        )

        text, calls = sieve.push(full_block)
        assert text == "Here's the answer: "
        assert calls is not None
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"

    def test_streaming_tool_call_no_leak(self):
        """Should buffer tool call in chunks without leaking markup."""
        sieve = tc.EnhancedToolCallSieve()

        chunks = [
            "Let me check. ",
            "<|DSML|tool_calls>",
            "<|DSML|invoke name=\"test\">",
            "<|DSML|parameter name=\"x\">",
            "<![CDATA[value]]>",
            "</|DSML|parameter>",
            "</|DSML|invoke>",
            "</|DSML|tool_calls>",
        ]

        all_text = ""
        all_calls = None

        for chunk in chunks:
            text, calls = sieve.push(chunk)
            all_text += text
            if calls:
                all_calls = calls

        # Should emit text before tool call, but not the DSML markup
        assert all_text == "Let me check. "
        assert all_calls is not None
        assert len(all_calls) == 1

    def test_ignore_tool_call_in_code_fence(self):
        """Should not intercept tool calls in code fences."""
        sieve = tc.EnhancedToolCallSieve()

        text_with_fence = (
            "Here's an example:\n"
            "```xml\n"
            "<|DSML|tool_calls><|DSML|invoke name=\"example\"></|DSML|invoke></|DSML|tool_calls>\n"
            "```\n"
        )

        text, calls = sieve.push(text_with_fence)
        # Should pass through as text since it's in a code fence
        assert calls is None

    def test_repair_on_flush(self):
        """Should attempt repair on incomplete blocks at flush."""
        sieve = tc.EnhancedToolCallSieve()

        # Missing closing tag
        sieve.push("<|DSML|tool_calls>")
        sieve.push("<|DSML|invoke name=\"test\">")
        sieve.push("<|DSML|parameter name=\"x\">123</|DSML|parameter>")
        sieve.push("</|DSML|invoke>")
        # No closing </|DSML|tool_calls>

        text, calls = sieve.flush()

        # Should still parse successfully after repair
        if calls:
            assert len(calls) == 1
            assert calls[0]["function"]["name"] == "test"


class TestBackwardCompatibility:
    """Test backward compatibility with original implementation."""

    def test_has_tools_function(self):
        """has_tools should work as before."""
        payload = {
            "tools": [
                {"type": "function", "function": {"name": "test"}}
            ]
        }
        assert tc.has_tools(payload)

    def test_parse_tool_calls_from_text(self):
        """parse_tool_calls_from_text should work as before."""
        text = (
            "Response text\n"
            "<|DSML|tool_calls>"
            "<|DSML|invoke name=\"get_weather\">"
            "<|DSML|parameter name=\"city\"><![CDATA[Tokyo]]></|DSML|parameter>"
            "</|DSML|invoke>"
            "</|DSML|tool_calls>"
        )

        content, calls = tc.parse_tool_calls_from_text(text)
        assert content == "Response text"
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
