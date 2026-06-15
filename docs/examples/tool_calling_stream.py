"""
Kimi2API 工具调用示例 - 流式输出

展示如何在流式模式下处理工具调用。
"""

import json
from openai import OpenAI


client = OpenAI(
    api_key="your-kimi2api-key",
    base_url="http://localhost:8000/v1"
)


# 简单的计算器工具
def calculate(expression: str) -> dict:
    """安全的数学表达式计算"""
    try:
        # 只允许基本数学运算
        allowed_chars = set("0123456789+-*/()., ")
        if not all(c in allowed_chars for c in expression):
            return {"error": "表达式包含非法字符"}

        result = eval(expression)
        return {"result": result, "expression": expression}
    except Exception as e:
        return {"error": str(e)}


tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学计算，支持加减乘除和括号",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如：(123 + 456) * 2"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]


def stream_with_tool_calls(user_message: str):
    """流式输出 + 工具调用"""
    print(f"👤 用户: {user_message}\n")
    print("🤖 助手: ", end="", flush=True)

    messages = [{"role": "user", "content": user_message}]

    # 用于累积流式数据
    accumulated_tool_calls = {}
    current_content = ""

    # 发起流式请求
    stream = client.chat.completions.create(
        model="kimi-k2.6",
        messages=messages,
        tools=tools,
        stream=True
    )

    for chunk in stream:
        delta = chunk.choices[0].delta

        # 处理文本内容
        if delta.content:
            print(delta.content, end="", flush=True)
            current_content += delta.content

        # 处理工具调用（流式累积）
        if delta.tool_calls:
            for tool_call_chunk in delta.tool_calls:
                index = tool_call_chunk.index

                # 初始化这个工具调用的累积器
                if index not in accumulated_tool_calls:
                    accumulated_tool_calls[index] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""}
                    }

                # 累积 ID
                if tool_call_chunk.id:
                    accumulated_tool_calls[index]["id"] = tool_call_chunk.id

                # 累积函数名
                if tool_call_chunk.function.name:
                    accumulated_tool_calls[index]["function"]["name"] = tool_call_chunk.function.name

                # 累积参数
                if tool_call_chunk.function.arguments:
                    accumulated_tool_calls[index]["function"]["arguments"] += tool_call_chunk.function.arguments

    print("\n")  # 换行

    # 如果有工具调用
    if accumulated_tool_calls:
        print("\n📞 检测到工具调用:\n")

        for tool_call in accumulated_tool_calls.values():
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])

            print(f"  工具: {function_name}")
            print(f"  参数: {json.dumps(function_args, ensure_ascii=False)}")

            # 执行工具
            if function_name == "calculate":
                result = calculate(**function_args)
                print(f"  结果: {json.dumps(result, ensure_ascii=False)}\n")

                # 构建完整的消息历史
                messages.append({
                    "role": "assistant",
                    "content": current_content,
                    "tool_calls": [
                        {
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": json.dumps(function_args, ensure_ascii=False)
                            }
                        }
                    ]
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False)
                })

        # 再次请求，获取最终答案
        print("🤖 最终回复: ", end="", flush=True)

        final_stream = client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=tools,
            stream=True
        )

        for chunk in final_stream:
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end="", flush=True)

        print("\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Kimi2API 工具调用示例 - 流式输出")
    print("=" * 60)
    print()

    # 示例 1: 简单计算
    stream_with_tool_calls("计算 123 + 456")

    print("\n" + "=" * 60 + "\n")

    # 示例 2: 复杂表达式
    stream_with_tool_calls("帮我算一下 (100 + 200) * 3 - 50")

    print("\n" + "=" * 60 + "\n")

    # 示例 3: 多步计算
    stream_with_tool_calls("先算 10 * 20，然后把结果除以 4")
