# qwen2API 工具调用实现分析与借鉴

## 📋 项目背景

**项目**：https://github.com/YuJunZhiXue/qwen2API  
**语言**：Go  
**分析日期**：2026-06-24  
**目的**：学习其工具调用实现，改进我们的 Kimi2API 项目

---

## 🎯 核心设计理念

### 1. **多格式容错解析**

qwen2API 支持 4 种不同的工具调用格式，按优先级尝试：

```go
func ParseToolCalls(text string, tools []map[string]any) []ParsedToolCall {
    calls := []ParsedToolCall{}
    calls = append(calls, parseQNMLToolCalls(text, allowed, tools)...)      // 1. QNML 格式（主格式）
    calls = append(calls, parseXMLToolCalls(text, allowed)...)              // 2. XML 格式
    ForEachJSONFragment(text, func(value any) {                              // 3. JSON 片段
        calls = append(calls, parseJSONToolCalls(value, allowed)...)
    })
    calls = append(calls, parseTextKVToolCalls(text, allowed, tools)...)    // 4. 文本键值对（兜底）
    return DedupeToolCalls(coerceToolCalls(calls, tools))
}
```

**启示**：不要依赖单一格式，提供多个回退方案。

---

## 💡 值得借鉴的特性

### 特性 1：工具名称规范化（Name Canonicalization）

**问题**：模型可能输出工具名的变体
- `Bash` vs `bash` vs `shell_run`
- `Read` vs `fs_open_file` vs `read_file`

**解决方案**：

```go
func canonicalToolName(name string, allowed map[string]string) string {
    // 1. 精确匹配（忽略大小写）
    if exact, ok := allowed[strings.ToLower(name)]; ok {
        return exact
    }
    
    // 2. 检查已知别名
    if alias := qwenToolAlias(name); alias != "" {
        if exact, ok := allowed[strings.ToLower(alias)]; ok {
            return exact
        }
    }
    
    // 3. 模糊匹配（移除特殊字符）
    key := toolAliasKey(name)  // "read_file" -> "readfile"
    for allowedKey, canonical := range allowed {
        if toolAliasKey(allowedKey) == key {
            return canonical
        }
    }
    
    return ""
}

// 别名映射
var qwenToolAlias = map[string]string{
    "fs_open_file":   "Read",
    "fs_put_file":    "Write",
    "fs_patch_file":  "Edit",
    "shell_run":      "Bash",
    "text_search":    "Grep",
    // ...
}
```

**收益**：显著提升工具调用成功率

---

### 特性 2：参数名称修复（Parameter Coercion）

**问题**：模型可能使用错误的参数名
- `path` vs `file_path` vs `filename`
- `cmd` vs `command`

**解决方案**：

```go
func CoerceToolInput(name string, input any, tools []map[string]any) any {
    fixed := cloneMap(input)
    
    switch name {
    case "Read":
        renameFirstPresent(fixed, "file_path", "path", "filename", "file")
    case "Write":
        renameFirstPresent(fixed, "file_path", "path", "target_file", "filename")
        renameFirstPresent(fixed, "content", "text", "body", "data", "file_content")
    case "Bash", "PowerShell":
        renameFirstPresent(fixed, "command", "cmd", "script")
    }
    
    return fixed
}

func renameFirstPresent(m map[string]any, canonical string, aliases ...string) {
    if m[canonical] != nil {
        return  // 正确参数名已存在
    }
    for _, alias := range aliases {
        if value, ok := m[alias]; ok {
            delete(m, alias)
            m[canonical] = value
            return
        }
    }
}
```

**收益**：容忍模型的参数命名错误

---

### 特性 3：Schema 驱动的类型转换

**问题**：模型可能输出错误的类型
- Schema 要求 `array`，模型输出 `string`
- Schema 要求 `object`，模型输出 JSON 字符串

**解决方案**：

```go
func coerceValueBySchema(value any, schema map[string]any) any {
    types := schemaTypes(schema)
    wantArray := types["array"]
    wantObject := types["object"]
    
    // 如果是字符串，但 schema 要求对象/数组，尝试解析
    if s, ok := value.(string); ok && (wantArray || wantObject) {
        if parsed, changed := parseJSONStringForSchema(s, wantArray, wantObject); changed {
            value = parsed
        }
    }
    
    // 如果是对象，但 schema 要求数组，包装成数组
    if wantArray {
        if m, ok := value.(map[string]any); ok {
            value = []any{m}
        }
    }
    
    return value
}
```

