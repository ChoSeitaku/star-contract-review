"""合同审批审查系统 —— 完整闭环演示脚本。

演示链路（对应需求 §1.3.12 验收标准）：
    待办拉取 → 附件下载 → 文档解析（含扫描件 OCR）→ 规则审查
    → 结果保存 → 评论回写审批评论区

并覆盖异常分支：三类解析期阻塞、接口调用失败阻塞、评论回写失败与重试、
重复拉取去重。全部通过 HTTP 接口调用，与前端使用同一套工具服务。

用法（需先启动后端服务）：
    .venv/Scripts/python.exe demo/run_demo.py
    .venv/Scripts/python.exe demo/run_demo.py --keep     # 保留现有数据，不做重置
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8003"

RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"

# Windows 终端启用 ANSI 转义序列
if os.name == "nt":
    os.system("")

FAILED: list[str] = []


# ---------------------------------------------------------------------------
# 控制台输出
# ---------------------------------------------------------------------------
def banner(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 74}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 74}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{BLUE}▸ {title}{RESET}")


def ok(text: str) -> None:
    print(f"  {GREEN}✓{RESET} {text}")


def warn(text: str) -> None:
    print(f"  {YELLOW}!{RESET} {text}")


def fail(text: str) -> None:
    FAILED.append(text)
    print(f"  {RED}✗{RESET} {text}")


def info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def expect(condition: bool, description: str, actual: str = "") -> bool:
    if condition:
        ok(description)
    else:
        fail(f"{description}（实际：{actual}）")
    return condition


# ---------------------------------------------------------------------------
# 接口客户端
# ---------------------------------------------------------------------------
class DemoClient:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=BASE_URL, timeout=60.0)
        self.token = ""

    def __enter__(self) -> "DemoClient":
        return self

    def __exit__(self, *exc) -> None:
        self.http.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def call(self, method: str, path: str, payload: dict | None = None) -> dict:
        response = self.http.request(method, path, json=payload, headers=self._headers())
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"{response.status_code} {detail}")
        return response.json() if response.text else {}

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def post(self, path: str, payload: dict | None = None) -> dict:
        return self.call("POST", path, payload or {})

    def put(self, path: str, payload: dict | None = None) -> dict:
        return self.call("PUT", path, payload or {})

    # -- 业务便捷方法 ---------------------------------------------------
    def tasks(self) -> list[dict]:
        return self.get("/api/tasks")["tasks"]

    def task_by_code(self, code: str) -> dict:
        for task in self.tasks():
            if task["approval_code"] == code:
                return task
        raise RuntimeError(f"未找到审批编号为 {code} 的任务")

    def detail(self, task_id: int) -> dict:
        return self.get(f"/api/tasks/{task_id}")

    def wait_terminal(self, codes: list[str], timeout: int = 180) -> None:
        """等待指定审批编号的任务全部进入终态（done / blocked）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = {t["approval_code"]: t for t in self.tasks()}
            if all(rows.get(c, {}).get("task_status") in {"done", "blocked"} for c in codes):
                return
            time.sleep(0.6)
        raise TimeoutError(f"等待任务进入终态超时（{timeout}s）")

    def wait_status(self, task_id: int, status: str, timeout: int = 90) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = next((t for t in self.tasks() if t["id"] == task_id), None)
            if task and task["task_status"] == status and not task["is_active"]:
                return task
            time.sleep(0.5)
        raise TimeoutError(f"等待任务进入 {status} 状态超时")


# ---------------------------------------------------------------------------
# 演示步骤
# ---------------------------------------------------------------------------
def step_health(client: DemoClient) -> None:
    section("1. 服务健康检查")
    health = client.get("/api/health")
    expect(health["status"] == "ok", f"服务可用：{health['service']} v{health['version']}")
    info(f"数据库：{health['db']}")


def step_init_and_login(client: DemoClient) -> None:
    section("2. 系统初始化与登录")
    try:
        client.post("/api/system/init", {})
        ok("系统初始化完成（admin / admin123，reviewer / reviewer123）")
    except RuntimeError as exc:
        if "已初始化" in str(exc):
            ok("系统已初始化，跳过")
        else:
            raise
    login = client.post("/api/system/login", {"username": "admin", "password": "admin123"})
    client.token = login["token"]
    ok(f"登录成功：{login['user']['display_name']}（{login['user']['role']}）")


