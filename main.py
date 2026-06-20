import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.middleware import ErrorHandlingMiddleware, RequestLoggingMiddleware
from app.api import auth, tenants, projects, api_keys, plans, usage, billing, alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="多租户 API 用量计费与额度控制服务",
    description="""
    一个完整的多租户 API 用量计费与额度控制后端服务。

    ## 核心功能

    - **租户管理**: 创建和管理租户
    - **项目管理**: 在租户下创建项目
    - **API Key 管理**: 生成、禁用和管理 API Key
    - **套餐管理**: 配置计费套餐和资源额度
    - **用量上报**: 业务系统上报 API 用量事件（支持幂等）
    - **额度控制**: 实时检查和控制资源使用额度
    - **账单管理**: 账单预览、历史查询和周期管理
    - **告警系统**: 用量阈值告警和通知

    ## 异常场景处理

    - 重复事件（幂等键去重）
    - 乱序事件（按请求时间处理）
    - API Key 被禁用后继续上报
    - 套餐中途升级
    - 账期切换
    - 并发上报导致的额度计算错误（数据库行锁）

    ## 告警阈值

    系统默认在用量达到以下阈值时生成告警记录：
    - **80%**: WARNING 级别告警
    - **100%**: CRITICAL 级别告警
    - **120%**: CRITICAL 级别告警
    """,
    version="1.0.0",
    contact={
        "name": "API Support",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
)

app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(api_keys.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")


@app.get("/", tags=["系统"])
async def root():
    return {
        "name": "多租户 API 用量计费与额度控制服务",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "openapi": "/openapi.json"
    }


@app.get("/health", tags=["系统"])
async def health_check():
    return {
        "status": "healthy",
        "timestamp": "UTC"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
