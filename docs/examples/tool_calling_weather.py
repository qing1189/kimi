"""
Kimi2API 工具调用示例 - 天气查询助手

这个示例展示了如何使用工具调用功能构建一个简单的天气查询助手。
"""

import json
from openai import OpenAI


# 初始化客户端
client = OpenAI(
    api_key="your-kimi2api-key",  # 替换为你的 API Key
    base_url="http://localhost:8000/v1"
)


# 模拟天气数据库
WEATHER_DB = {
    "北京": {"temperature": 15, "condition": "晴天", "humidity": 45},
    "上海": {"temperature": 20, "condition": "多云", "humidity": 65},
    "广州": {"temperature": 28, "condition": "阴天", "humidity": 80},
    "深圳": {"temperature": 26, "condition": "小雨", "humidity": 75},
}


def get_weather(city: str, unit: str = "celsius") -> dict:
    """获取指定城市的天气信息（模拟）"""
    print(f"🔧 调用工具: get_weather(city={city}, unit={unit})")

    if city not in WEATHER_DB:
        return {"error": f"未找到城市 {city} 的天气数据"}

    weather = WEATHER_DB[city].copy()

    # 如果需要华氏度，转换温度
    if unit == "fahrenheit":
        weather["temperature"] = weather["temperature"] * 9/5 + 32
        weather["unit"] = "°F"
    else:
        weather["unit"] = "°C"

    return weather


def get_weather_recommendation(temperature: int, condition: str) -> dict:
    """根据天气提供穿衣建议（模拟）"""
    print(f"🔧 调用工具: get_weather_recommendation(temperature={temperature}, condition={condition})")

    # 温度建议
    if temperature < 10:
        temp_advice = "建议穿羽绒服或厚外套"
    elif temperature < 20:
        temp_advice = "建议穿外套或卫衣"
    elif temperature < 25:
        temp_advice = "建议穿长袖衬衫或薄外套"
    else:
        temp_advice = "建议穿短袖或轻便衣物"

    # 天气建议
    if "雨" in condition:
        weather_advice = "记得带伞"
    elif "雪" in condition:
        weather_advice = "注意防滑保暖"
    else:
        weather_advice = "天气不错，适合出行"

    return {
        "temperature_advice": temp_advice,
        "weather_advice": weather_advice
    }


# 定义可用工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气信息，包括温度、天气状况、湿度",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如：北京、上海、广州"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位，celsius 表示摄氏度，fahrenheit 表示华氏度",
                        "default": "celsius"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_recommendation",
            "description": "根据天气情况提供穿衣建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "temperature": {
                        "type": "integer",
                        "description": "温度（摄氏度）"
                    },
                    "condition": {
                        "type": "string",
                        "description": "天气状况，例如：晴天、多云、雨天"
                    }
                },
                "required": ["temperature", "condition"]
            }
        }
    }
]


# 工具函数映射
AVAILABLE_FUNCTIONS = {
    "get_weather": get_weather,
    "get_weather_recommendation": get_weather_recommendation,
}


def run_conversation(user_message: str, max_iterations: int = 5):
    """运行对话，自动处理工具调用"""
    print(f"\n👤 用户: {user_message}\n")

    messages = [{"role": "user", "content": user_message}]

    for iteration in range(max_iterations):
        print(f"--- 迭代 {iteration + 1} ---")

        # 调用模型
        response = client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        message = response.choices[0].message
        messages.append(message)

        # 如果有文本内容，显示
        if message.content:
            print(f"💭 助手思考: {message.content}")

        # 如果没有工具调用，返回最终结果
        if not message.tool_calls:
            print(f"\n🤖 最终回复: {message.content}\n")
            return message.content

        # 处理工具调用
        print(f"📞 需要调用 {len(message.tool_calls)} 个工具")

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            # 调用对应的函数
            if function_name in AVAILABLE_FUNCTIONS:
                function_to_call = AVAILABLE_FUNCTIONS[function_name]
                function_response = function_to_call(**function_args)
            else:
                function_response = {"error": f"未知函数: {function_name}"}

            print(f"✅ 工具返回: {json.dumps(function_response, ensure_ascii=False)}")

            # 添加工具结果到消息历史
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(function_response, ensure_ascii=False)
            })

        print()  # 空行分隔

    return "达到最大迭代次数，对话结束"


if __name__ == "__main__":
    print("=" * 60)
    print("Kimi2API 工具调用示例 - 天气查询助手")
    print("=" * 60)

    # 示例 1: 简单查询
    run_conversation("北京今天天气怎么样？")

    print("\n" + "=" * 60 + "\n")

    # 示例 2: 多步骤查询
    run_conversation("上海天气怎么样？我该穿什么衣服？")

    print("\n" + "=" * 60 + "\n")

    # 示例 3: 多城市查询
    run_conversation("比较一下北京和广州的天气")