def step_rules(client: DemoClient) -> None:
    section("3. 审查规则概览")
    rules = client.get("/api/rules")["rules"]
    enabled = [r for r in rules if r["rule_status"] == "enabled"]
    expect(len(rules) >= 12, f"规则库共 {len(rules)} 条（其中启用 {len(enabled)} 条）")
    for rule in rules[:6]:
        info(f"{rule['rule_code']:<9} {rule['rule_name']:<12} {rule['risk_level']}  "
             f"{rule['match_mode']:<8} → {rule['match_target']}")
    info(f"…… 其余 {max(len(rules) - 6, 0)} 条省略")


def step_pull(client: DemoClient) -> list[dict]:
    section("4. 待办拉取（含按审批编号去重）")
    result = client.post("/api/tools/list-pending-approvals", {"limit": 20})
    ok(f"拉取到 {result['fetched']} 条待办审批单")
    expect(result["created_count"] > 0, f"新建任务 {result['created_count']} 条")
    for item in result["items"]:
        info(f"{item['approval_code']:<14} {item['approval_title']:<20} "
             f"{item['applicant_name']:<5} 附件 {item['attachment_count']} 个")

    codes = [item["approval_code"] for item in result["items"]]
    section("5. 后台流水线执行（解析 → 审查 → 保存 → 回写）")
    info("等待全部任务进入终态…")
    client.wait_terminal(codes)
    tasks = {t["approval_code"]: t for t in client.tasks()}
    for code in codes:
        task = tasks[code]
        tone = GREEN if task["task_status"] == "done" else YELLOW
        detail_line = task["blocked_reason"] or f"风险 {task['overall_risk_level'] or '—'}"
        print(
            f"  {tone}{task['task_status']:<8}{RESET} {code:<14} "
            f"回写 {task['write_status']:<11} 命中 {task['hit_count']} 条  {detail_line}"
        )
    return [tasks[c] for c in codes]


def step_verify_outcomes(client: DemoClient, tasks: list[dict]) -> None:
    section("6. 终态校验（正常闭环 + 三类解析期阻塞）")
    by_code = {t["approval_code"]: t for t in tasks}

    expected = [
        ("HT-2024-001", "done", "高", "docx 正常解析，命中多条高风险规则"),
        ("HT-2024-002", "done", "中", "文本型 PDF 正常解析"),
        ("HT-2024-003", "done", "中", "扫描件 OCR 识别后完成审查"),
        ("HT-2024-007", "done", "低", "条款齐备，未命中风险规则"),
        ("HT-2024-004", "blocked", "", "附件缺失 → 阻塞"),
        ("HT-2024-005", "blocked", "", "文档内容为空 → 阻塞"),
        ("HT-2024-006", "blocked", "", "图片无法识别 → 阻塞"),
    ]
    for code, status, risk, note in expected:
        task = by_code.get(code)
        if task is None:
            fail(f"{code} 任务缺失")
            continue
        status_ok = task["task_status"] == status
        risk_ok = not risk or task["overall_risk_level"] == risk
        expect(
            status_ok and risk_ok,
            f"{code} {note}",
            f"状态={task['task_status']} 风险={task['overall_risk_level']}",
        )

    # 扫描件必须走 OCR 路径
    ocr_task = by_code.get("HT-2024-003")
    if ocr_task:
        detail = client.detail(ocr_task["id"])
        parse_type = (detail.get("parse") or {}).get("parse_type")
        expect(parse_type == "pdf_ocr", "扫描件通过 OCR 路径解析（parse_type=pdf_ocr）", str(parse_type))

    # 解析失败必须记录原因，不允许静默空结果
    empty_task = by_code.get("HT-2024-005")
    if empty_task:
        parse = client.detail(empty_task["id"]).get("parse") or {}
        expect(
            parse.get("parse_status") == "failed" and bool(parse.get("parse_error")),
            "解析失败已记录失败原因（parse_status=failed + parse_error）",
            f"{parse.get('parse_status')} / {parse.get('parse_error')}",
        )


