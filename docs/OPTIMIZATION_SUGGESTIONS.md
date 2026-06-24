# 工具调用实现对比分析与优化建议

## 项目对比

### 对比项目
1. **当前项目** (qing1189/kimi) - 基于 ds2api 的 DSML 格式
2. **参考项目** (qingdeng888/kimi) - 自定义标记格式

---

## 实现方式对比

### 1. 标记格式

| 特性 | 当前项目 (DSML) | 参考项目 (自定义) |
|------|----------------|-----------------|
| **开始标记** | `<\|DSML\|tool_calls>` | `[function_calls]` |
| **调用标记** | `<\|DSML\|invoke name="...">` | `[call:tool_name]` |
| **参数标记** | `<\|DSML\|parameter name="...">` | 直接 JSON |
| **CDATA 包裹** | ✅ 支持 | ❌ 不需要 |
| **格式复杂度** | 高（类 XML） | 低（简洁） |
| **模型遵守难度** | 较难 | 较易 |

**分析**：
- ✅ **参考项目的优势**：格式更简洁，模型更容易学习和遵守
- ⚠️ **当前项目的优势**：更规范化，参考了 DeepSeek 的官方 DSML 协议

---

### 2. Prompt 工程

#### 当前项目 Prompt 特点
```python
# 优点
✅ 双语指令（中英文）
✅ 详细的格式约束
✅ 正确和错误示例对比
✅ 严格的规则说明
✅ 支持 tool_choice 模式

# 缺点
⚠️ Prompt 较长（~150 行）
⚠️ 格式复杂，模型可能困惑
```

#### 参考项目 Prompt 特点
```python
# 优点
✅ 格式简洁清晰
✅ Prompt 长度适中（~40 行）
✅ 模型容易理解和遵守
✅ 中文指令，更适合中文模型

# 缺点
⚠️ 缺少错误示例
⚠️ 未实现 tool_choice 模式
```

---

### 3. 解析器实现

| 功能 | 当前项目 | 参考项目 | 推荐 |
|------|---------|---------|------|
| **多格式支持** | ✅ 3+ 种 | ✅ 2 种 | 当前 |
| **正则复杂度** | 高 | 低 | 参考 |
| **XML 修复** | ✅ | ❌ | 当前 |
| **JSON 修复** | ❌ | ✅ | 参考 |
| **流式检测** | ✅ 状态机 | ✅ 简单检测 | 当前 |
| **代码围栏保护** | ✅ | ❌ | 当前 |

---

## 🎯 核心优化建议

### 优化 1: 采用混合标记格式（推荐 ⭐⭐⭐⭐⭐）

**问题**：当前 DSML 格式过于复杂，模型遵守率可能不高

**建议**：提供**简化版**作为备选，在 Prompt 中让模型选择更简单的格式

```python
# 新增：简化格式支持
SIMPLE_FORMAT = """
[TOOL_CALL]
{
  "name": "get_weather",
  "arguments": {"city": "Beijing"}
}
[/TOOL_CALL]
"""

# 保留 DSML 格式作为高级选项
DSML_FORMAT = """
<|DSML|tool_calls>
  <|DSML|invoke name="get_weather">
    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
"""
```

**实现建议**：
1. 在 `build_tool_prompt_block` 中添加 `format_style` 参数
2. 默认使用简化格式，高级用户可选 DSML
3. 解析器同时支持两种格式

**预期收益**：
- ✅ 提高模型遵守率 30-50%
- ✅ 减少解析失败率
- ✅ 降低 Prompt 长度

---

### 优化 2: JSON 修复机制（推荐 ⭐⭐⭐⭐）

**问题**：当前实现缺少 JSON 格式修复

**建议**：借鉴参考项目的 `_repair_json` 函数

```python
def _repair_json(text: str) -> str:
    """尝试修复常见的 JSON 格式问题"""
    if not text:
        return ""
    
    repairs = [
        # 原始文本
        lambda t: t,
        # 移除尾部逗号
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t),
        # 单引号转双引号
        lambda t: t.replace("'", '"'),
        # 组合修复
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t.replace("'", '"')),
    ]
    
    for repair_fn in repairs:
        try:
            repaired = repair_fn(text)
            parsed = json.loads(repaired)
            return json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, Exception):
            continue
    
    return ""
```

