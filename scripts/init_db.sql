-- ============================================================================
-- 合同审批审查系统 - 数据库初始化脚本
-- 数据库: SQLite 3
-- 说明: 本脚本幂等，可重复执行（全部使用 CREATE TABLE IF NOT EXISTS）
--       核心表结构对应需求文档 §1.3.9 数据表要求
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 一、基础支撑表
-- ---------------------------------------------------------------------------

-- 1. users 用户表（§1.3.2 用户角色：admin 系统管理员 / reviewer 法务审核人）
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT    NOT NULL DEFAULT '',
    role          TEXT    NOT NULL DEFAULT 'reviewer',   -- admin / reviewer
    status        TEXT    NOT NULL DEFAULT 'active',     -- active / disabled
    created_at    TEXT    NOT NULL
);

-- 2. sessions 登录会话表
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT    NOT NULL UNIQUE,
    user_id    INTEGER NOT NULL,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- 3. system_configs 系统配置表（§1.3.2 系统管理员维护审批接入配置）
CREATE TABLE IF NOT EXISTS system_configs (
    config_key   TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 二、模拟审批系统表（§1.3.2 审批系统：外部系统，通过适配器对接）
-- ---------------------------------------------------------------------------

-- 4. mock_approvals 模拟审批单表
CREATE TABLE IF NOT EXISTS mock_approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     TEXT NOT NULL UNIQUE,                  -- 审批实例编号 AP-xxx
    approval_code   TEXT NOT NULL UNIQUE,                  -- 审批编号（业务唯一标识）
    approval_title  TEXT NOT NULL,
    applicant_name  TEXT NOT NULL,
    department      TEXT NOT NULL DEFAULT '',
    approval_status TEXT NOT NULL DEFAULT 'pending',       -- pending / approved / rejected
    current_node    TEXT NOT NULL DEFAULT '法务审核',
    form_data_json  TEXT NOT NULL DEFAULT '{}',            -- 表单数据
    comment_area    TEXT NOT NULL DEFAULT '',              -- 审批评论区（回写目标）
    applied_at      TEXT NOT NULL,                         -- 申请时间
    created_at      TEXT NOT NULL
);

-- 5. mock_approval_attachments 模拟审批单附件表
CREATE TABLE IF NOT EXISTS mock_approval_attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id   TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    file_type     TEXT NOT NULL DEFAULT 'contract',        -- contract / scan / other
    source_path   TEXT NOT NULL,                           -- 相对 examples/contracts 的路径
    created_at    TEXT NOT NULL,
    UNIQUE (instance_id, attachment_id)
);

-- ---------------------------------------------------------------------------
-- 三、核心业务表（§1.3.9 数据表要求）
-- ---------------------------------------------------------------------------

-- 6. approval_tasks 审批任务表（按 approval_code 唯一去重，§1.3.4 任务状态与流转规则）
CREATE TABLE IF NOT EXISTS approval_tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_code  TEXT    NOT NULL UNIQUE,                     -- 唯一业务标识（去重键）
    approval_title TEXT    NOT NULL DEFAULT '',
    applicant_name TEXT    NOT NULL DEFAULT '',
    task_status    TEXT    NOT NULL DEFAULT 'pending',          -- pending/parsing/reviewing/blocked/done
    write_status   TEXT    NOT NULL DEFAULT 'not_written',      -- not_written/writing/success/failed
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    -- 扩展字段
    instance_id    TEXT    NOT NULL DEFAULT '',                 -- 审批实例编号
    applied_at     TEXT    NOT NULL DEFAULT '',                 -- 申请时间
    blocked_reason TEXT    NOT NULL DEFAULT '',                 -- 阻塞原因（附件缺失/图片无法识别/文档内容为空/接口调用失败）
    failure_stage  TEXT    NOT NULL DEFAULT '',                 -- download / parse / review（决定重试入口）
    retry_count    INTEGER NOT NULL DEFAULT 0
);

-- 7. approval_attachments 审批附件表（附件元数据与下载信息）
CREATE TABLE IF NOT EXISTS approval_attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    file_name       TEXT    NOT NULL,
    file_type       TEXT    NOT NULL DEFAULT 'contract',
    file_path       TEXT    NOT NULL DEFAULT '',                -- 下载后的本地路径
    download_status TEXT    NOT NULL DEFAULT 'pending',         -- pending/success/failed
    created_at      TEXT    NOT NULL,
    -- 扩展字段（§1.3.3 附件下载工具返回本地文件路径和校验信息）
    attachment_id   TEXT    NOT NULL DEFAULT '',
    sha256          TEXT    NOT NULL DEFAULT '',
    file_size       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

-- 8. contract_parses 合同解析结果表（§1.3.5 合同解析字段要求）
CREATE TABLE IF NOT EXISTS contract_parses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          INTEGER NOT NULL UNIQUE,
    basic_info_json  TEXT    NOT NULL DEFAULT '{}',             -- 合同基本信息（8 字段）
    clause_info_json TEXT    NOT NULL DEFAULT '{}',             -- 条款信息（8 类条款）
    parse_status     TEXT    NOT NULL DEFAULT 'pending',        -- pending/success/failed
    parse_error      TEXT    NOT NULL DEFAULT '',               -- 解析失败原因（不允许静默空结果）
    created_at       TEXT    NOT NULL,
    -- 扩展字段
    document_id      TEXT    NOT NULL DEFAULT '',               -- 文档编号 DOC-xxxx
    parse_type       TEXT    NOT NULL DEFAULT '',               -- docx / pdf_text / pdf_ocr
    full_text        TEXT    NOT NULL DEFAULT '',               -- 全文（供规则匹配与证据回溯）
    page_count       INTEGER NOT NULL DEFAULT 0,
    attachment_id    INTEGER,                                   -- 关联 approval_attachments.id
    paragraphs_json  TEXT    NOT NULL DEFAULT '[]',             -- 段落与位置信息（供审查阶段复现证据位置）
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY (attachment_id) REFERENCES approval_attachments (id) ON DELETE SET NULL
);