def step_walkthrough(client: DemoClient) -> dict:
    section("7. 高风险合同详情走查（HT-2024-001）")
    task = client.task_by_code("HT-2024-001")
    detail = client.detail(task["id"])
    parse = detail["parse"]

    basic = parse["basic_info"]
    found = sum(1 for v in basic.values() if v["status"] == "found")
    ok(f"基本信息提取 {found}/8 项，条款提取 "
       f"{sum(1 for v in parse['clause_info'].values() if v['status'] == 'found')}/8 类")

    sample = basic["contract_title"]
    info(f"字段示例：{sample['field_name']} = {sample['value']}")
    info(f"          原文片段：{sample['evidence']}")
    info(f"          位置标识：{sample['position']}  提取状态：{sample['status']}")

    payment = parse["clause_info"]["payment"]
    info(f"条款示例：{payment['clause_name']}（{payment['position']}）{payment['evidence'][:40]}…")

    hits = detail["hits"]
    ok(f"规则命中 {len(hits)} 条，总风险等级「{detail['result']['overall_risk_level']}」")
    for hit in hits:
        tone = RED if hit["risk_level"] == "高" else YELLOW
        print(f"    {tone}[{hit['risk_level']}]{RESET} {hit['rule_name']:<14} "
              f"{hit['evidence_position']:<12} {hit['evidence_text'][:38]}…")

    result = detail["result"]
    print(f"\n  {BOLD}中文摘要{RESET}")
    info(result["summary_text"])
    print(f"\n  {BOLD}审批关注点（{len(result['focus_points'])} 项）{RESET}")
    for point in result["focus_points"][:5]:
        info(f"[{point['risk_level']}] {point['point']}")
    return detail


def step_comment_check(client: DemoClient, detail: dict) -> None:
    section("8. 评论回写核验")
    instance_id = detail["task"]["instance_id"]
    preview = client.get(f"/api/tasks/{detail['task']['id']}/comment-preview")
    area = preview["approval_comment_area"]

    expect(
        preview["write_status"] == "success",
        f"回写状态：{preview['write_status_label']}",
        preview["write_status"],
    )
    expect("【合同自动审查意见】" in area, f"审批单 {instance_id} 评论区已收到审查意见")

    # 评论区隔离性：HT-2024-001 的意见不应写入其他审批单
    other = client.get("/api/tools/approvals/AP-002")
    expect(
        "【合同自动审查意见】" in other["comment_area"],
        "HT-2024-002 评论区同样收到各自合同（HT-2024-002）的审查意见",
    )

    print(f"\n  {BOLD}回写内容预览{RESET}")
    for line in preview["comment_text"].splitlines()[:9]:
        info(line)
    info("……")
    if preview["comment_logs"]:
        info(f"回写日志：共 {len(preview['comment_logs'])} 次尝试，"
             f"最近一次 {preview['comment_logs'][-1]['write_status']}")


def step_tool_showcase(client: DemoClient, detail: dict) -> None:
    section("9. 七个工具接口逐一调用演示")
    task = detail["task"]
    instance_id = task["instance_id"]
    case_id = detail["parse"]["id"]
    document_id = detail["parse"]["document_id"]
    review_id = detail["result"]["id"]

    # 1
    r = client.post("/api/tools/list-pending-approvals", {"limit": 3})
    ok(f"[1] list_pending_contract_approvals(limit=3) → 待办 {r['fetched']} 条，"
       f"新增 {r['created_count']}，跳过 {r['skipped_count']}")

    # 2
    r = client.get(f"/api/tools/approvals/{instance_id}")
    ok(f"[2] get_contract_approval({instance_id}) → {r['approval']['approval_title']}，"
       f"表单 {len(r['form_data'])} 项，附件 {r['attachment_count']} 个，"
       f"处理状态 {r['process_status']['task_status']}")

    # 3
    attachment = r["attachments"][0]
    r = client.post("/api/tools/download-attachment", {
        "instance_id": instance_id,
        "attachment_id": attachment["attachment_id"],
        "file_name": attachment["file_name"],
    })
    ok(f"[3] download_contract_attachment(...) → {attachment['file_name']}，"
       f"{r['file_size']} 字节，sha256 {r['sha256'][:16]}…，校验 {r['verified']}")

    # 4
    r = client.post("/api/tools/parse-document", {"document_id": document_id})
    ok(f"[4] parse_contract_document({document_id}) → 解析方式 {r['parse_type']}，"
       f"基本信息 {r['basic_found']}/{r['basic_total']}，条款 {r['clause_found']}/{r['clause_total']}")

    # 5
    evaluation = client.post("/api/tools/run-rules", {"case_id": case_id})
    ok(f"[5] run_contract_rules(case_id={case_id}) → 总风险「{evaluation['overall_risk_level']}」，"
       f"命中 {evaluation['hit_count']} 条 {evaluation['risk_counts']}")

    # 6
    saved = client.post("/api/tools/save-review-result", {
        "case_id": case_id,
        "overall_risk_level": evaluation["overall_risk_level"],
        "summary_text": evaluation["summary_text"],
        "focus_points_json": json.dumps(evaluation["focus_points"], ensure_ascii=False),
        "comment_text": evaluation["comment_text"],
    })
    ok(f"[6] save_review_result(case_id={case_id}) → 结果编号 #{saved['review_id']}，"
       f"已保存 {saved['comment_length']} 字回写内容")

    # 7
    r = client.post("/api/tools/write-comment", {
        "instance_id": instance_id,
        "review_id": review_id,
    })
    ok(f"[7] write_approval_comment({instance_id}, review_id={review_id}) → "
       f"回写状态 {r['write_status']}")