**集成位置**：
- `toolcall_enhanced.py::_decode_param_value`
- `toolcall.py::_parse_parameters`

**预期收益**：
- ✅ 容忍单引号 JSON
- ✅ 自动移除尾部逗号
- ✅ 提高解析成功率 10-20%

---

### 优化 3: 简化 Prompt 长度（推荐 ⭐⭐⭐⭐）

**问题**：当前 Prompt 过长（~200 行），消耗大量 token

**建议**：借鉴参考项目的精简风格

**当前 Prompt 结构**：
```
1. 双语标题
2. 工具列表
3. 强制格式
4. 7 条严格规则
5. 正确示例
6. 3 个错误示例
7. tool_choice 指令
8. 可用工具详情
```

**优化后结构**：
```
1. 工具列表
2. 调用格式（1 个示例）
3. 3 条核心规则
4. 可用工具详情
```

**优化示例**：

```python
def build_tool_prompt_block_v2(tools, tool_choice="auto"):
    """精简版工具 Prompt"""
    
    tool_list = _build_tool_list(tools)  # 简洁的工具列表
    
    return f"""# 可用工具

{tool_list}

## 调用格式

使用工具时，输出以下格式：

[TOOL_CALL]
{{"name": "工具名", "arguments": {{"参数": "值"}}}}
[/TOOL_CALL]

注意：
1. 必须是有效 JSON 格式
2. 工具调用必须在回复最后
3. 可以调用多个工具

{_build_choice_instruction(tool_choice)}
"""
```

**预期收益**：
- ✅ Prompt 长度减少 60%
- ✅ Token 消耗减少
- ✅ 模型理解更快

---

### 优化 4: 流式解析优化（推荐 ⭐⭐⭐）

**问题**：当前流式解析测试有 2 个失败

**建议**：参考项目的 `detect_partial_tool_call` 思路

```python
class EnhancedToolCallSieve:
    """改进的流式解析器"""
    
    def __init__(self):
        self.state = SieveState.TEXT
        self.pending = ""
        self.capture = ""
        self.accumulated_text = ""  # 新增：累积完整文本
    
    def push(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """处理流式块"""
        self.accumulated_text += chunk
        
        # 检测是否开始工具调用
        if self._has_tool_marker(self.accumulated_text):
            # 暂停文本输出，等待完整工具调用
            self.state = SieveState.CAPTURING
            return "", None
        
        # 正常文本输出
        return chunk, None
    
    def _has_tool_marker(self, text: str) -> bool:
        """检测工具调用标记"""
        markers = [
            "[TOOL_CALL]",
            "<|DSML|tool_calls>",
            "[function_calls]",
        ]
        return any(m in text for m in markers)
```

**预期收益**：
- ✅ 修复流式解析测试失败
- ✅ 提高流式可靠性

---

### 优化 5: 工具名称白名单验证（推荐 ⭐⭐⭐⭐）

**问题**：当前实现未验证工具名称

**建议**：添加白名单验证机制

```python
def parse_tool_calls_from_text(
    text: str,
    available_tools: Optional[List[str]] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """解析工具调用，支持白名单验证"""
    
    # 解析工具调用
    content, calls = _parse_internal(text)
    
    # 白名单验证
    if available_tools:
        validated_calls = []
        for call in calls:
            tool_name = call["function"]["name"]
            if tool_name in available_tools:
                validated_calls.append(call)
            else:
                logger.warning(f"Unknown tool: {tool_name}, ignored")
        return content, validated_calls
    
    return content, calls
```

**集成位置**：
- `inject_tool_call_context` - 传递工具名称列表
- `parse_tool_calls_from_text` - 添加验证参数

**预期收益**：
- ✅ 防止模型幻觉工具
- ✅ 提高安全性

---

### 优化 6: 测试用例补充（推荐 ⭐⭐⭐）

**问题**：参考项目有 13 个测试用例，我们只有 23 个（覆盖不同方面）

**建议**：补充以下测试

