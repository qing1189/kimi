# 工具调用 (Function Calling) 使用指南

本文档介绍如何在 Kimi2API 中使用 OpenAI 兼容的工具调用功能。

## 目录

- [概述](#概述)
- [快速开始](#快速开始)
- [工具定义](#工具定义)
- [调用示例](#调用示例)
- [高级用法](#高级用法)
- [故障排查](#故障排查)

---

## 概述

Kimi2API 通过 DSML 协议在 prompt 层实现了 OpenAI 格式的工具调用功能。支持：

- ✅ 流式和非流式输出
- ✅ 多工具并行调用
- ✅ `tool_choice` 参数（`auto`, `required`, `none`, `{"type": "function", "function": {"name": "..."}}`)
- ✅ 完整的参数类型支持（字符串、数字、布尔值、对象、数组）

**技术实现：**
- 将工具定义注入到系统 prompt 中
- 模型返回 DSML 格式的工具调用
- 自动解析并转换为 OpenAI 兼容格式
- 支持 JSON 格式回退解析

---

## 快速开始

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-kimi2api-key",
    base_url="http://localhost:8000/v1"
)

# 定义工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如：北京、上海"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# 发起请求
response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "北京今天天气怎么样？"}
    ],
    tools=tools,
    tool_choice="auto"  # 自动决定是否调用工具
)

# 检查是否有工具调用
message = response.choices[0].message
if message.tool_calls:
    for tool_call in message.tool_calls:
        print(f"工具: {tool_call.function.name}")
        print(f"参数: {tool_call.function.arguments}")
```

### JavaScript/TypeScript (OpenAI SDK)

```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  apiKey: 'your-kimi2api-key',
  baseURL: 'http://localhost:8000/v1'
});

const tools: OpenAI.ChatCompletionTool[] = [
  {
    type: 'function',
    function: {
      name: 'get_weather',
      description: '获取指定城市的天气信息',
      parameters: {
        type: 'object',
        properties: {
          city: {
            type: 'string',
            description: '城市名称'
          }
        },
        required: ['city']
      }
    }
  }
];

const response = await client.chat.completions.create({
  model: 'kimi-k2.6',
  messages: [
    { role: 'user', content: '北京今天天气怎么样？' }
  ],
  tools,
  tool_choice: 'auto'
});

const message = response.choices[0].message;
if (message.tool_calls) {
  for (const toolCall of message.tool_calls) {
    console.log(`工具: ${toolCall.function.name}`);
    console.log(`参数: ${toolCall.function.arguments}`);
  }
}
```

### cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-kimi2api-key" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [
      {"role": "user", "content": "北京今天天气怎么样？"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "获取指定城市的天气信息",
          "parameters": {
            "type": "object",
            "properties": {
              "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

---

## 工具定义

### 基本结构

```json
{
  "type": "function",
  "function": {
    "name": "工具名称",
    "description": "工具功能描述（会影响模型是否调用）",
    "parameters": {
      "type": "object",
      "properties": {
        "参数名": {
          "type": "参数类型",
          "description": "参数说明"
        }
      },
      "required": ["必需参数列表"]
    }
  }
}
```

### 参数类型

| 类型 | 描述 | 示例 |
|------|------|------|
| `string` | 字符串 | `"北京"` |
| `number` | 数字 | `25`, `3.14` |
| `integer` | 整数 | `10` |
| `boolean` | 布尔值 | `true`, `false` |
| `array` | 数组 | `["北京", "上海"]` |
| `object` | 对象 | `{"city": "北京"}` |

### 高级参数定义

```json
{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "城市名称"
    },
    "days": {
      "type": "integer",
      "description": "预报天数",
      "minimum": 1,
      "maximum": 7,
      "default": 3
    },
    "units": {
      "type": "string",
      "enum": ["metric", "imperial"],
      "description": "单位制"
    },
    "include_details": {
      "type": "boolean",
      "description": "是否包含详细信息"
    }
  },
  "required": ["city"]
}
```

---

## 调用示例

### 示例 1: 基础工具调用

```python
import json
from openai import OpenAI

client = OpenAI(
    api_key="your-key",
    base_url="http://localhost:8000/v1"
)

# 定义计算器工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学计算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如：2 + 2"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]

# 第一次请求
response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "计算 123 + 456"}
    ],
    tools=tools
)

message = response.choices[0].message
print(f"助手回复: {message.content}")

# 如果有工具调用
if message.tool_calls:
    tool_call = message.tool_calls[0]
    function_name = tool_call.function.name
    function_args = json.loads(tool_call.function.arguments)
    
    print(f"调用工具: {function_name}")
    print(f"参数: {function_args}")
    
    # 执行工具（这里简化处理）
    result = eval(function_args["expression"])
    
    # 第二次请求，返回工具结果
    response2 = client.chat.completions.create(
        model="kimi-k2.6",
        messages=[
            {"role": "user", "content": "计算 123 + 456"},
            message,  # 包含工具调用的消息
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result)
            }
        ],
        tools=tools
    )
    
    print(f"最终回复: {response2.choices[0].message.content}")
