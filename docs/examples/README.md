# Kimi2API 示例代码

本目录包含 Kimi2API 的各种使用示例。

## 工具调用 (Function Calling)

### 基础示例
- **[tool_calling_weather.py](tool_calling_weather.py)** - 天气查询助手
  - 展示基本的工具定义和调用流程
  - 演示多工具并行调用
  - 展示完整的对话循环

### 高级示例
- **[tool_calling_stream.py](tool_calling_stream.py)** - 流式输出 + 工具调用
  - 展示如何在流式模式下处理工具调用
  - 演示工具调用结果的累积
  - 展示多轮对话的实现

## 运行示例

### 前置条件

1. 确保 Kimi2API 服务已启动：
```bash
python run.py
```

2. 安装 OpenAI SDK：
```bash
pip install openai
```

3. 配置 API Key：
- 在管理面板 (http://localhost:8000/admin) 创建 API Key
- 或在 `.env` 文件中设置 `OPENAI_API_KEY`

### 运行示例

```bash
# 修改示例文件中的 API Key
# 将 "your-kimi2api-key" 替换为你的实际 Key

# 运行天气查询示例
python docs/examples/tool_calling_weather.py

# 运行流式输出示例
python docs/examples/tool_calling_stream.py
```

## 示例输出

### tool_calling_weather.py

```
============================================================
Kimi2API 工具调用示例 - 天气查询助手
============================================================

👤 用户: 北京今天天气怎么样？

--- 迭代 1 ---
📞 需要调用 1 个工具
🔧 调用工具: get_weather(city=北京, unit=celsius)
✅ 工具返回: {"temperature": 15, "condition": "晴天", "humidity": 45, "unit": "°C"}

--- 迭代 2 ---
🤖 最终回复: 北京今天天气晴朗，温度15°C，湿度45%。天气不错，适合外出活动。
```

### tool_calling_stream.py

```
============================================================
Kimi2API 工具调用示例 - 流式输出
============================================================

👤 用户: 计算 123 + 456

🤖 助手: 好的，我来帮你计算。

📞 检测到工具调用:

  工具: calculate
  参数: {"expression": "123 + 456"}
  结果: {"result": 579, "expression": "123 + 456"}

🤖 最终回复: 计算结果是 579。
```

## 更多资源

- [完整工具调用文档](../tool-calling.md)
- [API 参考](https://platform.openai.com/docs/api-reference)
- [OpenAI Function Calling 指南](https://platform.openai.com/docs/guides/function-calling)