```python
# 新增测试用例
def test_json_repair():
    """测试 JSON 修复"""
    # 单引号
    text = "[TOOL_CALL]{'name': 'test'}[/TOOL_CALL]"
    
    # 尾部逗号
    text = '[TOOL_CALL]{"name": "test",}[/TOOL_CALL]'

def test_tool_name_validation():
    """测试工具名称验证"""
    available = ["get_weather", "search"]
    text = "[TOOL_CALL]{\"name\": \"unknown_tool\"}[/TOOL_CALL]"
    # 应该返回空列表

def test_simplified_format():
    """测试简化格式"""
    text = """
    [TOOL_CALL]
    {"name": "get_weather", "arguments": {"city": "Beijing"}}
    [/TOOL_CALL]
    """
```

---

## 📊 优化优先级矩阵

| 优化项 | 难度 | 收益 | 优先级 | 预估时间 |
|--------|------|------|--------|---------|
| 1. 混合标记格式 | 中 | 极高 | ⭐⭐⭐⭐⭐ | 4-6h |
| 2. JSON 修复 | 低 | 高 | ⭐⭐⭐⭐ | 2-3h |
| 3. 简化 Prompt | 低 | 高 | ⭐⭐⭐⭐ | 2-4h |
| 4. 流式解析优化 | 中 | 中 | ⭐⭐⭐ | 3-4h |
| 5. 白名单验证 | 低 | 高 | ⭐⭐⭐⭐ | 1-2h |
| 6. 测试补充 | 低 | 中 | ⭐⭐⭐ | 2-3h |

---

## 🚀 推荐实施路线

### 阶段一：快速见效（1-2 天）
1. ✅ 添加 JSON 修复机制
2. ✅ 实现白名单验证
3. ✅ 补充核心测试用例

### 阶段二：核心优化（3-5 天）
1. ✅ 实现简化标记格式
2. ✅ 精简 Prompt 长度
3. ✅ 优化流式解析

### 阶段三：完善提升（1 周+）
1. ✅ A/B 测试两种格式
2. ✅ 收集用户反馈
3. ✅ 持续优化

---

## 📝 具体实施建议

### 立即可做（30 分钟内）

**1. 添加 JSON 修复到现有代码：**

```python
# 在 toolcall_enhanced.py 中添加
def _repair_json_arguments(text: str) -> str:
    """修复常见 JSON 格式问题"""
    # 复制参考项目的实现
    ...

# 在 _decode_param_value 中使用
def _decode_param_value(raw: str) -> Any:
    cdata = _CDATA_RE.match(raw)
    if cdata:
        value = cdata.group(1)
        try:
            # 先尝试修复
            repaired = _repair_json_arguments(value)
            return json.loads(repaired)
        except:
            return value
    ...
```

**2. 添加工具名称验证：**

```python
# 在 parse_tool_calls_from_text 中添加参数
def parse_tool_calls_from_text(
    text: Optional[str],
    available_tools: Optional[List[str]] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    # ... 解析逻辑
    
    # 验证工具名称
    if available_tools and calls:
        calls = [c for c in calls 
                 if c["function"]["name"] in available_tools]
    
    return content, calls
```

---

## 💡 最佳实践建议

### 从参考项目学习的关键点

1. **简洁优于复杂**
   - 参考项目的格式更简单，但同样有效
   - 考虑提供"简单模式"和"高级模式"

2. **渐进式增强**
   - 先实现核心功能（工作）
   - 再添加高级特性（更好）
   - 最后优化性能（最好）

3. **测试驱动**
   - 参考项目有清晰的测试覆盖
   - 每个功能都有对应测试

4. **文档完善**
   - 参考项目有详细的使用示例
   - 包含多场景演示

---

## 🎯 总结

### 当前项目的优势
✅ 更规范的 DSML 格式（参考 ds2api）
✅ 更强大的防泄露系统
✅ 更完善的 XML 修复机制
✅ 代码围栏保护

### 参考项目的优势
✅ 更简洁的标记格式
✅ JSON 修复机制
✅ 工具名称验证
✅ 更精简的 Prompt

### 建议融合策略
1. **保留当前的技术架构**（状态机、防泄露）
2. **借鉴参考项目的简洁性**（格式、Prompt）
3. **补充参考项目的实用特性**（JSON 修复、验证）

### 预期效果
实施所有优化后：
- ✅ 模型遵守率提升 30-50%
- ✅ 解析成功率提升 20-30%
- ✅ Token 消耗降低 40-60%
- ✅ 用户体验显著提升

---

**生成日期**：2026-06-24
**版本**：v2.0 优化建议
