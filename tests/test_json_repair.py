"""测试 JSON 修复功能"""

import pytest
from app.api.toolcall import _repair_json, _decode_param_value


class TestJSONRepair:
    """测试 JSON 修复机制"""

    def test_repair_valid_json(self):
        """有效的 JSON 应该直接返回"""
        text = '{"city": "Beijing", "unit": "celsius"}'
        result = _repair_json(text)
        assert result == text

    def test_repair_single_quotes(self):
        """修复单引号 JSON"""
        text = "{'city': 'Beijing', 'unit': 'celsius'}"
        result = _repair_json(text)
        assert '"city"' in result
        assert '"Beijing"' in result
        assert '"celsius"' in result
        # 验证是有效的 JSON
        import json
        parsed = json.loads(result)
        assert parsed["city"] == "Beijing"
        assert parsed["unit"] == "celsius"

    def test_repair_trailing_comma_object(self):
        """修复对象中的尾部逗号"""
        text = '{"city": "Beijing", "unit": "celsius",}'
        result = _repair_json(text)
        assert result == '{"city": "Beijing", "unit": "celsius"}'

    def test_repair_trailing_comma_array(self):
        """修复数组中的尾部逗号"""
        text = '["item1", "item2",]'
        result = _repair_json(text)
        assert result == '["item1", "item2"]'

    def test_repair_combined(self):
        """修复单引号和尾部逗号组合"""
        text = "{'city': 'Beijing', 'days': 3,}"
        result = _repair_json(text)
        import json
        parsed = json.loads(result)
        assert parsed["city"] == "Beijing"
        assert parsed["days"] == 3

    def test_repair_empty_string(self):
        """空字符串应该返回空"""
        assert _repair_json("") == ""
        assert _repair_json("   ") == ""

    def test_repair_invalid_json(self):
        """无法修复的 JSON 返回空字符串"""
        text = "{invalid json without quotes}"
        result = _repair_json(text)
        assert result == ""

    def test_repair_nested_object(self):
        """修复嵌套对象"""
        text = "{'user': {'name': 'Alice', 'age': 30,}, 'active': true,}"
        result = _repair_json(text)
        import json
        parsed = json.loads(result)
        assert parsed["user"]["name"] == "Alice"
        assert parsed["user"]["age"] == 30
        assert parsed["active"] is True


class TestDecodeParamValueWithRepair:
    """测试参数解码中的 JSON 修复"""

    def test_decode_with_single_quotes_in_cdata(self):
        """CDATA 中的单引号 JSON 应该被修复"""
        raw = "<![CDATA[{'city': 'Shanghai'}]]>"
        result = _decode_param_value(raw)
        assert isinstance(result, dict)
        assert result["city"] == "Shanghai"

    def test_decode_with_trailing_comma_in_cdata(self):
        """CDATA 中的尾部逗号应该被修复"""
        raw = '<![CDATA[{"city": "Beijing", "days": 7,}]]>'
        result = _decode_param_value(raw)
        assert isinstance(result, dict)
        assert result["city"] == "Beijing"
        assert result["days"] == 7

    def test_decode_plain_json_with_single_quotes(self):
        """普通 JSON（无 CDATA）的单引号应该被修复"""
        raw = "{'temperature': 25}"
        result = _decode_param_value(raw)
        assert isinstance(result, dict)
        assert result["temperature"] == 25

    def test_decode_plain_json_with_trailing_comma(self):
        """普通 JSON（无 CDATA）的尾部逗号应该被修复"""
        raw = '{"status": "ok",}'
        result = _decode_param_value(raw)
        assert isinstance(result, dict)
        assert result["status"] == "ok"

    def test_decode_array_with_single_quotes(self):
        """数组中的单引号应该被修复"""
        raw = "['item1', 'item2']"
        result = _decode_param_value(raw)
        assert isinstance(result, list)
        assert result == ["item1", "item2"]

    def test_decode_normal_values_unchanged(self):
        """正常值应该不受影响"""
        # 数字
        assert _decode_param_value("123") == 123
        assert _decode_param_value("3.14") == 3.14

        # 布尔值
        assert _decode_param_value("true") is True
        assert _decode_param_value("false") is False

        # Null
        assert _decode_param_value("null") is None

        # 字符串（无 CDATA）
        assert _decode_param_value("plain text") == "plain text"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