**收益**：自动修复类型不匹配

---

### 特性 4：参数污染检测

**问题**：模型可能在参数值中泄露提示词或格式标记

**解决方案**：

```go
func pathLikeArgLooksPolluted(value string) bool {
    lowered := strings.ToLower(value)
    
    // 检测 QNML/XML 标记泄露
    for _, marker := range []string{
        "<![cdata[", "]]>", "qnml|", "tool_calls",
        "invoke name=", "parameter name=",
    } {
        if strings.Contains(lowered, marker) {
            return true
        }
    }
    
    // 检测自然语言泄露（模型在"思考"）
    for _, marker := range []string{
        "我将", "我会", "首先", "接下来",
        "i will", "i'll", "first i", "next i",
    } {
        if strings.Contains(lowered, marker) {
            return true
        }
    }
    
    return false
}
```

**收益**：过滤掉被污染的工具调用

---

### 特性 5：去重机制

**问题**：多格式解析可能导致重复的工具调用

**解决方案**：

```go
func DedupeToolCalls(calls []ParsedToolCall) []ParsedToolCall {
    seen := map[string]bool{}
    out := []ParsedToolCall{}
    
    for _, call := range calls {
        // 使用工具名 + 参数 JSON 作为唯一键
        keyBytes, _ := json.Marshal(call.Input)
        key := strings.ToLower(call.Name) + "\x00" + string(keyBytes)
        
        if !seen[key] {
            seen[key] = true
            out = append(out, call)
        }
    }
    
    return out
}
```

---

### 特性 6：文本键值对回退格式

**最后的兜底方案**：当所有结构化格式都失败时，尝试解析简单的文本格式

```
name: Bash
arguments:
  command: ls -la
  description: List files
```

解析器会识别 `key: value` 模式并构建参数对象。

---

## 🔧 Unicode 字符规范化

**问题**：模型可能输出全角字符或相似字符

