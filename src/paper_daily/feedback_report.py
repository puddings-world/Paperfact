"""Allowlisted aggregate reports: no per-person IDs or event timelines leave the app."""

from collections import Counter
from math import isfinite

from paper_daily import ai_profiles

FEATURES = {*ai_profiles.TASKS, "default", "probe", "ai_settings", "list_overview",
            "bundle_import", "bundle_export", "other"}
PROVIDERS = {"cli", "codex", "gemini", "anthropic", "openai", "gateway", "other"}
FAMILIES = {"sonnet", "opus", "haiku", "fable", "gpt", "gemini", "service_default", "other"}
INPUTS = {"empty", "short", "medium", "long"}


def category(value, allowed):
    return value if isinstance(value, str) and value in allowed else "other"


def duration(value):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        return "unknown"
    return "under_10s" if value < 10 else "10_to_60s" if value < 60 else (
        "1_to_5m" if value < 300 else "over_5m"
    )


def aggregate(events, policy):
    events = [row for row in events if isinstance(row, dict)]
    usage, results, timings, models, inputs, transitions = (Counter() for _ in range(6))
    nodes = {}
    started = [r for r in events if r.get("event") in {"flow.started", "ai.started"}]
    for row in started:
        node = row.get("node_id")
        if isinstance(node, str):
            nodes[node] = category(row.get("feature"), FEATURES)
    for row in events:
        event = row.get("event")
        feature = category(row.get("feature"), FEATURES)
        if event == "ui.action":
            usage[(feature,)] += 1
        if event == "ai.started":
            models[(category(row.get("backend"), PROVIDERS),
                    category(row.get("model_family"), FAMILIES))] += 1
            inputs[(feature, category(row.get("input_size"), INPUTS))] += 1
        if event in {"ai.completed", "flow.completed"}:
            success = row.get("success")
            outcome = "success" if success is True else "failed" if success is False else "unknown"
            kind = "ai" if event == "ai.completed" else "workflow"
            results[(feature, kind, outcome)] += 1
            timings[(feature, kind, duration(row.get("duration_seconds")))] += 1
        if event in {"ai.started", "flow.started"}:
            parent = row.get("parent_node_id")
            if isinstance(parent, str) and parent in nodes:
                transitions[(nodes[parent], feature)] += 1

    def rows(counter, columns):
        return [{**dict(zip(columns, key, strict=True)), "count": count}
                for key, count in sorted(counter.items())]

    return {
        "schema_version": 2, "policy": policy, "retention_days": 30,
        "feature_usage": rows(usage, ("feature",)),
        "outcomes": rows(results, ("feature", "kind", "outcome")),
        "durations": rows(timings, ("feature", "kind", "duration_bucket")),
        "model_usage": rows(models, ("provider", "model_family")),
        "input_sizes": rows(inputs, ("feature", "size_bucket")),
        "workflow_edges": rows(transitions, ("from_feature", "to_feature")),
    }


def summary(report):
    sections = (
        ("feature_usage", "功能入口使用次數"), ("outcomes", "AI 與流程執行結果"),
        ("durations", "執行時間區間"), ("model_usage", "AI 服務與模型類別使用量"),
        ("input_sizes", "輸入規模區間"), ("workflow_edges", "流程內的功能銜接"),
    )
    labels = {"success": "成功", "failed": "失敗", "unknown": "未知", "ai": "AI",
              "workflow": "流程", "under_10s": "10 秒內", "10_to_60s": "10–60 秒",
              "1_to_5m": "1–5 分鐘", "over_5m": "超過 5 分鐘", "cli": "Claude",
              "empty": "無文字", "short": "少於 1,000 字", "medium": "1,000–9,999 字",
              "long": "10,000 字以上", "other": "其他", "service_default": "服務預設"}
    # Import UI labels lazily nowhere: the report stays usable without Qt.
    labels.update({"ask": "論文問答", "dive": "深度講解", "translate": "翻譯",
                   "slides": "簡報", "list_parse": "建立清單", "ai_settings": "AI 設定",
                   "list_overview": "清單總覽", "bundle_import": "匯入資料包",
                   "bundle_export": "匯出資料包"})
    lines = ["近 30 天的統計摘要；沒有逐筆紀錄或識別碼。"]
    for key, title in sections:
        lines.extend(("", title))
        for row in report[key]:
            name = " · ".join(labels.get(v, v) for k, v in row.items() if k != "count")
            lines.append(f"  {name}：{row['count']} 次")
        if not report[key]:
            lines.append("  尚無資料")
    return "\n".join(lines)
