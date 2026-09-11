"""Compare the API responses the web client relies on against the expected keys.

Run against a live server:  python scripts/check_contracts.py [base_url]
Exits non-zero when a required key is missing, which usually means the frontend
types in `frontend/src/api/types.ts` drifted from the backend schemas.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
failures: list[str] = []


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:  # pragma: no cover - diagnostics only
        failures.append(f"{method} {path} -> HTTP {error.code}: {error.read().decode()[:200]}")
        return {}


def expect(label: str, payload: dict, keys: list[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        failures.append(f"{label}: 缺少字段 {missing}")
    print(f"{'OK ' if not missing else 'FAIL'} {label}")


meta = call("GET", "/api/meta")
expect("GET /api/meta", meta, ["appName", "version", "nodeCount", "categories", "taskTypes", "llm", "limits"])

nodes = call("GET", "/api/nodes")
expect("GET /api/nodes", nodes, ["catalog"])
if nodes.get("catalog"):
    group = nodes["catalog"][0]
    expect("  node group", group, ["category", "nodes"])
    expect(
        "  node spec",
        group["nodes"][0],
        ["type", "label", "category", "description", "tags", "inputs", "outputs", "params"],
    )
    expect(
        "  param spec",
        next(
            (param for node in group["nodes"] for param in node["params"]),
            {},
        ),
        ["name", "type", "default", "label", "min", "max", "step", "options", "level", "unit", "description"],
    )

expect("GET /api/templates", call("GET", "/api/templates"), ["templates"])

projects = call("GET", "/api/projects")
expect("GET /api/projects", projects, ["projects"])
project_id = next(
    (item["id"] for item in projects.get("projects", []) if item.get("imageCount")),
    None,
)
if project_id is None:
    failures.append("没有可用于校验的项目（先运行 scripts/seed_demo.py）")
    print("\n".join(failures))
    raise SystemExit(1)

detail = call("GET", f"/api/projects/{project_id}")
expect(
    f"GET /api/projects/{{id}}",
    detail,
    ["id", "name", "graph", "userParams", "labels", "versions", "issues", "nodeCount", "imageCount"],
)

images = call("GET", f"/api/projects/{project_id}/images?pageSize=5")
expect("GET /api/projects/{id}/images", images, ["images", "total", "page", "pageSize"])
image = images["images"][0]
expect(
    "  image asset",
    image,
    ["id", "filename", "width", "height", "split", "thumbUrl", "previewUrl", "rawUrl", "annotation"],
)

expect(
    "GET /api/images/{id}/histogram",
    call("GET", f"/api/images/{image['id']}/histogram"),
    ["bins", "channels", "stats"],
)
expect(
    "GET /api/images/{id}/diagnose",
    call("GET", f"/api/images/{image['id']}/diagnose"),
    ["level", "metrics", "findings"],
)
expect(
    "GET /api/projects/{id}/dataset/stats",
    call("GET", f"/api/projects/{project_id}/dataset/stats"),
    ["total", "annotated", "unannotated", "shapeCount", "bySplit", "byLabel", "diskBytes"],
)
expect("GET /api/projects/{id}/labels", call("GET", f"/api/projects/{project_id}/labels"), ["labels"])

run = call(
    "POST",
    f"/api/projects/{project_id}/pipeline/run",
    {"imageId": image["id"], "saveGraph": False},
)
expect(
    "POST /api/projects/{id}/pipeline/run",
    run,
    ["order", "totalMs", "verdict", "reason", "measurements", "errors", "cache", "nodes"],
)
if run.get("nodes"):
    node_info = next(iter(run["nodes"].values()))
    expect(
        "  node run info",
        node_info,
        ["nodeId", "nodeType", "status", "durationMs", "cached", "params", "outputs", "logs"],
    )

expect("GET /api/projects/{id}/batch", call("GET", f"/api/projects/{project_id}/batch"), ["runs"])
expect(
    "GET /api/projects/{id}/runtime",
    call("GET", f"/api/projects/{project_id}/runtime"),
    ["sessionId", "status", "source", "published", "total", "yieldPercent", "userParams", "records"],
)
expect(
    "GET /api/projects/{id}/models/samples",
    call("GET", f"/api/projects/{project_id}/models/samples"),
    ["sampleCount", "classes", "distribution", "trainable"],
)
expect("GET /api/models", call("GET", f"/api/models?projectId={project_id}"), ["models"])
trainers = call("GET", "/api/models/trainers")
expect("GET /api/models/trainers", trainers, ["trainers"])
if trainers.get("trainers"):
    expect("  trainer", trainers["trainers"][0], ["id", "name", "family", "available", "hint"])
devices = call("GET", "/api/devices")
expect("GET /api/devices", devices, ["devices", "implementedCount", "note"])
if devices.get("devices"):
    expect(
        "  device status",
        devices["devices"][0],
        ["id", "name", "kind", "implemented", "capabilities", "settings", "note", "state"],
    )
monitoring = call("GET", "/api/monitoring/overview?hours=24")
expect(
    "GET /api/monitoring/overview",
    monitoring,
    ["hours", "since", "generatedAt", "summary", "devices", "models", "projects", "timeline",
     "alerts", "retentionNote"],
)
expect(
    "  summary",
    monitoring.get("summary", {}),
    ["total", "okCount", "ngCount", "errorCount", "yieldPercent", "avgDurationMs", "p95DurationMs",
     "maxDurationMs", "avgConfidence", "minConfidence", "lowConfidenceCount", "lastAt",
     "projectCount", "deviceCount", "modelCount", "onlineDevices", "totalDevices",
     "datasetInferences", "runningSessions"],
)
if monitoring.get("devices"):
    expect("  monitored device", monitoring["devices"][0], ["id", "name", "online", "state", "total",
                                                            "avgDurationMs", "lastAt"])
if monitoring.get("models"):
    expect(
        "  monitored model",
        monitoring["models"][0],
        ["id", "name", "projectId", "projectName", "classes", "cvAccuracy", "trainedAt",
         "confidenceBuckets", "total", "avgConfidence", "lowConfidenceCount", "p95DurationMs"],
    )
if monitoring.get("timeline"):
    expect("  timeline bucket", monitoring["timeline"][0],
           ["ts", "total", "okCount", "ngCount", "errorCount", "avgDurationMs"])
records = call("GET", "/api/monitoring/records?hours=24&pageSize=1")
expect("GET /api/monitoring/records", records, ["records", "total", "page", "pageSize"])
if records.get("records"):
    expect(
        "  inference record",
        records["records"][0],
        ["id", "seq", "projectId", "projectName", "imageName", "verdict", "source", "deviceId",
         "modelId", "modelName", "confidence", "measurements", "preview", "durationMs", "error",
         "createdAt"],
    )

expect(
    "GET /api/projects/{id}/copilot/diagnose",
    call("GET", f"/api/projects/{project_id}/copilot/diagnose"),
    ["level", "metrics", "findings"],
)
plan = call(
    "POST",
    f"/api/projects/{project_id}/copilot/plan",
    {"text": "找出图中的深色缺陷，超过 500 像素判 NG", "useLlm": False},
)
expect("POST /api/projects/{id}/copilot/plan", plan, ["intent", "diagnosis", "plan", "llm"])
if plan.get("plan"):
    expect(
        "  plan",
        plan["plan"],
        ["graph", "taskType", "route", "routeReason", "summary", "steps", "warnings", "source"],
    )
expect(
    "GET /api/projects/{id}/copilot/history",
    call("GET", f"/api/projects/{project_id}/copilot/history"),
    ["messages"],
)

print()
if failures:
    print("发现 %d 个契约问题:" % len(failures))
    for item in failures:
        print(" -", item)
    raise SystemExit(1)
print("全部接口字段与前端类型一致 ✓")
