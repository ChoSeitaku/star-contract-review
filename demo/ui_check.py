"""前端界面自动化检查（可选，用于交付前的 UI 冒烟测试）。

使用 Playwright 驱动本机已安装的 Edge / Chrome 逐页访问并截图，
同时收集控制台错误，确认各页面均可正常渲染、调用端各功能模块可见。

前置条件：
    uv pip install --python .venv/Scripts/python.exe playwright   # 复用本机浏览器，无需下载

用法（需先启动后端服务）：
    .venv/Scripts/python.exe demo/ui_check.py
    .venv/Scripts/python.exe demo/ui_check.py --channel chrome --headed
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8003"
SHOT_DIR = Path(__file__).resolve().parent / "screenshots"

PASS = 0
FAIL = 0
FAILURES: list[str] = []
CONSOLE_ERRORS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \033[32m[PASS]\033[0m {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  \033[31m[FAIL]\033[0m {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n\033[36m{title}\033[0m")


def ensure_account() -> tuple[str, str]:
    """确保系统已初始化，返回 (admin_token, reviewer_token)。"""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        client.post("/api/system/init", json={})

        admin = client.post(
            "/api/system/login", json={"username": "admin", "password": "admin123"}
        )
        reviewer = client.post(
            "/api/system/login", json={"username": "reviewer", "password": "reviewer123"}
        )
        admin.raise_for_status()
        reviewer.raise_for_status()
        return admin.json()["token"], reviewer.json()["token"]


def screenshot(page, name: str) -> None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="前端界面自动化检查")
    parser.add_argument("--channel", default="msedge", help="浏览器通道：msedge / chrome")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()

    try:
        admin_token, reviewer_token = ensure_account()
    except Exception as exc:
        print(f"\033[31m无法连接后端服务 {BASE_URL}，请先启动服务：{exc}\033[0m")
        return 1

    # 准备一条已完成任务，便于进入详情页检查各功能模块
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {admin_token}"}
        client.post("/api/tasks/pull", json={"limit": 20}, headers=headers)
        for _ in range(60):
            tasks = client.get("/api/tasks", headers=headers).json()["tasks"]
            if tasks and all(
                item["task_status"] in {"done", "blocked"} for item in tasks
            ):
                break
            time.sleep(1)
        done_task = next((t for t in tasks if t["task_status"] == "done"), tasks[0])

    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, headless=not args.headed)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_console(message):
            if message.type == "error":
                errors.append(message.text)

        page.on("console", on_console)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        storage_key = "scr_token"

        # --- 登录页 -------------------------------------------------------
        section("一、登录页")
        page.goto(f"{BASE_URL}/#/login", wait_until="networkidle")
        check("登录页渲染", page.locator("text=合同审批审查系统").count() > 0)
        check("初始化系统按钮存在", page.locator("text=初始化系统").count() > 0)
        screenshot(page, "01-登录页")

        # 注入管理员会话并进入待办列表
        page.evaluate(
            f"localStorage.setItem('{storage_key}', {admin_token!r});"
            "localStorage.setItem('scr_user', JSON.stringify("
            "{username:'admin',display_name:'系统管理员',role:'admin'}))"
        )

        # --- 待办列表（待办调用模块）--------------------------------------
        section("二、待办列表（待办调用模块）")
        page.goto(f"{BASE_URL}/#/tasks", wait_until="networkidle")
        page.wait_for_timeout(900)
        check("待办列表页渲染", page.locator("text=待办列表").count() > 0)
        check("拉取待办按钮存在", page.locator("button:has-text('拉取待办')").count() > 0)
        check("任务表格存在", page.locator("table.table tbody tr").count() > 0)
        check("状态筛选可用", page.locator(".chip").count() >= 5)
        screenshot(page, "02-待办列表")

        # --- 任务详情（详情查看 / 解析结果 / 规则命中 / 结果处理）---------
        section("三、任务详情（详情查看 / 解析结果 / 规则命中 / 结果处理）")
        page.goto(f"{BASE_URL}/#/tasks/{done_task['id']}", wait_until="networkidle")
        page.wait_for_timeout(1200)
        check("审批信息卡片", page.locator("text=审批信息与附件").count() > 0)
        check("附件表格含校验信息", page.locator("text=sha256 校验").count() > 0)
        check("解析结果卡片", page.locator("text=合同解析结果").count() > 0)
        check("基本信息字段卡片", page.locator(".field-card").count() >= 8)
        check("条款信息卡片", page.locator(".clause-item").count() >= 8)
        check("规则命中卡片", page.locator("text=规则命中").count() > 0)
        check("审查结果卡片", page.locator("text=审查结果与评论回写").count() > 0)
        check("总风险等级展示", page.locator(".risk-hero").count() > 0)
        check("回写内容展示", page.locator(".comment-box").count() > 0)
        check("任务日志表格", page.locator("text=任务日志").count() > 0)
        screenshot(page, "03-任务详情")

        # --- 规则管理 -----------------------------------------------------
        section("四、规则管理")
        page.goto(f"{BASE_URL}/#/rules", wait_until="networkidle")
        page.wait_for_timeout(800)
        check("规则管理页渲染", page.locator("text=规则列表").count() > 0)
        check("规则行数 >= 12", page.locator("table.table tbody tr").count() >= 12)
        check("新增规则按钮存在", page.locator("button:has-text('新增规则')").count() > 0)
        screenshot(page, "04-规则管理")

        # --- 运行日志 -----------------------------------------------------
        section("五、运行日志")
        page.goto(f"{BASE_URL}/#/logs", wait_until="networkidle")
        page.wait_for_timeout(900)
        check("运行日志页渲染", page.locator("text=运行日志").count() > 0)
        check("日志标签页存在", page.locator("text=全链路任务日志").count() > 0)
        screenshot(page, "05-运行日志")

        # --- 系统配置 -----------------------------------------------------
        section("六、系统配置")
        page.goto(f"{BASE_URL}/#/config", wait_until="networkidle")
        page.wait_for_timeout(800)
        check("系统配置页渲染", page.locator("text=配置项").count() > 0)
        check("适配器失败开关存在", page.locator("text=adapter_fail_enabled").count() > 0)
        screenshot(page, "06-系统配置")

        # --- 法务审核人视角（隐藏管理员菜单）------------------------------
        section("七、法务审核人视角")
        page.evaluate(
            f"localStorage.setItem('{storage_key}', {reviewer_token!r});"
            "localStorage.setItem('scr_user', JSON.stringify("
            "{username:'reviewer',display_name:'法务审核人',role:'reviewer'}))"
        )
        page.goto(f"{BASE_URL}/#/tasks", wait_until="networkidle")
        page.wait_for_timeout(900)
        check("法务审核人可访问待办列表", page.locator("text=待办列表").count() > 0)
        check("侧栏隐藏规则管理", page.locator(".sidebar-nav >> text=规则管理").count() == 0)
        check("侧栏隐藏系统配置", page.locator(".sidebar-nav >> text=系统配置").count() == 0)
        screenshot(page, "07-法务审核人视角")

        browser.close()

    # --- 控制台错误 -------------------------------------------------------
    section("八、控制台错误检查")
    check("无控制台错误", len(errors) == 0, "; ".join(errors[:3]))

    section("自检结果汇总")
    total = PASS + FAIL
    if FAILURES:
        print("  失败项：")
        for item in FAILURES:
            print(f"    - {item}")
    print(f"  通过 \033[32m{PASS}\033[0m / {total}")
    print(f"  截图目录：{SHOT_DIR}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
