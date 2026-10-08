@echo off
chcp 65001 >nul
setlocal

REM ========================================================================
REM  合同审批审查系统 - 一键启动（Windows）
REM  首次运行会自动安装后端依赖、生成示例合同并构建前端
REM ========================================================================

cd /d "%~dp0"

set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [错误] 未找到虚拟环境 %PY%
    echo        请先执行: python -m venv .venv
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   合同审批审查系统
echo ============================================================
echo.

REM ---- 1. 后端依赖 ----
echo [1/4] 检查后端依赖...
"%PY%" -c "import fastapi, uvicorn, docx, pymupdf, PIL" >nul 2>&1
if errorlevel 1 (
    echo       正在安装后端依赖...
    uv pip install --python "%PY%" -e .
    if errorlevel 1 (
        echo [错误] 后端依赖安装失败
        pause
        exit /b 1
    )
)
echo       后端依赖就绪

REM ---- 2. 示例合同 ----
echo [2/4] 检查示例合同文件...
if not exist "examples\contracts\software_dev_contract.docx" (
    echo       正在生成示例合同...
    "%PY%" scripts\generate_examples.py
    if errorlevel 1 (
        echo [错误] 示例合同生成失败
        pause
        exit /b 1
    )
) else (
    echo       示例合同已存在
)

REM ---- 3. 前端构建 ----
echo [3/4] 检查前端构建产物...
if not exist "frontend\dist\index.html" (
    echo       未找到 frontend\dist，正在构建前端...
    pushd frontend
    if not exist "node_modules" (
        echo       安装前端依赖...
        call npm install --no-audit --no-fund
        if errorlevel 1 (
            echo [错误] 前端依赖安装失败，请确认已安装 Node.js
            popd
            pause
            exit /b 1
        )
    )
    call npm run build
    if errorlevel 1 (
        echo [错误] 前端构建失败
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo       前端产物已存在
)

REM ---- 4. 启动服务 ----
echo [4/4] 启动后端服务...
echo.
echo       访问地址: http://127.0.0.1:8003
echo       接口文档: http://127.0.0.1:8003/api/docs
echo       默认账户: admin / admin123      （系统管理员）
echo                 reviewer / reviewer123（法务审核人）
echo       首次使用请在登录页点击「初始化系统」
echo.
echo       按 Ctrl+C 停止服务
echo.

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
"%PY%" -m app.main

endlocal
