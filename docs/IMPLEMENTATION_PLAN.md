# 工具调用优化实施计划

## 📋 项目状态

- **当前版本**：v1.0.0（基于 ds2api 实现）
- **参考项目**：qingdeng888/kimi（简化格式实现）
- **优化目标**：融合两个项目的优势

---

## ✅ 已完成的工作

### 阶段一：ds2api 增强实现（2026-06-24）

1. ✅ Tool Call Anti-Leak System
   - 状态机流式解析
   - 防泄露缓冲机制
   - 部分标记检测

2. ✅ DSML 标记规范化
   - 多格式支持
   - 全角字符转换
   - 迭代规范化

3. ✅ XML 修复机制
   - 缺失包装标签修复
   - 未闭合 CDATA 修复

4. ✅ 代码围栏保护
   - Markdown 代码块检测
   - 防止拦截示例

5. ✅ 测试覆盖
   - 23 个测试用例
   - 82.6% 通过率

6. ✅ 完整文档
   - 技术文档
   - 集成指南
   - 使用示例

**成果文件**：
- `app/api/toolcall_enhanced.py` (455 行)
- `tests/test_toolcall_enhanced.py` (255 行)
- `examples/toolcall_enhanced_examples.py` (178 行)
- `docs/toolcall-enhancement.md`
- `docs/ENHANCEMENT_REPORT.md`

---

## 🎯 待实施优化（基于 qingdeng888/kimi）

### 任务清单

| ID | 任务 | 优先级 | 预估时间 | 状态 |
|----|------|--------|---------|------|
| #2 | 添加 JSON 修复机制 | ⭐⭐⭐⭐ | 2-3h | 📋 待开始 |
| #3 | 实现工具名称白名单验证 | ⭐⭐⭐⭐ | 1-2h | 📋 待开始 |
| #4 | 实现简化标记格式支持 | ⭐⭐⭐⭐⭐ | 4-6h | 📋 待开始 |
| #5 | 精简工具调用 Prompt | ⭐⭐⭐⭐ | 2-4h | 📋 待开始 |

### 任务 #2: 添加 JSON 修复机制

**目标**：提高 JSON 参数解析的容错性

**实现要点**：
```python
def _repair_json(text: str) -> str:
    """尝试修复常见的 JSON 格式问题"""
    repairs = [
        lambda t: t,  # 原始
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t),  # 移除尾部逗号
        lambda t: t.replace("'", '"'),  # 单引号转双引号
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t.replace("'", '"')),  # 组合
    ]
    
    for repair_fn in repairs:
        try:
            repaired = repair_fn(text)
            parsed = json.loads(repaired)
            return json.dumps(parsed, ensure_ascii=False)
        except:
            continue
    return ""
```

**集成位置**：
- `toolcall_enhanced.py::_decode_param_value`
- `toolcall.py::_parse_parameters`

**测试用例**：
```python
def test_json_repair_single_quotes():
    text = "{'city': 'Beijing', 'unit': 'celsius'}"
    assert _repair_json(text) == '{"city": "Beijing", "unit": "celsius"}'

def test_json_repair_trailing_comma():
    text = '{"city": "Beijing",}'
    assert _repair_json(text) == '{"city": "Beijing"}'
```

**预期收益**：
- ✅ 解析成功率提升 10-20%
- ✅ 容忍模型常见 JSON 错误

---

### 任务 #3: 实现工具名称白名单验证

**目标**：防止模型幻觉不存在的工具

**实现要点**：
```python
def parse_tool_calls_from_text(
    text: Optional[str],
    available_tools: Optional[List[str]] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """解析工具调用，支持白名单验证"""
    
    # 现有解析逻辑
    content, calls = _parse_internal(text)
    
    # 白名单验证
    if available_tools:
        validated_calls = []
        for call in calls:
            tool_name = call["function"]["name"]
            if tool_name in available_tools:
                validated_calls.append(call)
            else:
                logger.warning(f"Tool '{tool_name}' not in available list, ignored")
        return content, validated_calls
    
    return content, calls
```

**集成位置**：
- `inject_tool_call_context` - 提取工具名称列表传递
- `parse_tool_calls_from_text` - 添加验证逻辑

**测试用例**：
```python
def test_tool_name_validation():
    text = '<tool_calls><invoke name="unknown_tool">...</invoke></tool_calls>'
    available = ["get_weather", "search"]
    _, calls = parse_tool_calls_from_text(text, available)
    assert len(calls) == 0  # unknown_tool 被过滤
```

**预期收益**：
- ✅ 提高安全性
- ✅ 避免无效工具调用

---

### 任务 #4: 实现简化标记格式支持

**目标**：提供更易于模型遵守的简化格式

**实现要点**：

1. **定义简化格式**：
```python
SIMPLE_FORMAT = """
[TOOL_CALL]
{
  "name": "get_weather",
  "arguments": {
    "city": "Beijing",
    "unit": "celsius"
  }
}
[/TOOL_CALL]
"""
```

2. **更新 Prompt 生成器**：
```python
def build_tool_prompt_block(
    tools: Optional[List[Any]],
    tool_choice: str = "auto",
    format_style: str = "simple"  # 新增参数
) -> str:
    """构建工具调用提示词"""
    
    if format_style == "simple":
        return _build_simple_format_prompt(tools, tool_choice)
    else:
        return _build_dsml_format_prompt(tools, tool_choice)
```

3. **扩展解析器**：
```python
def parse_tool_calls_from_text(text: str) -> Tuple[str, List[Dict]]:
    """支持多种格式解析"""
    
    # 尝试简化格式
    result = _parse_simple_format(text)
    if result:
        return result
    
    # 尝试 DSML 格式
    result = _parse_dsml_format(text)
    if result:
        return result
    
    # 其他格式...
    return text, []
```

