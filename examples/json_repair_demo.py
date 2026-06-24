#!/usr/bin/env python3
"""
JSON 修复功能演示

展示新增的 JSON 修复机制如何处理模型输出的常见 JSON 格式错误
"""

from app.api.toolcall import _repair_json, parse_tool_calls_from_text


def demo_single_quotes():
    """示例 1: 修复单引号 JSON"""
    print("=" * 70)
    print("示例 1: 修复单引号 JSON")
    print("=" * 70)

    # 模型可能输出单引号格式的 JSON
    malformed = "{'city': 'Beijing', 'days': 3}"
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复后: {repaired}")

    import json
    parsed = json.loads(repaired)
    print(f"解析结果: {parsed}")
    print("✅ 成功修复并解析")


def demo_trailing_comma():
    """示例 2: 修复尾部逗号"""
    print("\n" + "=" * 70)
    print("示例 2: 修复尾部逗号")
    print("=" * 70)

    malformed = '{"location": "Shanghai", "temperature": 22,}'
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复后: {repaired}")

    import json
    parsed = json.loads(repaired)
    print(f"解析结果: {parsed}")
    print("✅ 成功修复并解析")


def demo_combined_errors():
    """示例 3: 修复组合错误（单引号 + 尾部逗号）"""
    print("\n" + "=" * 70)
    print("示例 3: 修复组合错误")
    print("=" * 70)

    malformed = "{'name': 'Alice', 'age': 30, 'active': true,}"
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复后: {repaired}")

    import json
    parsed = json.loads(repaired)
    print(f"解析结果: {parsed}")
    print("✅ 成功修复并解析")


def demo_nested_object():
    """示例 4: 修复嵌套对象"""
    print("\n" + "=" * 70)
    print("示例 4: 修复嵌套对象")
    print("=" * 70)

    malformed = "{'user': {'name': 'Bob', 'email': 'bob@example.com',}, 'status': 'active',}"
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复后: {repaired}")

    import json
    parsed = json.loads(repaired)
    print(f"解析结果: {parsed}")
    print(f"  用户名: {parsed['user']['name']}")
    print(f"  邮箱: {parsed['user']['email']}")
    print("✅ 成功修复并解析")


def demo_array_repair():
    """示例 5: 修复数组格式"""
    print("\n" + "=" * 70)
    print("示例 5: 修复数组格式")
    print("=" * 70)

    malformed = "['item1', 'item2', 'item3',]"
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复后: {repaired}")

    import json
    parsed = json.loads(repaired)
    print(f"解析结果: {parsed}")
    print("✅ 成功修复并解析")


def demo_real_tool_call():
    """示例 6: 真实工具调用场景"""
    print("\n" + "=" * 70)
    print("示例 6: 真实工具调用场景（模型输出错误 JSON）")
    print("=" * 70)

    # 模拟模型输出了包含错误 JSON 的工具调用
    model_output = """
    让我帮你查询天气。

    <|DSML|tool_calls>
      <|DSML|invoke name="get_weather">
        <|DSML|parameter name="city"><![CDATA[{'name': 'Beijing', 'country': 'China',}]]></|DSML|parameter>
        <|DSML|parameter name="days">7</|DSML|parameter>
      </|DSML|invoke>
    </|DSML|tool_calls>
    """

    print("\n模型输出（包含错误 JSON）:")
    print(model_output)

    # 解析工具调用
    content, calls = parse_tool_calls_from_text(model_output)

    print("\n解析结果:")
    print(f"  文本内容: {content.strip()}")
    print(f"  工具调用数: {len(calls)}")

    if calls:
        call = calls[0]
        print(f"\n  工具名称: {call['function']['name']}")

        import json
        args = json.loads(call['function']['arguments'])
        print(f"  参数:")
        for key, value in args.items():
            print(f"    {key}: {value}")

        print("\n✅ JSON 修复机制自动处理了参数中的格式错误")


def demo_failure_case():
    """示例 7: 无法修复的情况"""
    print("\n" + "=" * 70)
    print("示例 7: 无法修复的 JSON")
    print("=" * 70)

    malformed = "{totally broken json without proper structure"
    print(f"\n原始（错误）: {malformed}")

    repaired = _repair_json(malformed)
    print(f"修复结果: {repaired if repaired else '(空字符串 - 修复失败)'}")

    if not repaired:
        print("⚠️ 此 JSON 无法自动修复，将作为普通字符串处理")


def main():
    """运行所有演示"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + " JSON 修复功能演示 ".center(68) + "║")
    print("║" + " 参考 qingdeng888/kimi 项目实现 ".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")

    demos = [
        demo_single_quotes,
        demo_trailing_comma,
        demo_combined_errors,
        demo_nested_object,
        demo_array_repair,
        demo_real_tool_call,
        demo_failure_case,
    ]

    for demo in demos:
        demo()
        print()

    print("=" * 70)
    print("✅ 所有演示完成")
    print("=" * 70)
    print()
    print("💡 主要改进:")
    print("  1. 自动修复单引号 JSON（'key' → \"key\"）")
    print("  2. 自动移除尾部逗号（{\"a\": 1,} → {\"a\": 1}）")
    print("  3. 组合修复策略（同时处理多种错误）")
    print("  4. 无缝集成到工具调用解析流程")
    print()
    print("📈 预期收益:")
    print("  - 解析成功率提升 10-20%")
    print("  - 容忍模型常见 JSON 格式错误")
    print("  - 提升用户体验")
    print()


if __name__ == "__main__":
    main()
