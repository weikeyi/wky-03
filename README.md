# 多租户 API 用量计费与额度控制服务

一个完整的多租户 API 用量计费与额度控制后端服务，基于 FastAPI + SQLAlchemy 构建，提供完整的 RESTful API 接口。

> **说明**：本项目为纯后端服务，不包含前端代码。如需前端界面，可基于 OpenAPI 规范（见 `/openapi.json` 或 `/docs`）对接。

## 功能特性

### 核心功能
- **租户管理**：多租户架构，支持创建和管理多个租户
- **项目管理**：在租户下创建和管理项目
- **API Key 管理**：安全的 API Key 生成（bcrypt 哈希存储）、禁用和管理
- **套餐管理**：灵活的计费套餐配置，支持多种资源类型
- **用量上报**：支持业务系统上报 API 用量事件（支持幂等键去重）
- **额度控制**：实时检查和控制资源使用额度
- **账单管理**：账单预览、历史查询和周期管理
- **告警系统**：用量阈值告警和通知

### 异常场景处理
- **重复事件**：通过幂等键 + 数据库唯一约束双重去重，且匹配租户/项目/Key 才判定为重复
- **乱序事件**：按请求时间（request_time）归属到正确账期
- **API Key 禁用**：禁用后的 API Key 无法继续上报，也无法重放历史事件
- **套餐升级**：通过 effective_from/effective_to 时间范围确定事件适用套餐
- **账期切换**：日/月账期自动切换，不同周期独立聚合
- **并发安全**：`SELECT FOR UPDATE` 行级锁防止并发上报额度计算错误

### 告警阈值
- **80%**：WARNING 级别告警
- **100%**：CRITICAL 级别告警
- **120%**：CRITICAL 级别告警
- 支持自定义告警规则

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
│   ├── database.py            # 数据库连接
│   ├── models.py              # 数据模型（12个核心模型）
│   ├── schemas.py             # Pydantic 验证模式
│   ├── security.py            # 安全认证（bcrypt + JWT）
│   ├── middleware.py          # 中间件（错误处理、日志、限流）
│   ├── api/                   # REST API 路由
│   │   ├── __init__.py
│   │   ├── auth.py            # 认证接口
│   │   ├── tenants.py         # 租户接口
│   │   ├── projects.py        # 项目接口
│   │   ├── api_keys.py        # API Key 接口
│   │   ├── plans.py           # 套餐接口
│   │   ├── usage.py           # 用量接口
│   │   ├── billing.py         # 账单接口
│   │   └── alerts.py          # 告警接口
│   └── services/              # 领域服务
│       ├── __init__.py
│       ├── billing_cycle_service.py   # 账单周期服务
│       ├── usage_service.py           # 用量处理核心服务
│       └── billing_service.py         # 账单服务
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # 测试配置
│   ├── test_usage_service.py         # 核心服务单元测试（18个）
│   ├── test_api_endpoints.py         # API 端点集成测试（31个）
│   └── test_advanced_scenarios.py    # 高级场景测试（跨租户、并发等）
├── main.py                 # FastAPI 应用入口
├── init_db.py              # 数据库初始化脚本（幂等）
├── seed_data.py            # 种子数据脚本（幂等）
├── requirements.txt        # Python 依赖
├── pytest.ini              # pytest 配置
├── .env.example            # 环境变量示例
└── README.md               # 项目文档
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

### 3. 初始化数据库（仅建表，幂等可重复执行）

```bash
python init_db.py
```

### 4. 填充种子数据（幂等可重复执行）

```bash
python seed_data.py
```

执行成功后将创建：
- 管理员用户: `admin` / `admin123`
- 租户管理员: `tenant1_admin` / `tenant123`
- 示例租户、2个项目、3个套餐、3个 API Key、3个告警规则

### 5. 启动服务

```bash
python main.py
```

服务启动后访问：
- **Swagger API 文档**: http://localhost:8000/docs
- **ReDoc API 文档**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json
- **健康检查**: http://localhost:8000/health

## 数据库初始化与迁移方案

本项目采用 SQLAlchemy 声明式模型 + 幂等初始化方案，无需额外迁移工具即可完成数据库搭建，同时为生产环境预留了 Alembic 迁移扩展点。

### 开发/测试环境：一键初始化（幂等）

```bash
# 步骤 1：创建所有数据表（幂等，已存在则跳过）
python init_db.py

# 步骤 2：填充种子演示数据（幂等，已存在则跳过）
python seed_data.py
```

**初始化方案特性**：
- **幂等性**：`init_db.py` 使用 `Base.metadata.create_all()`，仅创建不存在的表；`seed_data.py` 对每类数据做 `query().first()` 存在性检查，重复执行不报错、不产生重复数据
- **可回滚**：删除 `billing.db` 文件后重新执行上述两条命令即可重建数据库
- **输出友好**：内置 Windows 控制台 UTF-8 兼容层，特殊字符自动降级为 ASCII，避免 `UnicodeEncodeError`