-- 9. review_rules 审查规则表（§1.3.6 审查规则要求）
CREATE TABLE IF NOT EXISTS review_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code       TEXT    NOT NULL UNIQUE,
    rule_name       TEXT    NOT NULL,
    risk_level      TEXT    NOT NULL DEFAULT '中',              -- 高 / 中 / 低
    rule_status     TEXT    NOT NULL DEFAULT 'enabled',         -- enabled / disabled
    match_mode      TEXT    NOT NULL DEFAULT 'contains',        -- regex / contains / missing
    match_text      TEXT    NOT NULL DEFAULT '',
    suggestion_text TEXT    NOT NULL DEFAULT '',
    updated_at      TEXT    NOT NULL,
    -- 扩展字段：匹配对象 field:{key} / clause:{key} / full_text
    match_target    TEXT    NOT NULL DEFAULT 'full_text'
);

-- 10. rule_hits 规则命中表（§1.3.6 命中结果）
CREATE TABLE IF NOT EXISTS rule_hits (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           INTEGER NOT NULL,
    rule_id           INTEGER NOT NULL,
    evidence_text     TEXT    NOT NULL DEFAULT '',              -- 命中证据
    evidence_position TEXT    NOT NULL DEFAULT '',              -- 证据位置
    hit_status        TEXT    NOT NULL DEFAULT 'hit',           -- hit（计入风险）/ dismissed（审核人判定误报）
    created_at        TEXT    NOT NULL,
    -- 规则快照（规则后续被修改时保留当时判定依据）
    rule_code         TEXT    NOT NULL DEFAULT '',
    rule_name         TEXT    NOT NULL DEFAULT '',
    risk_level        TEXT    NOT NULL DEFAULT '',
    suggestion_text   TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE,
    FOREIGN KEY (rule_id) REFERENCES review_rules (id) ON DELETE CASCADE
);

-- 11. review_results 审查结果表（§1.3.11 输出结果格式）
CREATE TABLE IF NOT EXISTS review_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id            INTEGER NOT NULL UNIQUE,
    overall_risk_level TEXT    NOT NULL DEFAULT '低',           -- 低 / 中 / 高
    summary_text       TEXT    NOT NULL DEFAULT '',             -- 中文摘要
    focus_points_json  TEXT    NOT NULL DEFAULT '[]',           -- 审批关注点
    comment_text       TEXT    NOT NULL DEFAULT '',             -- 回写内容
    created_at         TEXT    NOT NULL,
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

-- 12. comment_logs 评论回写日志表（§1.3.4 回写状态）
CREATE TABLE IF NOT EXISTS comment_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL,
    write_status        TEXT    NOT NULL DEFAULT 'writing',     -- writing/success/failed
    write_response_text TEXT    NOT NULL DEFAULT '',            -- 回写返回内容或错误信息
    created_at          TEXT    NOT NULL,
    -- 扩展字段
    attempt_no          INTEGER NOT NULL DEFAULT 1,             -- 第几次回写尝试
    review_id           INTEGER,
    instance_id         TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

-- 13. task_logs 全链路日志表（§1.3.8 日志模块）
CREATE TABLE IF NOT EXISTS task_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    log_level   TEXT    NOT NULL DEFAULT 'INFO',                -- DEBUG/INFO/WARN/ERROR
    log_type    TEXT    NOT NULL DEFAULT '',                    -- pull_created/stage_enter/stage_ok/blocked/retry/comment_write/comment_success/comment_failed
    log_content TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (task_id) REFERENCES approval_tasks (id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 四、索引
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sessions_token          ON sessions (token);
CREATE INDEX IF NOT EXISTS idx_tasks_status            ON approval_tasks (task_status);
CREATE INDEX IF NOT EXISTS idx_tasks_write_status      ON approval_tasks (write_status);
CREATE INDEX IF NOT EXISTS idx_tasks_instance          ON approval_tasks (instance_id);
CREATE INDEX IF NOT EXISTS idx_attachments_task        ON approval_attachments (task_id);
CREATE INDEX IF NOT EXISTS idx_parses_task             ON contract_parses (task_id);
CREATE INDEX IF NOT EXISTS idx_parses_document         ON contract_parses (document_id);
CREATE INDEX IF NOT EXISTS idx_rules_status            ON review_rules (rule_status);
CREATE INDEX IF NOT EXISTS idx_hits_task               ON rule_hits (task_id);
CREATE INDEX IF NOT EXISTS idx_hits_rule               ON rule_hits (rule_id);
CREATE INDEX IF NOT EXISTS idx_results_task            ON review_results (task_id);
CREATE INDEX IF NOT EXISTS idx_comment_logs_task       ON comment_logs (task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_task          ON task_logs (task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_type          ON task_logs (log_type);
CREATE INDEX IF NOT EXISTS idx_mock_approvals_status   ON mock_approvals (approval_status);
CREATE INDEX IF NOT EXISTS idx_mock_attachments_inst   ON mock_approval_attachments (instance_id);
