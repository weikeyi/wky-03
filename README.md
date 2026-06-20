# 多租户 API 用量计费与额度控制服务

一个完整的多租户 API 用量计费与额度控制后端服务，基于 FastAPI + SQLAlchemy 构建，提供完整的 RESTful API 接口。

## 功能特性

### 核心功能
- **租户管理**：多租户架构，支持创建和管理多个租户
- **项目管理**：在租户下创建和管理项目
- **API Key 管理**：安全的 API Key 生成、禁用和管理
- **套餐管理**：灵活的计费套餐配置，支持多种资源类型
- **用量上报**：支持业务系统上报 API 用量事件（支持幂等键去重）
- **额度控制**：实时检查和控制资源使用额度
- **账单管理**：账单预览、历史查询和周期管理
- **告警系统**：用量阈值告警和通知

### 异常场景处理
- **重复事件**：通过幂等键去重，确保重复上报不重复计费
- **乱序事件**：按请求时间处理，确保时序正确
- **API Key 禁用**：禁用后的 API Key 无法继续上报
- **套餐升级**：支持套餐中途升级，新旧套餐各自计费
- **账期切换**：日/月账期自动切换
- **并发安全**：数据库行级锁防止并发上报导致额度计算错误

### 告警阈值
- **80%**：WARNING 级别告警
- **100%**：CRITICAL 级别告警
- **120%**：CRITICAL 级别告警

## 技术栈

- **框架**: FastAPI 0.104+
- **ORM**: SQLAlchemy 2.0+
- **数据库**: SQLite (默认) / PostgreSQL / MySQL
- **认证**: JWT (OAuth2)
- **密码加密**: bcrypt
- **测试**: pytest + httpx

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── config.py              # 配置管理
│   ├── database.py          # 数据库连接
│   ├── models.py          # 数据模型
│   ├── schemas.py         # Pydantic 模式
│   ├── security.py      # 安全认证
│   ├── middleware.py    # 中间件
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py      # 认证接口
│   │   ├── tenants.py   # 租户接口
│   │   ├── projects.py  # 项目接口
│   │   ├── api_keys.py  # API Key 接口
│   │   ├── plans.py     # 套餐接口
│   │   ├── usage.py     # 用量接口
│   │   ├── billing.py  # 账单接口
│   │   └── alerts.py    # 告警接口
│   └── services/
│       ├── __init__.py
│       ├── billing_cycle_service.py   # 账单周期服务
│       ├── usage_service.py        # 用量处理服务
│       └── billing_service.py      # 账单服务
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # 测试配置
│   ├── test_usage_service.py   # 核心服务测试
│   └── test_api_endpoints.py   # API 端点测试
├── main.py                    # 应用入口
├── seed_data.py            # 种子数据脚本
├── requirements.txt      # Python 依赖
├── pytest.ini        # pytest 配置
├── .env.example    # 环境变量示例
└── README.md         # 项目文档
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件配置数据库连接等
```

### 3. 初始化数据库和种子数据

```bash
python seed_data.py
```

这会创建：
- 管理员用户: admin / admin123
- 租户管理员: tenant1_admin / tenant123
- 示例租户、项目、套餐、API Key 和告警规则

### 4. 启动服务

```bash
python main.py
```

服务启动后访问：
- API 文档: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json
- 健康检查: http://localhost:8000/health
```

现在让我安装依赖并运行测试来验证项目是否正常工作。

<seed:tool_call><function name="RunCommand"><parameter name="command" string="true">cd "c:\Users\22933\Desktop\trae_maker\solo_0620_task_003_api_billing_quota ; python -m venv venv ; venv\Scripts\python -m pip install --upgrade pip