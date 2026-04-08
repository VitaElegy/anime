# NicoTracker 测试套件

## 文件结构

```
tests/
├── README.md           # 本文件
├── CHECKLIST.md        # 89 项功能测试 checklist（含前后端对应关系）
├── test_all_apis.py    # 自动化测试脚本（模拟前端调用后端）
└── test_report.json    # 测试执行后自动生成的 JSON 报告
```

## 运行测试

### 前置条件
```bash
pip install httpx websockets
```

### 执行
```bash
# 确保后端已启动 (默认 http://localhost:8000)
python tests/test_all_apis.py

# 指定后端地址
python tests/test_all_apis.py --base http://localhost:8000

# 详细输出
python tests/test_all_apis.py --verbose
```

### 覆盖范围
- **35 个后端 API 接口** 全部测试
- **10 种 WebSocket 消息类型** 测试（需要 websockets 库）
- **前端 → 后端调用链** 完全一致的参数传递
- **边际条件**: 空参数、超范围参数、不存在的资源、重复操作
- **协议验证**: HTTP 状态码、JSON 结构、SSE 事件格式、WebSocket 握手

### 测试报告
执行后自动生成 `test_report.json`，包含每条测试的通过/失败状态和耗时。