### 生产环境：推荐使用 Alembic 迁移

```bash
# 安装 alembic
pip install alembic

# 初始化迁移仓库
alembic init alembic

# 生成首次迁移
alembic revision --autogenerate -m "init"

# 执行迁移
alembic upgrade head
```

迁移配置要点：
- 在 `alembic/env.py` 中设置 `target_metadata = Base.metadata`
- `sqlalchemy.url` 指向生产数据库（建议 PostgreSQL）

### 数据模型校验（验收用）

```bash
# 检查所有模型是否能正确映射到表结构
python -c "
from app.database import Base, engine
from app import models
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f'Total tables: {len(tables)}')
for t in sorted(tables):
    print(f'  - {t}')
"
```

---

## 验收命令总览

本项目为**纯后端服务**，无前端代码，因此不提供 `npm run build` / `npm run type-check` 等前端构建命令。以下为等价的后端验收命令。

### 1. 代码语法校验（等价于 type-check）

```bash
python -m compileall app main.py seed_data.py init_db.py
```

- **作用**：编译所有 `.py` 文件，检查语法错误
- **预期**：无错误输出，所有文件编译成功

### 2. 单元测试 + 集成测试（等价于 npm test）

```bash
python -m pytest tests/ -v
```

- **作用**：运行全部测试用例（当前共 57+ 个）
- **测试覆盖**：
  - 核心服务单元测试（幂等、额度、账期、告警、套餐升级、乱序事件）
  - API 端点集成测试（认证、租户、项目、Key、套餐、用量、账单、告警）
  - 高级场景测试（跨租户重放、禁用 Key 重放、并发超额、初始化幂等）
- **预期**：全部 passed，exit code = 0

### 3. 数据库初始化校验

```bash
python init_db.py
python seed_data.py
python seed_data.py  # 再执行一次验证幂等性
```

- **作用**：验证数据库初始化和种子数据填充的正确性与幂等性
- **预期**：三次命令均成功退出，无报错

### 4. 服务启动与接口文档（可选）

```bash
python main.py
```

启动后访问：
- **健康检查**：http://localhost:8000/health → 返回 `{"status":"ok"}`
- **Swagger UI**：http://localhost:8000/docs → 可交互 API 文档
- **OpenAPI JSON**：http://localhost:8000/openapi.json → 机器可读 API 规范

### 5. 所有验收命令一键执行

```bash
python -m compileall app main.py seed_data.py init_db.py ; echo "compile: OK"
python -m pytest tests/ -v ; echo "pytest: OK"
python init_db.py ; echo "init_db: OK"
python seed_data.py ; echo "seed_data (1st): OK"
python seed_data.py ; echo "seed_data (2nd, idempotent): OK"
```

### 关于前端 / npm

本仓库**不包含前端代码**，不存在以下文件或命令：
- ❌ `package.json`
- ❌ `npm run build` / `npm run type-check` / `npm test`
- ❌ `frontend/` 或 `web/` 目录

前端等价验收方式：
1. 启动后端服务
2. 访问 `http://localhost:8000/docs` 使用 Swagger UI 交互验证所有 API
3. 或使用 Postman / curl 直接调用 REST 接口

## 核心 API 概览

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 认证 | POST | `/api/v1/auth/login` | 登录获取 Token |
| 认证 | GET | `/api/v1/auth/me` | 获取当前用户 |
| 租户 | GET/POST | `/api/v1/tenants` | 租户列表/创建 |
| 项目 | GET/POST | `/api/v1/projects` | 项目列表/创建 |
| API Key | GET/POST | `/api/v1/api-keys` | Key 列表/生成 |
| API Key | POST | `/api/v1/api-keys/{id}/disable` | 禁用 Key |
| 套餐 | GET/POST | `/api/v1/plans` | 套餐列表/创建 |
| 用量 | POST | `/api/v1/usage/report` | 上报用量事件 |
| 用量 | POST | `/api/v1/usage/batch-report` | 批量上报 |
| 用量 | GET | `/api/v1/usage/current` | 当前用量查询 |
| 用量 | GET | `/api/v1/usage/check-quota` | 额度预检查 |
| 账单 | GET | `/api/v1/billing/preview` | 当前周期账单预览 |
| 账单 | GET | `/api/v1/billing/cycles` | 账期列表 |
| 告警 | GET/POST | `/api/v1/alerts/rules` | 告警规则 |
| 告警 | GET | `/api/v1/alerts/records` | 告警记录 |
| 系统 | GET | `/health` | 健康检查 |

完整 API 文档请启动服务后访问 `/docs`。