**配置选项**：
```python
# .env
TOOL_CALL_FORMAT=simple  # 或 dsml
```

**测试用例**：
```python
def test_simple_format_parsing():
    text = '''
    Let me check.
    [TOOL_CALL]
    {"name": "get_weather", "arguments": {"city": "Beijing"}}
    [/TOOL_CALL]
    '''
    content, calls = parse_tool_calls_from_text(text)
    assert content.strip() == "Let me check."
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_weather"
```

**预期收益**：
- ✅ 模型遵守率提升 30-50%
- ✅ 更简洁的格式
- ✅ 兼容性保持

---

### 任务 #5: 精简工具调用 Prompt

**目标**：减少 Prompt 长度，降低 token 消耗

**当前 Prompt 分析**：
- 总长度：~200 行
- 双语说明：中英文重复
- 规则说明：7 条详细规则
- 示例数量：1 个正确 + 3 个错误

**优化方案**：

```python
def build_tool_prompt_block_v2(tools, tool_choice="auto"):
    """精简版工具 Prompt"""
    
    tool_list = _format_tool_list(tools)
    
    return f"""# 可用工具

{tool_list}

## 调用方式

需要使用工具时，按以下格式输出：

[TOOL_CALL]
{{"name": "工具名", "arguments": {{"参数": "值"}}}}
[/TOOL_CALL]

要点：
1. 参数必须是有效 JSON
2. 工具调用放在回复最后
3. 可调用多个工具

{_build_choice_hint(tool_choice)}
"""
```

**对比**：

| 指标 | 当前版本 | 优化版本 | 改善 |
|------|---------|---------|------|
| 总行数 | ~200 | ~80 | -60% |
| Token 数 | ~500 | ~200 | -60% |
| 规则数 | 7 | 3 | -57% |
| 示例数 | 4 | 1 | -75% |

**测试验证**：
- 确保精简后模型仍能正确调用工具
- A/B 测试对比遵守率

**预期收益**：
- ✅ Token 消耗减少 60%
- ✅ 模型理解更快
- ✅ 响应速度提升

---

## 📊 实施进度跟踪

### 阶段一：快速见效（完成度：0%）

- [ ] 任务 #2: JSON 修复机制（2-3h）
- [ ] 任务 #3: 白名单验证（1-2h）
- [ ] 补充测试用例（2h）

**目标**：1-2 天内完成
**预期收益**：解析成功率 +15%

### 阶段二：核心优化（完成度：0%）

- [ ] 任务 #4: 简化格式支持（4-6h）
- [ ] 任务 #5: 精简 Prompt（2-4h）
- [ ] 流式解析优化（3-4h）

**目标**：3-5 天内完成
**预期收益**：模型遵守率 +30%，Token -60%

### 阶段三：完善提升（计划中）

- [ ] A/B 测试两种格式
- [ ] 收集生产环境反馈
- [ ] 性能基准测试
- [ ] 持续优化迭代

**目标**：持续进行
**预期收益**：整体体验显著提升

---

## 🔍 质量保证

### 测试策略

1. **单元测试**
   - 每个新功能对应测试用例
   - 目标覆盖率：90%+

2. **集成测试**
   - 完整工具调用流程
   - 多轮对话场景

3. **回归测试**
   - 确保原有功能正常
   - 运行所有现有测试

4. **性能测试**
   - Token 消耗对比
   - 解析速度测量

### 验收标准

✅ **功能完整性**
- 所有新功能正常工作
- 现有功能无回退

✅ **测试覆盖**
- 新增测试通过率 100%
- 整体覆盖率 ≥ 85%

✅ **性能指标**
- Token 消耗减少 ≥ 40%
- 解析成功率提升 ≥ 15%
- 模型遵守率提升 ≥ 25%

✅ **文档完善**
- 更新技术文档
- 更新集成指南
- 添加新示例

---

## 📝 开发指南

### 开发环境设置

```bash
# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -e .

# 运行测试
pytest tests/test_toolcall_enhanced.py -v
```

### 代码规范

1. **命名约定**
   - 函数：snake_case
   - 类：PascalCase
   - 常量：UPPER_CASE

2. **注释要求**
   - 所有公共函数必须有 docstring
   - 复杂逻辑添加行内注释
   - 保持注释与代码同步

3. **测试要求**
   - 新功能必须有测试
   - 测试命名：test_<功能描述>
   - 使用清晰的断言

### 提交规范

```bash
# 功能开发
git commit -m "feat(tool-call): 添加 JSON 修复机制"

# Bug 修复
git commit -m "fix(tool-call): 修复流式解析失败问题"

# 文档更新
git commit -m "docs(tool-call): 更新优化建议文档"

# 测试补充
git commit -m "test(tool-call): 添加 JSON 修复测试用例"
```

---

## 🎯 成功指标

### 短期目标（1-2 周）

- ✅ 完成所有快速见效优化
- ✅ 测试通过率达到 90%
- ✅ 文档更新完成

### 中期目标（1 个月）

- ✅ 完成所有核心优化
- ✅ 生产环境验证
- ✅ 性能指标达成

### 长期目标（3 个月）

- ✅ 用户反馈良好
- ✅ 持续迭代优化
- ✅ 社区贡献活跃

---

## 📚 参考资源

- [ds2api 项目](https://github.com/CJackHwang/ds2api)
- [qingdeng888/kimi 项目](https://github.com/qingdeng888/kimi)
- [优化建议文档](./OPTIMIZATION_SUGGESTIONS.md)
- [增强实现报告](./ENHANCEMENT_REPORT.md)

---

**创建日期**：2026-06-24
**最后更新**：2026-06-24
**负责人**：开发团队
**审核人**：技术负责人
