"""合同审批审查系统 —— 验收自检脚本。

逐项核对需求文档 §1.3 的可验证条目：服务入口、数据表结构、工具接口、
解析字段、审查规则、输出格式、评论回写、异常阻塞与重试、去重与权限。

用法（需先启动后端服务）：
    .venv/Scripts/python.exe demo/verify.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import config  # noqa: E402

BASE_URL = "http://127.0.0.1:8003"
README = BASE_DIR / "README.md"

GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"

if os.name == "nt":
    os.system("")

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  {GREEN}[PASS]{RESET} {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  {RED}[FAIL]{RESET} {name}" + (f"  ({detail})" if detail else ""))
    return condition


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}▸ {title}{RESET}")


# ---------------------------------------------------------------------------
# 需求 §1.3.9 规定的数据表与必需列
# ---------------------------------------------------------------------------
REQUIRED_TABLES: dict[str, set[str]] = {
    "approval_tasks": {
        "id", "approval_code", "approval_title", "applicant_name",
        "task_status", "write_status", "created_at", "updated_at",
    },
    "approval_attachments": {
        "id", "task_id", "file_name", "file_type", "file_path",
        "download_status", "created_at",
    },
    "contract_parses": {
        "id", "task_id", "basic_info_json", "clause_info_json",
        "parse_status", "parse_error", "created_at",
    },
    "review_rules": {
        "id", "rule_code", "rule_name", "risk_level", "rule_status",
        "match_mode", "match_text", "suggestion_text", "updated_at",
    },
    "rule_hits": {
        "id", "task_id", "rule_id", "evidence_text",
        "evidence_position", "hit_status", "created_at",
    },
    "review_results": {
        "id", "task_id", "overall_risk_level", "summary_text",
        "focus_points_json", "comment_text", "created_at",
    },
    "comment_logs": {
        "id", "task_id", "write_status", "write_response_text", "created_at",
    },
    "task_logs": {
        "id", "task_id", "log_level", "log_type", "log_content", "created_at",
    },
}

TOOL_NAMES = (
    "list_pending_contract_approvals",
    "get_contract_approval",
    "download_contract_attachment",
    "parse_contract_document",
    "run_contract_rules",
    "save_review_result",
    "write_approval_comment",
)


# ---------------------------------------------------------------------------
# 各检查分组
# ---------------------------------------------------------------------------
def verify_files() -> None:
    section("一、交付物完整性（§1.3.12 交付形式）")
    check("数据库初始化脚本存在", config.SCHEMA_PATH.is_file(), str(config.SCHEMA_PATH))
    check("示例合同目录存在", config.CONTRACT_DIR.is_dir(), str(config.CONTRACT_DIR))

    contracts = [p for p in config.CONTRACT_DIR.glob("*") if p.is_file()] if config.CONTRACT_DIR.is_dir() else []
    check("示例合同文件 ≥ 4 个", len(contracts) >= 4, f"实际 {len(contracts)} 个")

    labels = list(config.OCR_LABEL_DIR.glob("*.txt")) if config.OCR_LABEL_DIR.is_dir() else []
    check("扫描件 OCR 标注文件 ≥ 2 个", len(labels) >= 2, f"实际 {len(labels)} 个")

    check("前端构建产物存在", (config.FRONTEND_DIST / "index.html").is_file(),
          str(config.FRONTEND_DIST / "index.html"))

    if README.is_file():
        content = README.read_text(encoding="utf-8")
        missing = [name for name in TOOL_NAMES if name not in content]
        check("README 工具调用说明覆盖全部 7 个工具", not missing,
              f"缺少：{', '.join(missing)}" if missing else "")
    else:
        check("README 工具调用说明存在", False, "README.md 不存在")


def verify_schema() -> None:
    section("二、数据表结构（§1.3.9 数据表要求）")
    check("数据库文件已生成", config.DB_PATH.is_file(), str(config.DB_PATH))
    if not config.DB_PATH.is_file():
        return

    connection = sqlite3.connect(str(config.DB_PATH))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table, required in REQUIRED_TABLES.items():
            if table not in tables:
                check(f"{table} 表存在", False, "表不存在")
                continue
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            missing = required - columns
            check(f"{table} 表及必需列完整", not missing,
                  f"缺少列：{', '.join(sorted(missing))}" if missing else "")

        indexes = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
        ).fetchone()[0]
        check("已建立查询索引", indexes >= 10, f"实际 {indexes} 个")
    finally:
        connection.close()


def verify_health(client: httpx.Client) -> None:
    section("三、服务可运行性（§1.3.3 服务入口 / §1.3.12 验收标准）")
    response = client.get("/api/health")
    check("健康检查接口返回 200", response.status_code == 200, str(response.status_code))

    response = client.get("/")
    check("前端页面可访问", response.status_code == 200 and "text/html" in response.headers.get("content-type", ""),
          str(response.status_code))

    response = client.get("/api/docs")
    check("接口文档可访问", response.status_code == 200, str(response.status_code))


def verify_auth(client: httpx.Client) -> tuple[str, str]:
    section("四、账户与权限（§1.3.2 用户角色）")
    client.post("/api/system/init", json={})

    admin = client.post("/api/system/login", json={"username": "admin", "password": "admin123"})
    check("管理员账户可登录", admin.status_code == 200, str(admin.status_code))
    admin_token = admin.json()["token"] if admin.status_code == 200 else ""

    reviewer = client.post("/api/system/login", json={"username": "reviewer", "password": "reviewer123"})
    check("法务审核人账户可登录", reviewer.status_code == 200, str(reviewer.status_code))
    reviewer_token = reviewer.json()["token"] if reviewer.status_code == 200 else ""

    bad = client.post("/api/system/login", json={"username": "admin", "password": "wrong-password"})
    check("错误密码被拒绝（401）", bad.status_code == 401, str(bad.status_code))

    anon = client.get("/api/tasks")
    check("未登录访问业务接口被拒绝（401）", anon.status_code == 401, str(anon.status_code))

    if reviewer_token:
        forbidden = client.get("/api/logs/tasks", headers={"Authorization": f"Bearer {reviewer_token}"})
        check("法务审核人访问管理员接口被拒绝（403）", forbidden.status_code == 403, str(forbidden.status_code))

        allowed = client.get("/api/tasks", headers={"Authorization": f"Bearer {reviewer_token}"})
        check("法务审核人可访问待办任务", allowed.status_code == 200, str(allowed.status_code))

    return admin_token, reviewer_token


def verify_pull_and_dedupe(client: httpx.Client, headers: dict) -> list[dict]:
    section("五、待办拉取与去重（§1.3.4 任务状态与流转规则）")
    first = client.post("/api/tools/list-pending-approvals", json={"limit": 20}, headers=headers)
    check("待办拉取接口返回 200", first.status_code == 200, str(first.status_code))
    payload = first.json()

    fields = {"instance_id", "approval_code", "approval_title", "applicant_name",
              "applied_at", "attachment_count"}
    items_ok = bool(payload.get("items")) and all(
        fields.issubset(item.keys()) for item in payload["items"]
    )
    check("待办列表字段完整（编号/标题/申请人/申请时间/附件数量）", items_ok)

    # 等待流水线跑完，再用第二轮拉取验证去重
    for _ in range(180):
        tasks = client.get("/api/tasks", headers=headers).json()["tasks"]
        if tasks and all(t["task_status"] in {"done", "blocked"} for t in tasks):
            break
        time.sleep(0.5)

    second = client.post("/api/tools/list-pending-approvals", json={"limit": 20}, headers=headers).json()
    check("重复拉取不新建任务", second["created_count"] == 0,
          f"新增 {second['created_count']} 条")

    codes = [t["approval_code"] for t in tasks]
    check("审批编号全局唯一（按唯一业务标识去重）", len(codes) == len(set(codes)),
          f"{len(codes)} 条任务 / {len(set(codes))} 个编号")

    return tasks


def verify_parse(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("六、合同解析字段（§1.3.5 合同解析字段要求）")
    parsed = [t for t in tasks if t["parse_type"]]
    check("存在解析成功的合同", bool(parsed), "无解析成功记录")
    if not parsed:
        return

    detail = client.get(f"/api/tasks/{parsed[0]['id']}", headers=headers).json()
    parse = detail["parse"]

    basic_keys = {"contract_title", "contract_no", "party_a", "party_b",
                  "amount", "currency", "effective_date", "expire_date"}
    clause_keys = {"payment", "delivery", "acceptance", "breach",
                   "confidentiality", "data", "ip", "dispute"}
    check("基本信息覆盖 8 个规定字段", basic_keys.issubset(parse["basic_info"].keys()))
    check("条款信息覆盖 8 类规定条款", clause_keys.issubset(parse["clause_info"].keys()))

    def fields_complete(collection: dict) -> bool:
        for item in collection.values():
            if item.get("status") not in {"found", "missing"}:
                return False
            if item["status"] == "found":
                # 提取成功必须带原文片段、位置标识与状态
                if not item.get("evidence") or not item.get("position") or not item.get("value"):
                    return False
        return True

    check("每个字段均含原文片段、位置标识与提取状态",
          fields_complete(parse["basic_info"]) and fields_complete(parse["clause_info"]))

    # 扫描件必须走 OCR 路径
    ocr = [t for t in tasks if t["parse_type"] == "pdf_ocr"]
    parse_types = sorted({t["parse_type"] for t in tasks if t["parse_type"]})
    check("扫描件通过 OCR 识别解析（parse_type=pdf_ocr）", bool(ocr),
          f"解析方式：{parse_types}")

    # 解析失败必须记录原因
    failed = [
        p for p in (
            client.get(f"/api/tasks/{t['id']}", headers=headers).json().get("parse")
            for t in tasks if t["task_status"] == "blocked"
        )
        if p and p["parse_status"] == "failed"
    ]
    check("解析失败记录失败原因（parse_error 非空）",
          bool(failed) and all(p["parse_error"] for p in failed),
          f"失败解析记录 {len(failed)} 条")


def verify_rules_and_output(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("七、审查规则与输出格式（§1.3.6 / §1.3.11）")
    rules = client.get("/api/rules", headers=headers).json()["rules"]
    check("规则数量 ≥ 12", len(rules) >= 12, f"实际 {len(rules)} 条")

    rule_fields = {"rule_code", "rule_name", "risk_level", "rule_status",
                   "match_mode", "match_text", "suggestion_text"}
    check("规则字段完整（编码/名称/等级/状态/模式/匹配文本/建议）",
          all(rule_fields.issubset(r.keys()) for r in rules))

    levels = {r["risk_level"] for r in rules}
    check("规则覆盖 高/中/低 三个风险等级", levels == {"高", "中", "低"}, str(sorted(levels)))

    # 规则主题覆盖（§1.3.6 规定的 11 个风险主题）
    names = " ".join(r["rule_name"] for r in rules)
    themes = {
        "预付款比例": "预付款" in names,
        "付款周期": "付款周期" in names,
        "自动续约": "续约" in names,
        "违约责任": "违约" in names,
        "管辖地": "管辖" in names,
        "主体信息缺失": "主体信息" in names,
        "金额缺失": "金额缺失" in names,
        "保密缺失": "保密" in names,
        "数据处理": "数据" in names,
        "知识产权": "知识产权" in names,
        "验收标准缺失": "验收" in names,
    }
    missing = [name for name, hit in themes.items() if not hit]
    check("规则覆盖全部规定风险主题", not missing,
          f"缺少：{', '.join(missing)}" if missing else "")

    # 命中结果字段
    done = [t for t in tasks if t["task_status"] == "done" and t["hit_count"]]
    check("存在命中规则的任务", bool(done), "无命中记录")
    if not done:
        return

    detail = client.get(f"/api/tasks/{done[0]['id']}", headers=headers).json()
    hits = detail["hits"]
    hit_fields = {"rule_name", "risk_level", "evidence_text", "evidence_position", "suggestion_text"}
    check("命中结果含规则名称/风险等级/证据/位置/建议",
          bool(hits) and all(hit_fields.issubset(h.keys()) for h in hits))

    # 总风险等级 = 命中规则最高等级
    order = {"高": 3, "中": 2, "低": 1}
    active = [h["risk_level"] for h in hits if h["hit_status"] != "dismissed"]
    expected = max(active, key=lambda x: order[x]) if active else "低"
    result = detail["result"]
    check(f"总风险等级等于命中最高等级（{expected}）",
          result["overall_risk_level"] == expected, result["overall_risk_level"])
    check("总风险等级取值合法（低/中/高）",
          result["overall_risk_level"] in {"低", "中", "高"}, result["overall_risk_level"])

    check("输出含中文摘要", bool(result["summary_text"]) and any(
        "一" <= ch <= "鿿" for ch in result["summary_text"]))
    check("输出含审批关注点列表", isinstance(result["focus_points"], list) and bool(result["focus_points"]))
    check("输出含回写内容", bool(result["comment_text"]))

    focus_fields = {"point", "risk_level"}
    check("关注点含事项与风险等级",
          all(focus_fields.issubset(p.keys()) for p in result["focus_points"]))


def verify_tools(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("八、工具接口（§1.3.10 工具接口要求）")
    done = [t for t in tasks if t["task_status"] == "done" and t["hit_count"]]
    if not done:
        check("存在可调用工具的任务", False, "无已完成任务")
        return

    detail = client.get(f"/api/tasks/{done[0]['id']}", headers=headers).json()
    task = detail["task"]
    parse = detail["parse"]

    # 1 待办拉取
    r = client.post("/api/tools/list-pending-approvals", json={"limit": 5}, headers=headers)
    check("[1] list_pending_contract_approvals 可用",
          r.status_code == 200 and "items" in r.json(), str(r.status_code))

    # 2 审批详情
    r = client.get(f"/api/tools/approvals/{task['instance_id']}", headers=headers)
    payload = r.json() if r.status_code == 200 else {}
    check("[2] get_contract_approval 返回审批信息/表单数据/附件/处理状态",
          r.status_code == 200 and {"approval", "form_data", "attachments", "process_status"}.issubset(payload.keys()),
          str(r.status_code))

    # 3 附件下载
    attachment = (payload.get("attachments") or [{}])[0]
    r = client.post("/api/tools/download-attachment", json={
        "instance_id": task["instance_id"],
        "attachment_id": attachment.get("attachment_id", ""),
        "file_name": attachment.get("file_name", ""),
    }, headers=headers)
    payload = r.json() if r.status_code == 200 else {}
    check("[3] download_contract_attachment 返回本地路径与校验信息",
          r.status_code == 200 and {"local_path", "sha256", "file_size", "verified"}.issubset(payload.keys())
          and Path(payload.get("local_path", "")).is_file(),
          str(r.status_code))

    # 4 文档解析
    r = client.post("/api/tools/parse-document", json={"document_id": parse["document_id"]}, headers=headers)
    payload = r.json() if r.status_code == 200 else {}
    check("[4] parse_contract_document 返回结构化字段与定位信息",
          r.status_code == 200 and payload.get("parse_status") == "success"
          and bool(payload.get("basic_info")) and bool(payload.get("clause_info")),
          str(r.status_code))

    # 5 规则审查
    r = client.post("/api/tools/run-rules", json={"case_id": parse["id"]}, headers=headers)
    payload = r.json() if r.status_code == 200 else {}
    check("[5] run_contract_rules 返回命中结果与风险结论",
          r.status_code == 200 and "overall_risk_level" in payload
          and isinstance(payload.get("hits"), list),
          str(r.status_code))

    # 6 结果保存
    r = client.post("/api/tools/save-review-result", json={
        "case_id": parse["id"],
        "overall_risk_level": payload.get("overall_risk_level", "低"),
        "summary_text": payload.get("summary_text", ""),
        "focus_points_json": json.dumps(payload.get("focus_points", []), ensure_ascii=False),
        "comment_text": payload.get("comment_text", ""),
    }, headers=headers)
    check("[6] save_review_result 保存审查结果",
          r.status_code == 200 and "review_id" in (r.json() if r.status_code == 200 else {}),
          str(r.status_code))

    # 7 评论回写
    review_id = detail["result"]["id"]
    r = client.post("/api/tools/write-comment", json={
        "instance_id": task["instance_id"], "review_id": review_id,
    }, headers=headers)
    payload = r.json() if r.status_code == 200 else {}
    check("[7] write_approval_comment 写回评论区并返回结果",
          r.status_code == 200 and payload.get("write_status") == "success",
          str(r.status_code))


def verify_writeback(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("九、评论回写闭环（§1.3.4 回写状态 / §1.3.11 回写内容）")
    done = [t for t in tasks if t["task_status"] == "done"]
    check("存在已完成任务", bool(done), "无已完成任务")
    if not done:
        return

    check("已完成任务回写状态为 success",
          all(t["write_status"] == "success" for t in done),
          str({t["write_status"] for t in done}))

    task = done[0]
    preview = client.get(f"/api/tasks/{task['id']}/comment-preview", headers=headers).json()
    check("回写内容含审查意见标记", "【合同自动审查意见】" in preview["comment_text"])
    check("审查意见已写入审批系统评论区",
          "【合同自动审查意见】" in preview["approval_comment_area"])
    check("存在评论回写日志记录", bool(preview["comment_logs"]))

    logs = client.get("/api/logs/comments", headers=headers)
    check("评论回写日志接口可用", logs.status_code == 200 and logs.json()["total"] > 0,
          str(logs.status_code))

    task_logs = client.get("/api/logs/tasks", headers=headers)
    check("全链路日志接口可用", task_logs.status_code == 200 and task_logs.json()["total"] > 0,
          str(task_logs.status_code))


def verify_blocked_and_retry(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("十、异常阻塞与重试（§1.3.4 任务状态与流转规则）")
    blocked = [t for t in tasks if t["task_status"] == "blocked"]
    reasons = {t["blocked_reason"] for t in blocked}

    for reason in ("附件缺失", "文档内容为空", "图片无法识别"):
        check(f"阻塞原因「{reason}」可达", reason in reasons, f"现有：{sorted(reasons)}")

    check("阻塞任务记录了失败阶段",
          bool(blocked) and all(t["failure_stage"] in {"download", "parse", "review"} for t in blocked),
          str({t["failure_stage"] for t in blocked}))

    # 接口调用失败：开启开关后重试阻塞任务即可触发
    client.put("/api/system/config", json={"configs": {"adapter_fail_enabled": "true"}}, headers=headers)
    target = next((t for t in blocked if t["failure_stage"] == "download"), None)
    if target:
        client.post(f"/api/tasks/{target['id']}/retry", headers=headers)
        deadline = time.time() + 60
        while time.time() < deadline:
            row = next((t for t in client.get("/api/tasks", headers=headers).json()["tasks"]
                        if t["id"] == target["id"]), None)
            if row and row["task_status"] == "blocked" and not row["is_active"]:
                break
            time.sleep(0.5)
        check("阻塞原因「接口调用失败」可达", row and row["blocked_reason"] == "接口调用失败",
              row["blocked_reason"] if row else "未取到任务")
        check("重试后重新进入解析阶段（failure_stage=download）",
              row and row["failure_stage"] == "download", row["failure_stage"] if row else "")
        check("重试次数已累加", row and row["retry_count"] >= 1)
    else:
        check("阻塞原因「接口调用失败」可达", False, "无 download 阶段阻塞任务可用于重试")

    client.put("/api/system/config", json={"configs": {"adapter_fail_enabled": "false"}}, headers=headers)

    # 恢复原阻塞状态
    if target:
        client.post(f"/api/tasks/{target['id']}/retry", headers=headers)
        deadline = time.time() + 60
        while time.time() < deadline:
            row = next((t for t in client.get("/api/tasks", headers=headers).json()["tasks"]
                        if t["id"] == target["id"]), None)
            if row and row["task_status"] == "blocked" and not row["is_active"]:
                break
            time.sleep(0.5)
        check("接口恢复后重试回到业务阻塞原因（附件缺失）",
              row and row["blocked_reason"] == "附件缺失",
              row["blocked_reason"] if row else "")

    # 已完成任务不允许重试
    done = next((t for t in tasks if t["task_status"] == "done"), None)
    if done:
        r = client.post(f"/api/tasks/{done['id']}/retry", headers=headers)
        check("已完成任务不可重试（400）", r.status_code == 400, str(r.status_code))


def verify_review_action(client: httpx.Client, headers: dict, tasks: list[dict]) -> None:
    section("十一、法务审核人判定动作（§1.3.2 法务审核人）")
    done = [t for t in tasks if t["task_status"] == "done" and t["hit_count"]]
    if not done:
        check("存在可判定的命中记录", False, "无命中任务")
        return

    detail = client.get(f"/api/tasks/{done[0]['id']}", headers=headers).json()
    hit = detail["hits"][0]
    original = detail["result"]["overall_risk_level"]

    r = client.put(f"/api/tasks/{done[0]['id']}/hits/{hit['id']}",
                   json={"hit_status": "dismissed"}, headers=headers)
    check("可将命中标记为误报", r.status_code == 200 and r.json()["hit_status"] == "dismissed",
          str(r.status_code))
    check("误报判定后总风险等级重算",
          r.status_code == 200 and r.json()["overall_risk_level"] in {"低", "中", "高"},
          r.json().get("overall_risk_level") if r.status_code == 200 else "")

    # 恢复原状态，避免影响后续查看
    client.put(f"/api/tasks/{done[0]['id']}/hits/{hit['id']}",
               json={"hit_status": "hit"}, headers=headers)
    restored = client.get(f"/api/tasks/{done[0]['id']}", headers=headers).json()
    check("恢复命中后风险等级还原", restored["result"]["overall_risk_level"] == original,
          restored["result"]["overall_risk_level"])


def main() -> int:
    print(f"{BOLD}{CYAN}{'=' * 74}{RESET}")
    print(f"{BOLD}{CYAN}  合同审批审查系统 —— 验收自检{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 74}{RESET}")

    verify_files()
    verify_schema()

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        try:
            client.get("/api/health")
        except Exception as exc:
            print(f"\n{RED}无法连接后端服务 {BASE_URL}，请先启动服务。{RESET}\n  错误：{exc}")
            return 1

        verify_health(client)
        admin_token, _ = verify_auth(client)
        headers = {"Authorization": f"Bearer {admin_token}"}

        tasks = verify_pull_and_dedupe(client, headers)
        verify_parse(client, headers, tasks)
        verify_rules_and_output(client, headers, tasks)
        verify_tools(client, headers, tasks)
        verify_writeback(client, headers, tasks)
        verify_blocked_and_retry(client, headers, tasks)
        verify_review_action(client, headers, tasks)

    print(f"\n{BOLD}{CYAN}▸ 自检结果汇总{RESET}")
    total = PASS + FAIL
    if FAILURES:
        print(f"  {RED}失败项：{RESET}")
        for item in FAILURES:
            print(f"    {RED}✗{RESET} {item}")
    print(f"  通过 {GREEN}{PASS}{RESET} / {total}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
