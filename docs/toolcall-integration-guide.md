# 工具调用增强模块集成指南

## 概述

本指南介绍如何在 Kimi2API 项目中启用参考 ds2api 实现的增强工具调用功能。

## 功能亮点

✅ **防泄露流式解析** - 确保 DSML 标记不会泄露到客户端输出  
✅ **智能格式规范化** - 支持多种 DSML 格式变体  
✅ **部分标记缓冲** - 改进的流式体验，无闪烁  
✅ **代码围栏保护** - 不拦截示例代码中的工具调用  
✅ **自动 XML 修复** - 容忍模型输出的常见错误  

## 快速开始

### 方式一：直接使用增强模块

```python
# 在你的代码中
from app.api import toolcall_enhanced as tc

# 使用增强的 Sieve
sieve = tc.EnhancedToolCallSieve()
text, calls = sieve.push(chunk)

# 使用规范化功能
normalized = tc.normalize_dsml_markup(raw_text)
```

### 方式二：全局替换（推荐生产环境）

修改 `app/api/chat_completions.py`:

```python
# 原来的导入
# from app.api import toolcall

# 改为
from app.api import toolcall_enhanced as toolcall
```

这样所有现有代码无需修改即可使用增强功能。

## 运行示例

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行示例程序
python examples/toolcall_enhanced_examples.py
```

## 运行测试

```bash
# 运行增强模块测试
python -m pytest tests/test_toolcall_enhanced.py -v

# 运行所有测试
python -m pytest tests/ -v
```

## 性能影响

- **CPU 开销**：轻微增加（迭代规范化）
- **内存占用**：略微增加（额外缓冲区）
- **解析准确性**：显著提升
- **用户体验**：明显改善（无标记泄露）

对于大多数场景，性能影响可忽略不计。

## 配置选项

目前增强模块使用默认配置，未来版本将支持：

- 规范化迭代次数限制
- 自定义标记格式
- 调试日志级别

## 兼容性

- ✅ 完全向后兼容原有 `toolcall` 模块
- ✅ 支持所有现有工具调用功能
- ✅ 可与原模块无缝切换

## 故障排查

### 问题：工具调用未被识别

**可能原因**：格式不在支持的变体中

**解决方案**：
```python
# 查看规范化结果
normalized = tc.normalize_dsml_markup(text)
print(f"Normalized: {normalized}")
```

### 问题：流式输出中断

**可能原因**：解析失败，Sieve 状态异常

**解决方案**：
```python
# 检查 Sieve 状态
print(f"Sieve state: {sieve.state}")

# 强制 flush
text, calls = sieve.flush()
```

### 问题：代码示例被拦截

**检查**：
```python
# 验证代码围栏检测
is_in_fence = tc.is_inside_code_fence(text, position)
print(f"In code fence: {is_in_fence}")
```

## 文档

- [完整增强文档](./toolcall-enhancement.md)
- [使用示例](../examples/toolcall_enhanced_examples.py)
- [测试用例](../tests/test_toolcall_enhanced.py)

## 与 ds2api 的关系

本实现参考了 [ds2api](https://github.com/CJackHwang/ds2api) 项目的优秀设计：

- Tool Call Anti-Leak System 概念
- DSML 标记规范化策略
- 部分标记检测算法
- XML 修复机制

感谢 ds2api 团队的开源贡献！

## 后续计划

- [ ] 完善全角字符支持
- [ ] 添加性能基准测试
- [ ] 实现自定义配置接口
- [ ] 考虑 Cython/Rust 加速

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v1.0.0 (2026-06-24)

- 初始实现
- 核心功能完成
- 测试覆盖率 82.6%
