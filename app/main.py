"""合同审批审查系统 - 服务入口。

启动时完成建库建表、默认配置与种子数据写入；对外提供工具服务 HTTP 接口
（§1.3.10 工具接口要求）与前端静态资源。
"""

from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, seed
from .routers import logs as logs_router
from .routers import rules as rules_router
from .routers import system as system_router
from .routers import tasks as tasks_router
from .routers import tools as tools_router

API_DESCRIPTION = """
面向企业合同审批场景的自动审查服务。

**完整链路**：待办拉取 → 附件下载 → 文档解析（含扫描件 OCR）→ 规则审查 →
结果保存 → 评论回写审批评论区。

对应需求 §1.3.10 的 7 个工具接口位于 `/api/tools/*`：
`list_pending_contract_approvals`、`get_contract_approval`、
`download_contract_attachment`、`parse_contract_document`、
`run_contract_rules`、`save_review_result`、`write_approval_comment`。
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时建库建表并写入默认配置与种子数据；退出时停止后台任务。"""
    db.init_db()
    config.ensure_default_configs()
    seed.seed_all()
    print("[star-contract-review] 数据库初始化完成")
    yield
    from . import pipeline

    pipeline.shutdown()


app = FastAPI(
    title="合同审批审查系统",
    description=API_DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    return {
        "status": "ok",
        "service": "star-contract-review",
        "version": "1.0.0",
        "db": str(config.DB_PATH),
    }


# 业务路由需在下方 SPA 兜底路由之前注册
app.include_router(system_router.router)
app.include_router(tasks_router.router)
app.include_router(tools_router.router)
app.include_router(rules_router.router)
app.include_router(logs_router.router)


# ---------------------------------------------------------------------------
# 前端静态资源（生产构建产物 frontend/dist，由本服务同端口提供）
# ---------------------------------------------------------------------------
def _mount_frontend() -> None:
    dist = config.FRONTEND_DIST
    index_file = dist / "index.html"

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        if index_file.is_file():
            return FileResponse(str(index_file))
        return JSONResponse(
            {
                "service": "star-contract-review",
                "message": "前端尚未构建，请执行 frontend 目录下的 npm install && npm run build",
                "api_docs": "/api/docs",
            }
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # 未匹配的 /api/* 保持 JSON 404 语义，其余路径交给前端路由
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "接口不存在"}, status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        if index_file.is_file():
            return FileResponse(str(index_file))
        return JSONResponse({"detail": "前端尚未构建"}, status_code=404)


_mount_frontend()


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8003)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        run()