```

### 示例 2: 多工具并行调用

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "获取新闻",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"}
                },
                "required": ["category"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "北京天气怎么样？顺便给我看看科技新闻"}
    ],
    tools=tools
)

# 可能同时调用多个工具
for tool_call in response.choices[0].message.tool_calls or []:
    print(f"调用: {tool_call.function.name}")
```

### 示例 3: 强制调用工具

```python
# 强制模型调用某个工具
response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "北京"}
    ],
    tools=tools,
    tool_choice={
        "type": "function",
        "function": {"name": "get_weather"}
    }
)
```

### 示例 4: 流式输出

```python
stream = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "北京天气怎么样？"}
    ],
    tools=tools,
    stream=True
)

for chunk in stream:
    delta = chunk.choices[0].delta
    
    # 文本内容
    if delta.content:
        print(delta.content, end="")
    
    # 工具调用
    if delta.tool_calls:
        for tool_call in delta.tool_calls:
            if tool_call.function.name:
                print(f"\n调用工具: {tool_call.function.name}")
            if tool_call.function.arguments:
                print(tool_call.function.arguments, end="")
```

---

## 高级用法

### tool_choice 参数

| 值 | 行为 |
|----|------|
| `"auto"` (默认) | 模型自动决定是否调用工具 |
| `"none"` | 不调用工具，只返回文本 |
| `"required"` | 强制调用至少一个工具 |
| `{"type": "function", "function": {"name": "..."}}` | 强制调用指定工具 |

### 工具调用循环

```python
def run_conversation(user_message, tools, max_iterations=5):
    messages = [{"role": "user", "content": user_message}]
    
    for i in range(max_iterations):
        response = client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=tools
        )
        
        message = response.choices[0].message
        messages.append(message)
        
        # 如果没有工具调用，返回结果
        if not message.tool_calls:
            return message.content
        
        # 执行所有工具调用
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # 执行工具（实际应用中应该调用真实函数）
            result = execute_tool(function_name, function_args)
            
            # 添加工具结果
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })
    
    return "达到最大迭代次数"

# 使用
result = run_conversation("帮我查询北京天气并推荐穿衣建议", tools)
print(result)
```

---

## 故障排查

### 模型不调用工具

**可能原因：**
1. 工具 `description` 不够清晰
2. 用户问题与工具功能不匹配
3. `tool_choice` 设置为 `"none"`

**解决方案：**
```python
# 改进工具描述
{
    "name": "get_weather",
    "description": "获取指定城市的实时天气信息，包括温度、湿度、天气状况。当用户询问天气相关问题时使用此工具。"
}

# 或强制调用
tool_choice="required"
```

### 工具参数解析错误

**可能原因：**
- 参数定义不明确
- 缺少必需参数

**解决方案：**
```python
# 添加详细的参数描述和约束
"parameters": {
    "type": "object",
    "properties": {
        "city": {
            "type": "string",
            "description": "城市名称，必须是中文全称，例如：北京、上海、广州"
        },
        "date": {
            "type": "string",
            "description": "日期，格式：YYYY-MM-DD，例如：2024-01-01",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
    },
    "required": ["city", "date"]
}
```

### 流式输出不完整

**可能原因：**
- 网络中断
- 超时设置过短

**解决方案：**
```python
# 增加超时时间
client = OpenAI(
    api_key="your-key",
    base_url="http://localhost:8000/v1",
    timeout=120.0  # 增加到 120 秒
)
```

### 查看调试日志

启用 DEBUG 日志查看详细的工具调用过程：

```bash
# .env 文件
LOG_LEVEL=DEBUG

# 或启动时设置
LOG_LEVEL=DEBUG python run.py
```

查看日志中的工具调用信息：
```
DEBUG kimi2api.api.toolcall Parsed tool calls using strategy: dsml_format
DEBUG kimi2api.api.toolcall Tool call: get_weather({"city": "北京"})
```

---

## 性能优化建议

1. **批量工具调用**：尽量让模型一次返回多个工具调用，减少往返次数
2. **工具描述精简**：保持 description 简洁清晰，过长会消耗更多 token
3. **参数验证**：在工具执行前验证参数，避免无效调用
4. **缓存工具结果**：对相同参数的调用结果进行缓存
5. **并行执行**：多个独立工具调用可以并行执行

---

## 常见问题

### Q: 支持哪些模型？
A: 所有 Kimi 模型都支持工具调用，推荐使用 `kimi-k2.6` 或更新版本。

### Q: 工具调用会消耗多少 token？
A: 工具定义会注入到系统 prompt 中，每个工具大约消耗 50-200 tokens（取决于描述长度）。

### Q: 可以同时定义多少个工具？
A: 理论上没有限制，但建议不超过 20 个，过多工具会影响模型选择准确性。

### Q: 支持嵌套工具调用吗？
A: 支持。可以在工具结果中返回建议调用其他工具的信息，由模型决定下一步。

### Q: 工具调用失败怎么办？
A: 返回工具结果时，可以在 `content` 中返回错误信息，模型会根据错误信息调整策略。

---

## 参考资源

- [OpenAI Function Calling 文档](https://platform.openai.com/docs/guides/function-calling)
- [Kimi2API 项目主页](https://github.com/qing1189/kimi)
- [示例代码仓库](https://github.com/qing1189/kimi/tree/main/docs/examples)

---

**更新日期：** 2026-06-15  
**版本：** v1.2.0
