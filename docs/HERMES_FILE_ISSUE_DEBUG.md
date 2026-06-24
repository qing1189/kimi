# Hermes 文件发送问题诊断指南

## 🔍 问题描述

**症状**：在 Hermes 中使用 Kimi2API 时，无法让飞书发送文件

**预期**：模型应该调用飞书的文件发送工具

---

## 📊 诊断步骤

### 第 1 步：查看请求日志

1. 访问 `http://your-server:8000/admin`
2. 进入「请求日志」页面
3. 找到失败的请求
4. 查看以下信息：
   - **请求正文**：工具定义是否正确？
   - **响应内容**：模型实际输出了什么？
   - **工具调用**：是否检测到工具调用？

### 第 2 步：检查工具定义

Hermes 发送的工具定义应该类似：

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "send_feishu_file",  // 或类似的名称
        "description": "发送文件到飞书",
        "parameters": {
          "type": "object",
          "properties": {
            "file_content": {  // 关键：包含 file/content/data 等关键字
              "type": "string",
              "description": "文件内容（base64编码）"
            },
            "filename": {
              "type": "string",
              "description": "文件名"
            }
          },
          "required": ["file_content", "filename"]
        }
      }
    }
  ]
}
```

### 第 3 步：检查模型输出

在日志中查看模型的实际输出，可能是以下几种情况：

#### 情况 1：模型只回复文本，没有调用工具
```
让我帮你创建一个文件...
```
**原因**：模型没有理解需要调用工具  
**解决**：可能需要更明确的 Prompt 或 `tool_choice: "required"`

#### 情况 2：模型输出了 DSML 格式但格式错误
```
<|DSML|tool_calls>
  <|DSML|invoke name="send_feishu_file">
    <|DSML|parameter name="file_content"><![CDATA[很长的base64内容被截断...
```
**原因**：内容太长被截断  
**解决**：需要使用 JSON 格式

#### 情况 3：模型输出了错误的工具名
```
<|DSML|invoke name="send_file">  // 实际工具名可能是 send_feishu_file
```
**原因**：工具名不匹配  
**解决**：需要启用工具名规范化（已实现但未集成）

#### 情况 4：模型输出了 JSON 格式但未被识别
```
我来帮你发送文件。

{
  "name": "send_feishu_file",
  "arguments": {
    "file_content": "base64...",
    "filename": "test.txt"
  }
}
```
**原因**：JSON 格式没有被正确解析  
**解决**：需要检查解析器

---

## 🔧 快速修复方案

### 方案 1：确认工具参数名包含关键字

检查 Hermes 的工具定义，确保参数名包含以下关键字之一：
- `file_content`
- `content`
- `data`
- `attachment`
- `file_data`
- `base64`

这样系统会自动提示 JSON 格式。

### 方案 2：手动添加测试工具

创建一个简单的测试工具来验证：

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "test_send_file",
        "description": "测试发送文件",
        "parameters": {
          "type": "object",
          "properties": {
            "file_content": {
              "type": "string",
              "description": "文件内容"
            },
            "filename": {
              "type": "string"
            }
          },
          "required": ["file_content", "filename"]
        }
      }
    }
  ],
  "tool_choice": "required"  // 强制调用工具
}
```

### 方案 3：启用调试日志

在 Hermes 中启用详细日志，查看：
1. 发送到 Kimi2API 的请求
2. Kimi2API 的响应
3. 工具调用是否被识别

---

## 🐛 常见问题

### Q1: 为什么官方 API 能用，2API 不能用？

**A**: 官方 API 使用原生 Function Calling，模型经过专门训练。2API 在 Prompt 层模拟，模型可能：
- 不理解复杂的 DSML 格式
- 输出被截断
- 工具名不匹配

### Q2: 规范化功能为什么没有生效？

**A**: 规范化功能（`toolcall_normalize.py`）已经实现，但**尚未集成到主解析流程**。需要修改 `toolcall.py` 来调用这些函数。

### Q3: 如何强制模型调用工具？

**A**: 在请求中添加：
```json
{
  "tool_choice": "required"
}
```

或指定特定工具：
```json
{
  "tool_choice": {
    "type": "function",
    "function": {"name": "send_feishu_file"}
  }
}
```

---

## 🔨 需要集成的改进

当前规范化功能**已实现但未集成**，需要在 `parse_tool_calls_from_text()` 中添加：

```python
from app.api.toolcall_normalize import (
    normalize_tool_call,
    deduplicate_tool_calls
)

def parse_tool_calls_from_text(text, tools):
    # 现有解析逻辑...
    raw_calls = _parse_dsml_or_json(text)
    
    # 🆕 添加规范化步骤
    normalized_calls = []
    available_tools = [t.get("function", {}).get("name") for t in tools]
    
    for call in raw_calls:
        normalized = normalize_tool_call(
            tool_name=call["name"],
            parameters=call["parameters"],
            available_tools=available_tools,
            tools_schema=tools
        )
        if normalized:
            normalized_calls.append(normalized)
    
    # 🆕 去重
    unique_calls = deduplicate_tool_calls(normalized_calls)
    
    return unique_calls
```

---

## 📝 收集信息

请提供以下信息以便进一步诊断：

1. **工具定义**：Hermes 配置的飞书工具完整定义
2. **模型输出**：从请求日志中复制模型的实际输出
3. **错误信息**：Hermes 显示的错误消息
4. **Kimi2API 版本**：`git log --oneline -1`

---

## 🚀 临时解决方案

在修复前，可以尝试：

### 方案 A：简化工具定义
使用更简单的参数结构：
```json
{
  "name": "send_file",
  "parameters": {
    "properties": {
      "path": {"type": "string"},  // 文件路径而不是内容
      "message": {"type": "string"}
    }
  }
}
```

### 方案 B：分步骤操作
1. 先让模型生成文件内容
2. 再手动上传到飞书

### 方案 C：使用官方 API
对于文件操作，暂时切换回官方 API

---

## 📞 下一步

1. **收集日志**：从管理面板导出失败请求的详细信息
2. **分享信息**：提供工具定义和模型输出
3. **集成规范化**：我可以帮你将规范化功能集成到主流程

---

**最后更新**：2026-06-24  
**状态**：待诊断
