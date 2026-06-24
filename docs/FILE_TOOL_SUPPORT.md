# 文件操作工具调用支持

## 📋 问题背景

在使用 2API 配合 Hermes 等应用时，发现包含文件附件的工具调用场景经常失败，而使用官方 API 则正常工作。

### 根本原因

2API 使用 **DSML 协议**在 prompt 层模拟工具调用，要求所有字符串参数用 `<![CDATA[...]]>` 包裹：

```xml
<|DSML|parameter name="file_content"><![CDATA[very_long_base64_content...]]></|DSML|parameter>
```

这种格式对于包含大量数据的场景存在问题：
- **Base64 编码的文件内容**可能非常长（几 KB 到几 MB）
- **模型输出长度限制**可能导致内容截断
- **CDATA 特殊字符转义**（如 `]]>` 需要转义）模型可能不知道
- **复杂格式**增加了模型出错的概率

而官方 API 使用原生 Function Calling，参数直接以 JSON 格式传递，无需复杂包裹。

---

## ✅ 解决方案

### 1. 增强 JSON 格式支持

**改进点**：
- ✅ 自动检测包含文件操作的工具（通过参数名启发式识别）
- ✅ 在 Prompt 中添加 JSON 格式说明作为备选方案
- ✅ 改进 JSON 解析正则表达式，支持深度嵌套对象
- ✅ 集成现有的 JSON 修复机制

**识别的文件相关参数名**：
- `file_content`
- `content`
- `data`
- `attachment`
- `file_data`
- `base64`

### 2. 改进的 Prompt

当检测到文件操作工具时，Prompt 会自动添加：

```
📝 NOTE: For tools with large data (files, attachments), 
you can use simplified JSON format if DSML is too complex:

{
  "name": "tool_name",
  "arguments": {
    "param": "value"
  }
}

注意：对于包含大量数据（文件、附件）的工具，
如果 DSML 格式太复杂，可以使用简化的 JSON 格式。
```

### 3. 增强的 JSON 解析

**支持的格式**：

#### 格式 1：Markdown 包裹的 JSON
```markdown
```json
{
  "name": "send_file",
  "arguments": {
    "file_content": "SGVsbG8gV29ybGQ=",
    "filename": "test.txt"
  }
}
\```
```

#### 格式 2：不带包裹的 JSON
```json
{"name": "create_file", "arguments": {"filename": "test.txt", "content": "Hello"}}
```

#### 格式 3：嵌套对象
```json
{
  "name": "send_attachment",
  "arguments": {
    "file": {
      "name": "document.pdf",
      "size": 1024,
      "content": "base64content..."
    },
    "metadata": {
      "author": "User"
    }
  }
}
```

#### 格式 4：标准 DSML（仍然支持）
```xml
<|DSML|tool_calls>
  <|DSML|invoke name="read_file">
    <|DSML|parameter name="path"><![CDATA[/path/to/file.txt]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
```

---

## 🧪 测试覆盖

已添加 8 个测试用例覆盖文件操作场景：

1. ✅ JSON 格式包含文件内容
2. ✅ JSON 格式包含 base64 编码数据
3. ✅ 不带 markdown 包裹的 JSON
4. ✅ 包含嵌套对象的 JSON
5. ✅ DSML 格式仍然正常工作
6. ✅ 自动检测文件工具并调整 Prompt
7. ✅ JSON 格式验证
8. ✅ 大文件内容处理

**测试结果**：8/8 通过 ✅

---

## 📊 预期效果

### 改进前
- ❌ 文件附件工具调用失败
- ❌ Base64 内容被截断
- ❌ 模型难以正确生成 DSML 格式
- ❌ 用户体验差

### 改进后
- ✅ 支持多种格式（DSML + JSON）
- ✅ 自动检测文件工具并提示
- ✅ 更好地处理大数据内容
- ✅ 更高的成功率

---

## 🔧 使用建议

### 对于应用开发者

如果你的应用需要使用文件操作相关的工具调用：

1. **工具定义**中明确标注参数用途：
```python
{
  "name": "send_file",
  "parameters": {
    "properties": {
      "file_content": {
        "type": "string",
        "description": "Base64 encoded file content"
      }
    }
  }
}
```

2. **参数命名**使用标准名称（`file_content`、`content`、`data` 等），这样系统会自动启用 JSON 格式提示

3. **测试**两种格式都应该能正常工作：
   - DSML 格式（小文件）
   - JSON 格式（大文件或复杂数据）

### 对于最终用户

- ✅ 无需修改配置，改进自动生效
- ✅ 与官方 API 的兼容性提升
- ✅ 文件附件功能现在应该能正常工作

---

## 🚀 部署

### 方式 1：拉取最新代码

```bash
cd kimi2api/
git pull
docker compose up -d --build
```

### 方式 2：手动更新

如果你修改过代码，可以只更新 `app/api/toolcall.py` 文件中的相关函数。

---

## 📝 相关文件

- `app/api/toolcall.py` - 核心改进
- `tests/test_file_tool_calls.py` - 测试套件
- `docs/toolcall-enhancement.md` - 工具调用增强文档
- `docs/JSON_REPAIR_COMPLETION.md` - JSON 修复机制

---

## 🐛 故障排除

### 问题：仍然无法发送文件

**检查步骤**：

1. 查看请求日志（`/admin` → 请求日志）
2. 检查模型输出的格式
3. 确认文件大小是否超过模型输出限制

**临时方案**：

如果文件非常大（> 100KB），考虑：
- 分块传输
- 使用文件 URL 而不是直接传输内容
- 压缩后再编码

### 问题：JSON 格式未被识别

**可能原因**：

1. 参数名不在自动检测列表中
2. JSON 格式不标准（缺少必需字段）

**解决方法**：

手动在工具描述中添加格式说明：
```
"description": "Send file. You can use JSON format: {\"name\": \"send_file\", \"arguments\": {...}}"
```

---

## 📈 未来优化

可能的进一步改进（低优先级）：

- [ ] 支持更多文件参数名变体
- [ ] 自动压缩大文件内容
- [ ] 提供文件分块传输示例
- [ ] 添加文件大小统计和警告

---

**更新日期**：2026-06-24  
**版本**：v1.1（文件操作支持）  
**状态**：✅ 已实现并测试