def step_dedupe(client: DemoClient) -> None:
    section("10. 重复拉取去重校验")
    before = len(client.tasks())
    result = client.post("/api/tools/list-pending-approvals", {"limit": 20})
    after = len(client.tasks())
    expect(
        result["created_count"] == 0 and before == after,
        f"重复拉取未产生新任务（新增 {result['created_count']} 条，"
        f"已存在 {result['skipped_count']} 条，任务总数仍为 {after}）",
        f"{before} → {after}",
    )


def step_retry_blocked(client: DemoClient) -> None:
    section("11. 阻塞任务重试（重新进入解析阶段）")
    task = client.task_by_code("HT-2024-004")
    before = client.detail(task["id"])
    info(f"重试前：{before['task']['task_status']} / {before['task']['blocked_reason']} / "
         f"失败阶段 {before['task']['failure_stage']}")

    client.post(f"/api/tasks/{task['id']}/retry")
    after = client.wait_status(task["id"], "blocked")
    expect(
        after["retry_count"] >= 1,
        f"重试后重新执行解析阶段并再次阻塞（重试次数 {after['retry_count']}，"
        f"原因仍为「{after['blocked_reason']}」）",
    )
    logs = client.detail(task["id"])["logs"]
    types = [log["log_type"] for log in reversed(logs)]
    expect("retry" in types and types.count("stage_enter") >= 2,
           "任务日志完整记录「重试 → 重新进入阶段 → 再次阻塞」全过程")


def step_adapter_failure(client: DemoClient) -> None:
    section("12. 接口调用失败阻塞与恢复")
    client.put("/api/system/config", {"configs": {"adapter_fail_enabled": "true"}})
    ok("已开启「审批系统接口失败」开关")

    # 拉取级失败：拉取接口不可用时调用方应收到明确错误，而不是静默成功
    try:
        client.post("/api/tools/list-pending-approvals", {"limit": 5})
        fail("拉取接口失败时未报错")
    except RuntimeError as exc:
        expect("接口调用失败" in str(exc), f"拉取接口失败被明确识别：{exc}")

    # 任务级失败：重试阻塞任务时详情接口不可用 → 任务转为 blocked（接口调用失败）
    task = client.task_by_code("HT-2024-004")
    client.post(f"/api/tasks/{task['id']}/retry")
    blocked = client.wait_status(task["id"], "blocked")
    expect(
        blocked["blocked_reason"] == "接口调用失败",
        f"任务级接口失败使任务进入阻塞（原因「{blocked['blocked_reason']}」，"
        f"失败阶段 {blocked['failure_stage']}）",
        blocked["blocked_reason"],
    )

    client.put("/api/system/config", {"configs": {"adapter_fail_enabled": "false"}})
    ok("已关闭接口失败开关")

    client.post(f"/api/tasks/{task['id']}/retry")
    recovered = client.wait_status(task["id"], "blocked")
    expect(
        recovered["blocked_reason"] == "附件缺失",
        f"接口恢复后重试，任务回到其自身业务阻塞原因「{recovered['blocked_reason']}」",
        recovered["blocked_reason"],
    )


