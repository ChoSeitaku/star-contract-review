#!/usr/bin/env bash
# ==========================================================================
#  合同审批审查系统 - 一键启动（Linux / macOS / Git Bash）
#  首次运行会自动安装后端依赖、生成示例合同并构建前端
# ==========================================================================
set -e

cd "$(dirname "$0")"

# Windows 的虚拟环境使用 Scripts/，类 Unix 使用 bin/
if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    echo "[错误] 未找到虚拟环境，请先执行: python -m venv .venv"
    exit 1
fi

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

echo
echo "============================================================"
echo "  合同审批审查系统"
echo "============================================================"
echo

# ---- 1. 后端依赖 ----
echo "[1/4] 检查后端依赖..."
if ! "$PY" -c "import fastapi, uvicorn, docx, pymupdf, PIL" >/dev/null 2>&1; then
    echo "      正在安装后端依赖..."
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$PY" -e .
    else
        "$PY" -m pip install -e .
    fi
fi
echo "      后端依赖就绪"

# ---- 2. 示例合同 ----
echo "[2/4] 检查示例合同文件..."
if [ ! -f "examples/contracts/software_dev_contract.docx" ]; then
    echo "      正在生成示例合同..."
    "$PY" scripts/generate_examples.py
else
    echo "      示例合同已存在"
fi

# ---- 3. 前端构建 ----
echo "[3/4] 检查前端构建产物..."
if [ ! -f "frontend/dist/index.html" ]; then
    echo "      未找到 frontend/dist，正在构建前端..."
    pushd frontend >/dev/null
    if [ ! -d "node_modules" ]; then
        echo "      安装前端依赖..."
        npm install --no-audit --no-fund
    fi
    npm run build
    popd >/dev/null
else
    echo "      前端产物已存在"
fi

# ---- 4. 启动服务 ----
echo "[4/4] 启动后端服务..."
echo
echo "      访问地址: http://127.0.0.1:8003"
echo "      接口文档: http://127.0.0.1:8003/api/docs"
echo "      默认账户: admin / admin123      （系统管理员）"
echo "                reviewer / reviewer123（法务审核人）"
echo "      首次使用请在登录页点击「初始化系统」"
echo
echo "      按 Ctrl+C 停止服务"
echo

"$PY" -m app.main