```go
var markupReplacements = map[string]string{
    "＜": "<", "＞": ">",           // 全角括号
    "／": "/", "＝": "=",           // 全角符号
    "｜": "|", "│": "|", "┃": "|", // 各种竖线
    """: `"`, """: `"`,             // 智能引号
    "Ο": "O", "ο": "o",            // 希腊字母 O
    "А": "A", "С": "C",            // 西里尔字母
}
```

**启示**：在解析前规范化字符，提高容错性

---

## 📊 与当前实现对比

| 特性 | Kimi2API (当前) | qwen2API | 优先级 |
|------|----------------|----------|--------|
| 多格式支持 | ✅ DSML + JSON | ✅ QNML + XML + JSON + TextKV | ⭐⭐⭐⭐⭐ |
| 工具名规范化 | ❌ 无 | ✅ 完善 | ⭐⭐⭐⭐⭐ |
| 参数名修复 | ❌ 无 | ✅ 完善 | ⭐⭐⭐⭐ |
| Schema 类型转换 | ❌ 无 | ✅ 完善 | ⭐⭐⭐⭐ |
| 参数污染检测 | ❌ 无 | ✅ 完善 | ⭐⭐⭐ |
| JSON 修复 | ✅ 基础 | ✅ 高级 | ⭐⭐⭐ |
| 去重机制 | ❌ 无 | ✅ 完善 | ⭐⭐⭐ |
| Unicode 规范化 | ❌ 无 | ✅ 完善 | ⭐⭐ |
| 文本 KV 回退 | ❌ 无 | ✅ 支持 | ⭐⭐ |

---

## 🚀 改进建议

### 优先级 1：工具名规范化（⭐⭐⭐⭐⭐）

**实施内容**：
- 添加 `canonicalize_tool_name()` 函数
- 支持常见别名映射
- 模糊匹配（移除特殊字符和空格）

**预期收益**：工具调用成功率 +20-30%

---

### 优先级 2：参数名修复（⭐⭐⭐⭐⭐）

**实施内容**：
- 为常用工具添加参数别名映射
- `Read`: `path` → `file_path`
- `Write`: `text` → `content`
- `Bash`: `cmd` → `command`

**预期收益**：减少 "missing required parameter" 错误 15-20%

---

### 优先级 3：Schema 驱动类型转换（⭐⭐⭐⭐）

**实施内容**：
- 检查工具 schema 的类型要求
- 自动转换不匹配的类型
- 字符串 → JSON 对象/数组
- 对象 → 数组包裹

**预期收益**：减少类型错误 10-15%

---

### 优先级 4：参数污染检测（⭐⭐⭐）

**实施内容**：
- 检测参数值中的格式标记（`<|DSML|`, `<![CDATA[`）
- 检测自然语言泄露（"我将"、"首先"）
- 拒绝被污染的工具调用

**预期收益**：减少无效调用 5-10%

---

### 优先级 5：去重机制（⭐⭐⭐）

**实施内容**：
- 基于工具名 + 参数哈希去重
- 避免多格式解析导致的重复

**预期收益**：清理冗余调用

---

## 📝 实施计划

### 阶段 1：核心功能（1-2 天）

1. ✅ 实现工具名规范化
2. ✅ 实现参数名修复
3. ✅ 添加测试用例

### 阶段 2：高级功能（2-3 天）

4. ✅ Schema 驱动类型转换
5. ✅ 参数污染检测
6. ✅ 去重机制

### 阶段 3：优化与测试（1-2 天）

7. ✅ 完整测试覆盖
8. ✅ 性能优化
9. ✅ 文档更新

---

## 📚 技术要点

### 1. 别名映射表

```python
TOOL_ALIASES = {
    # Bash 相关
    "bash": "Bash",
    "shell": "Bash",
    "shell_run": "Bash",
    "run_command": "Bash",
    "execute": "Bash",
    
    # Read 相关
    "read": "Read",
    "read_file": "Read",
    "fs_open_file": "Read",
    "open_file": "Read",
    "get_file": "Read",
    
    # Write 相关
    "write": "Write",
    "write_file": "Write",
    "fs_put_file": "Write",
    "create_file": "Write",
    "save_file": "Write",
    
    # Edit 相关
    "edit": "Edit",
    "edit_file": "Edit",
    "fs_patch_file": "Edit",
    "modify_file": "Edit",
    "update_file": "Edit",
}
```

### 2. 参数别名映射

```python
PARAMETER_ALIASES = {
    "Read": {
        "file_path": ["path", "filename", "file", "filepath", "target"],
    },
    "Write": {
        "file_path": ["path", "filename", "file", "filepath", "target"],
        "content": ["text", "body", "data", "file_content", "contents", "value"],
    },
    "Bash": {
        "command": ["cmd", "script", "code", "shell_command"],
    },
    "Edit": {
        "file_path": ["path", "filename", "file", "filepath", "target"],
        "old_string": ["old", "search", "pattern", "find"],
        "new_string": ["new", "replace", "replacement", "substitute"],
    },
}
```

### 3. 污染检测模式

```python
POLLUTION_MARKERS = [
    # 格式标记
    "<|DSML|", "</|DSML|", "<![CDATA[", "]]>",
    "<tool_calls>", "</tool_calls>",
    "<invoke", "</invoke>",
    
    # 自然语言（中文）
    "我将", "我会", "我先", "首先", "现在", "接下来", "然后",
    
    # 自然语言（英文）
    "i will", "i'll", "i am going to", "now i", "next i", "first i",
    "let me", "i need to",
]
```

---

## 🎯 预期效果

### 改进前
- ❌ 工具名变体导致失败
- ❌ 参数名错误导致失败
- ❌ 类型不匹配导致失败
- ❌ 参数污染导致错误执行

### 改进后
- ✅ 自动识别工具名变体
- ✅ 自动修复参数名错误
- ✅ 自动转换类型不匹配
- ✅ 过滤被污染的调用
- ✅ 总体成功率预计提升 **30-50%**

---

## 🔗 参考资源

- **项目地址**：https://github.com/YuJunZhiXue/qwen2API
- **核心文件**：
  - `backend/toolcall/parser.go` - 主解析器
  - `backend/toolcall/normalize.go` - 规范化逻辑
  - `backend/toolcall/formats_qnml.go` - QNML 格式解析
  - `backend/toolcall/fallback_textkv.go` - 文本键值对回退

---

**分析完成日期**：2026-06-24  
**下一步**：开始实施改进计划  
**预计完成时间**：3-5 天