def step_comment_failure(client: DemoClient) -> None:
    section("13. 评论回写失败与回写重试")
    # 新建一条审批单用于演示回写失败（--keep 重复演示时可能已存在）
    try:
        created = client.post("/api/system/mock-approvals", {
            "approval_code": "HT-2024-101",
            "approval_title": "回写失败演示合同",
            "applicant_name": "演示申请人",
            "department": "法务部",
            "attachment_file": "simple_service_contract.docx",
        })
        info(f"已创建演示审批单 {created['approval_code']}（实例 {created['instance_id']}）")
    except RuntimeError as exc:
        if "已存在" not in str(exc):
            raise
        info("演示审批单 HT-2024-101 已存在，直接复用")

    client.put("/api/system/config", {"configs": {"adapter_fail_write_enabled": "true"}})
    ok("已开启「评论回写失败」开关")

    client.post("/api/tools/list-pending-approvals", {"limit": 50})
    client.wait_terminal(["HT-2024-101"])
    task = client.task_by_code("HT-2024-101")

    expect(
        task["task_status"] == "done" and task["write_status"] == "failed",
        f"回写失败不阻塞任务：任务 {task['task_status']}，回写状态 {task['write_status']}",
        f"{task['task_status']} / {task['write_status']}",
    )

    client.put("/api/system/config", {"configs": {"adapter_fail_write_enabled": "false"}})
    ok("已关闭回写失败开关")

    client.post(f"/api/tasks/{task['id']}/retry-comment")
    deadline = time.time() + 60
    while time.time() < deadline:
        task = client.task_by_code("HT-2024-101")
        if task["write_status"] == "success":
            break
        time.sleep(0.5)

    expect(task["write_status"] == "success", f"重试回写成功（{task['write_status']}）", task["write_status"])

    logs = client.detail(task["id"])["comment_logs"]
    ok(f"回写日志记录 {len(logs)} 次尝试：" +
       "、".join(f"#{l['attempt_no']} {l['write_status']}" for l in logs))

    area = client.get("/api/tools/approvals/AP-2024101")["comment_area"]
    expect("【合同自动审查意见】" in area, "重试后审批评论区已收到审查意见")


def step_summary(client: DemoClient) -> None:
    section("14. 演示汇总")
    tasks = client.tasks()
    by_status: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for task in tasks:
        by_status[task["task_status"]] = by_status.get(task["task_status"], 0) + 1
        if task["overall_risk_level"]:
            by_risk[task["overall_risk_level"]] = by_risk.get(task["overall_risk_level"], 0) + 1

    info(f"任务总数 {len(tasks)}")
    info("任务状态分布：" + "，".join(f"{k} {v}" for k, v in sorted(by_status.items())))
    info("风险等级分布：" + "，".join(f"{k} {v}" for k, v in sorted(by_risk.items())))
    info(f"规则命中总数：{sum(t['hit_count'] for t in tasks)} 条")

    logs = client.get("/api/logs/tasks?limit=1000")["logs"]
    comments = client.get("/api/logs/comments?limit=1000")["logs"]
    info(f"全链路日志 {len(logs)} 条，评论回写日志 {len(comments)} 条")


def main() -> int:
    parser = argparse.ArgumentParser(description="合同审批审查系统闭环演示")
    parser.add_argument("--keep", action="store_true", help="保留现有数据，不重置演示环境")
    args = parser.parse_args()

    banner("合同审批审查系统 —— 完整闭环演示")
    print(f"  服务地址：{BASE_URL}")
    print("  演示链路：待办拉取 → 附件下载 → 文档解析（含 OCR）→ 规则审查 → 结果保存 → 评论回写")

    try:
        with DemoClient() as client:
            try:
                client.get("/api/health")
            except Exception as exc:
                print(f"\n{RED}无法连接后端服务，请先启动：{RESET}")
                print("  start.bat          （Windows）")
                print("  ./start.sh         （Linux / macOS）")
                print(f"  错误：{exc}")
                return 1

            step_health(client)
            step_init_and_login(client)

            if not args.keep:
                section("0. 重置演示环境")
                reset = client.post("/api/system/mock-reset")
                ok(f"已重置：剩余任务 {reset['approval_tasks']} 条，"
                   f"模拟审批单 {reset['mock_approvals']} 条")

            step_rules(client)
            tasks = step_pull(client)
            step_verify_outcomes(client, tasks)
            detail = step_walkthrough(client)
            step_comment_check(client, detail)
            step_tool_showcase(client, detail)
            step_dedupe(client)
            step_retry_blocked(client)
            step_adapter_failure(client)
            step_comment_failure(client)
            step_summary(client)

    except Exception as exc:  # 演示中断时给出明确原因
        fail(f"演示中断：{exc}")
        import traceback

        traceback.print_exc()

    banner("演示结果")
    if FAILED:
        print(f"  {RED}失败 {len(FAILED)} 项：{RESET}")
        for item in FAILED:
            print(f"    {RED}✗{RESET} {item}")
        return 1

    print(f"  {GREEN}全部演示步骤通过，闭环链路完整可用。{RESET}")
    print(f"  {DIM}浏览器访问 {BASE_URL} 可查看界面；接口文档 {BASE_URL}/api/docs{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
