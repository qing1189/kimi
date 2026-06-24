# 自动删除会话功能

## 📋 问题背景

使用 Kimi2API 时，每次对话都会在 Kimi 官网（https://www.kimi.com/chat/history）留下历史记录。长期使用会导致：

- 历史对话列表过长，难以管理
- 可能包含敏感信息的对话残留在云端
- 需要手动逐个删除，操作繁琐

## ✨ 解决方案

Kimi2API 提供自动删除会话功能，可在对话完成后自动清理 Kimi 官网的历史记录。

---

## 🚀 快速开始

### 方式一：Web 管理后台配置（推荐）

1. **登录管理后台**
   ```
   访问 http://your-server:8000/admin
   ```

2. **进入系统设置**
   - 点击左侧导航栏「系统设置」

3. **选择删除模式**
   - 不删除（默认）
   - 对话完成后删除（推荐）
   - 始终删除

4. **保存设置**
   - 点击「保存设置」按钮
   - 设置立即生效，无需重启服务

### 方式二：环境变量配置（可选）

编辑 `.env` 文件，添加：

```bash
AUTO_DELETE_CHAT=on_completion
```

重启服务：

```bash
docker compose restart
```

**注意**：Web 管理后台的设置优先级高于环境变量。

---

## ⚙️ 配置选项

### `AUTO_DELETE_CHAT` 参数

| 值 | 说明 | 使用场景 |
|---|---|---|
| `disabled` | **不自动删除**（默认） | 需要保留历史记录用于审计或回溯 |
| `on_completion` | **对话完成后删除** | 正常使用，防止历史积累（推荐） |
| `always` | **始终删除**（包括错误情况） | 最大程度保护隐私 |

### 推荐配置

**一般使用**（推荐）：
```bash
AUTO_DELETE_CHAT=on_completion
```

**极致隐私保护**：
```bash
AUTO_DELETE_CHAT=always
```

**保留所有记录**（默认）：
```bash
AUTO_DELETE_CHAT=disabled
# 或直接不配置此项
```

---

## 🔍 工作原理

### 删除时机

1. **非流式响应**（`stream=false`）：
   - 在收到完整响应后
   - 构建 `ChatCompletion` 对象前
   - 调用 Kimi 删除接口

2. **流式响应**（`stream=true`）：
   - 在收到 `done` 事件后
   - 发送最后的 stop chunk 前
   - 调用 Kimi 删除接口

### 技术实现

```python
# 删除 API 端点
POST /apiv2/kimi.chat.v1.ChatService/DeleteChat

# 请求体
{
  "chat_id": "19efa4e1-5012-834d-8000-092589e39552"
}

# 响应
200 OK (删除成功)
```

### 删除的是什么？

- **会话 ID**（`remote_chat_id`）：Kimi 服务器分配的唯一标识
- **官网历史记录**：https://www.kimi.com/chat/history 中的对话条目
- **不影响**：当前请求的响应内容、本地日志

---

## 📝 使用示例

### 示例 1：API 调用（Python）

```python
import openai

client = openai.OpenAI(
    api_key="your-api-key",
    base_url="http://localhost:8000/v1"
)

# 配置 AUTO_DELETE_CHAT=on_completion 后
# 此对话完成后会自动从 Kimi 官网删除
response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "你好"}
    ]
)

print(response.choices[0].message.content)
# Kimi 官网不会有这条对话记录
```

### 示例 2：流式调用

```python
# 配置 AUTO_DELETE_CHAT=on_completion 后
# 流式响应完成时自动删除
stream = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[{"role": "user", "content": "讲个笑话"}],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# 流结束后，Kimi 官网已删除该会话
```

### 示例 3：Hermes 中使用

在 Hermes 中配置 Kimi2API 为 API 提供者：

```
基础URL: http://your-server:8000/v1
API Key: your-api-key
模型: kimi-k2.6
```

设置 `.env` 中 `AUTO_DELETE_CHAT=on_completion`，每次对话完成后 Kimi 官网不会留下记录。

---

## 🛡️ 隐私保护

### 删除成功后

- ✅ Kimi 官网历史记录中**不可见**
- ✅ 无法通过官网界面恢复
- ✅ 减少云端数据残留

### 本地仍然保留

- ✅ Kimi2API 请求日志（`REQUEST_LOG_RETENTION` 控制）
- ✅ 应用层日志（如 Hermes 的对话记录）

### 注意事项

1. **删除是单向操作**：无法恢复已删除的会话
2. **本地日志独立**：删除官网记录不影响本地日志
3. **多账号场景**：删除的是当前使用账号的会话

---

## ⚠️ 故障处理

### 删除失败

删除失败**不会影响**正常响应：

```python
# 即使删除失败，用户仍能收到完整响应
# 只是 Kimi 官网会保留该会话记录
```

### 查看删除日志

启用 DEBUG 日志查看删除详情：

```bash
# .env 文件
DEBUG_LOG_LEVEL=DEBUG

# 查看日志
docker compose logs -f | grep "delete_chat"
```

---

## 🔄 与其他项目对比

### ds2api 和 qwen2api

这些项目也支持会话管理，Kimi2API 的实现参考了它们的设计：

| 功能 | Kimi2API | ds2api/qwen2api |
|---|---|---|
| 自动删除会话 | ✅ | ✅ |
| 配置方式 | 环境变量 | 环境变量 |
| 删除时机 | on_completion/always | 类似 |
| 多账号支持 | ✅ | ✅ |

---

## 🎯 最佳实践

### 生产环境

```bash
# 平衡隐私和调试需求
AUTO_DELETE_CHAT=on_completion
REQUEST_LOG_RETENTION=100
DEBUG_LOG_LEVEL=INFO
```

### 开发调试

```bash
# 保留会话便于在官网查看
AUTO_DELETE_CHAT=disabled
DEBUG_LOG_LEVEL=DEBUG
```

### 高隐私场景

```bash
# 最大程度减少数据残留
AUTO_DELETE_CHAT=always
REQUEST_LOG_RETENTION=10
REQUEST_LOG_BODY_LIMIT=0
```

---

## 📚 相关文档

- [工具调用调试指南](DEBUG_TOOL_CALLS.md)
- [配置文件说明](.env.example)

---

**最后更新**：2026-06-24  
**版本**：v1.0
