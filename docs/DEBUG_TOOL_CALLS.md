# 工具调用调试指南

## 📋 问题描述

当在 Hermes、Dify 等应用中使用 Kimi2API 时，工具调用可能失败。本指南帮助你快速诊断问题。

---

## 🚀 快速开始

### 1. 启用调试日志

编辑 `.env` 文件，添加：

```bash
DEBUG_TOOL_CALLS=true
DEBUG_LOG_LEVEL=INFO
```

### 2. 重启服务

```bash
docker compose restart
```

### 3. 发送测试请求

在 Hermes 或你的应用中触发工具调用。

### 4. 查看日志

```bash
# 查看所有日志
docker compose logs -f

# 仅查看工具调用相关日志
docker compose logs -f | grep "TOOL_CALL_DEBUG"

# 保存日志到文件
docker compose logs > kimi2api_debug.log
```

---

## 📊 日志内容说明

启用 `DEBUG_TOOL_CALLS=true` 后，日志会显示：

### 1. 工具定义
```
[TOOL_CALL_DEBUG] Building tool prompt for 2 tools with tool_choice=auto
[TOOL_CALL_DEBUG] Available tools: ['send_file', 'read_file']
[TOOL_CALL_DEBUG] Tool 1: {
  "name": "send_file",
  "description": "发送文件",
  "parameters": {
    "type": "object",
    "properties": {
      "file_content": {"type": "string"},
      "filename": {"type": "string"}
    }
  }
}
```

### 2. 模型输出
```
[TOOL_CALL_DEBUG] === Starting tool call parsing ===
[TOOL_CALL_DEBUG] Input text length: 1234 chars
[TOOL_CALL_DEBUG] Input text preview: 我来帮你创建文件...
```

### 3. 解析过程
```
[TOOL_CALL_DEBUG] Strategy 'Standard DSML block' detected 1 tool(s): ['send_file']
[TOOL_CALL_DEBUG] Text length: 500 chars
[TOOL_CALL_DEBUG] Text preview: <|DSML|tool_calls>...
```

### 4. 最终结果
```
Tool calls parsed via standard DSML block: ['send_file']
```

或者：
```
[TOOL_CALL_DEBUG] No tool calls detected in response text
```

---

## 🔍 常见问题诊断

### 问题 1：模型没有调用工具

**症状**：日志显示 "No tool calls detected"

**可能原因**：
1. 模型没有理解需要调用工具
2. `tool_choice` 设置为 `none`
3. 工具描述不清晰

**解决方案**：
```json
{
  "tool_choice": "required",  // 强制调用工具
  "tools": [
    {
      "function": {
        "name": "send_file",
        "description": "发送文件给用户。当用户要求发送、提供、给出文件时使用此工具。"  // 更明确的描述
      }
    }
  ]
}
```

---

### 问题 2：工具调用格式错误

**症状**：模型输出了工具调用，但所有解析策略都失败

**日志示例**：
```
[TOOL_CALL_DEBUG] Input text preview: 我将发送文件 send_file(filename="test.txt")
[TOOL_CALL_DEBUG] No tool calls detected in response text
```

**原因**：模型使用了自创的格式，不是标准的 DSML 或 JSON 格式

**解决方案**：
1. 检查 Prompt 是否正确注入
2. 尝试其他模型（如 `kimi-k2.6` 而不是 `kimi-k2.6-thinking`）
3. 简化工具定义

---

### 问题 3：文件内容被截断

**症状**：DSML 格式的工具调用不完整

**日志示例**：
```
[TOOL_CALL_DEBUG] Input text preview: <|DSML|tool_calls>
  <|DSML|invoke name="send_file">
    <|DSML|parameter name="file_content"><![CDATA[very_long_base64_content...
```

**原因**：模型输出长度限制

**解决方案**：
- 使用 JSON 格式（更简洁）
- 分块传输文件
- 使用文件路径而不是内容

---

### 问题 4：工具名不匹配

**症状**：模型调用了工具，但名称不对

**日志示例**：
```
[TOOL_CALL_DEBUG] Available tools: ['send_feishu_file']
[TOOL_CALL_DEBUG] Strategy 'Standard DSML block' detected 1 tool(s): ['send_file']
```

**原因**：模型输出的工具名与定义不匹配

**当前状态**：规范化功能已实现但未集成，无法自动修复

**临时方案**：
1. 修改工具定义，使用模型倾向的名称（如 `send_file` 而不是 `send_feishu_file`）
2. 在工具描述中强调正确的工具名

---

## 📝 提供日志给开发者

如果你需要帮助，请提供以下信息：

### 1. 完整的工具定义
```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "...",
        "description": "...",
        "parameters": {...}
      }
    }
  ]
}
```

### 2. 调试日志
```bash
# 保存日志
docker compose logs > debug.log

# 或只保存工具调用相关的
docker compose logs | grep -A 10 -B 5 "TOOL_CALL_DEBUG" > debug.log
```

### 3. 预期行为
- 应该调用什么工具？
- 参数应该是什么？
- 其他模型（如 GPT-4）是否能正常工作？

---

## 🛠️ 高级调试

### 查看特定请求的完整日志

```bash
# 实时查看，带时间戳
docker compose logs -f --timestamps

# 查看最近 100 行
docker compose logs --tail=100

# 查看特定时间段
docker compose logs --since="2026-06-24T22:00:00"
```

### 提取关键信息

```bash
# 提取工具定义
docker compose logs | grep "Available tools"

# 提取模型输出
docker compose logs | grep "Input text preview"

# 提取解析结果
docker compose logs | grep "detected.*tool"
```

### 过滤噪音

```bash
# 排除第三方库日志
docker compose logs | grep -v "httpx" | grep -v "httpcore"
```

---

## ⚙️ 调试完成后

### 关闭调试模式

编辑 `.env`，注释或删除：
```bash
# DEBUG_TOOL_CALLS=true
# DEBUG_LOG_LEVEL=INFO
```

重启服务：
```bash
docker compose restart
```

---

## 📚 相关文档

- [文件工具支持说明](FILE_TOOL_SUPPORT.md)
- [工具调用增强文档](toolcall-enhancement.md)
- [Hermes 文件问题诊断](HERMES_FILE_ISSUE_DEBUG.md)

---

**最后更新**：2026-06-24  
**版本**：v1.0
