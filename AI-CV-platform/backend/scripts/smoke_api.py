"""End-to-end API smoke test (no browser, no external services).

Walks the MVP acceptance path: 新建项目 → 导入图像 → 标注 → 单节点调试 →
AI 生成流程 → 批量测试 → 发布 → Runtime → 训练分类模型 → 设备采集。

Usage::

    python -m scripts.smoke_api
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.utils.imageio import encode_png  # noqa: E402

PASS, FAIL = "[ok]  ", "[FAIL]"
_failures: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    print(f"{PASS if condition else FAIL} {name} {extra}")
    if not condition:
        _failures.append(name)


def synthetic(size: int = 320, spots: int = 0, seed: int = 0) -> bytes:
    import cv2

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    image = np.clip(180 + 20 * np.sin(xx / size * np.pi) + rng.normal(0, 4, (size, size)), 0, 255)
    image = image.astype(np.uint8)
    for _ in range(spots):
        x, y = (int(v) for v in rng.integers(40, size - 40, 2))
        cv2.circle(image, (x, y), int(rng.integers(6, 12)), 45, -1)
    return encode_png(image)


def main() -> int:
    client = TestClient(app)
    with client:
        response = client.get("/api/health")
        check("health", response.status_code == 200, str(response.json()))

        meta = client.get("/api/meta").json()
        check("meta / 节点数量 >= 30", meta["nodeCount"] >= 30, f"nodes={meta['nodeCount']}")

        catalog = client.get("/api/nodes").json()["catalog"]
        check("节点库分组", len(catalog) >= 8, f"categories={len(catalog)}")

        templates = client.get("/api/templates").json()["templates"]
        check("流程模板", len(templates) >= 5, f"templates={len(templates)}")

        name = f"Smoke 测试项目 {int(time.time())}"
        project = client.post(
            "/api/projects",
            json={"name": name, "templateId": "surface_defect",
                  "requirement": "检测白布上的黑色污点，不允许出现大于 8 像素的污点"},
        ).json()
        project_id = project["id"]
        check("新建项目", bool(project_id), project_id)

        files = [
            ("files", (f"ok_{i}.png", io.BytesIO(synthetic(spots=0, seed=i)), "image/png"))
            for i in range(3)
        ] + [
            ("files", (f"ng_{i}.png", io.BytesIO(synthetic(spots=2, seed=100 + i)), "image/png"))
            for i in range(3)
        ]
        upload = client.post(f"/api/projects/{project_id}/images", files=files).json()
        check("批量导入图像", upload["imported"] == 6, f"imported={upload['imported']}")
        images = upload["images"]

        for image in images:
            label = "NG" if image["filename"].startswith("ng") else "OK"
            client.put(
                f"/api/projects/{project_id}/annotations",
                json={"imageId": image["id"], "label": label},
            )
        shapes = [{"type": "bbox", "label": "NG", "points": [[0.3, 0.3], [0.5, 0.5]]}]
        client.put(
            f"/api/projects/{project_id}/annotations",
            json={"imageId": images[-1]["id"], "shapes": shapes},
        )
        stats = client.get(f"/api/projects/{project_id}/dataset/stats").json()
        check("标注统计", stats["annotated"] == 6, str(stats["byLabel"]))

        histogram = client.get(f"/api/images/{images[0]['id']}/histogram").json()
        check("直方图", len(histogram["channels"]["gray"]) == 256, str(histogram["stats"]))
        pixels = client.get(f"/api/images/{images[0]['id']}/pixels", params={"x": 10, "y": 10}).json()
        check("像素探针", "value" in pixels, str(pixels["value"]))

        diagnose = client.get(f"/api/projects/{project_id}/copilot/diagnose").json()
        check("图像诊断", "metrics" in diagnose and diagnose["sampleCount"] >= 1,
              f"level={diagnose['level']} findings={len(diagnose['findings'])}")

        plan = client.post(
            f"/api/projects/{project_id}/copilot/plan",
            json={"text": "检测白布上的黑色污点，不允许出现面积大于 60 像素的污点"},
        ).json()
        graph = plan["plan"]["graph"]
        check("AI 生成流程", len(graph["nodes"]) >= 5,
              f"task={plan['intent']['taskType']} route={plan['plan']['route']} "
              f"nodes={len(graph['nodes'])} steps={len(plan['plan']['steps'])}")
        check("生成流程无告警", not plan["plan"]["warnings"], str(plan["plan"]["warnings"]))

        applied = client.post(
            f"/api/projects/{project_id}/copilot/apply",
            json={"graph": graph, "taskType": plan["intent"]["taskType"]},
        ).json()
        check("应用流程", len(applied["graph"]["nodes"]) == len(graph["nodes"]))

        run = client.post(
            f"/api/projects/{project_id}/pipeline/run",
            json={"imageId": images[-1]["id"]},
        ).json()
        check("全流程运行", not run["errors"], f"verdict={run['verdict']} ms={run['totalMs']}")
        previews = [
            output.get("preview")
            for node in run["nodes"].values()
            for output in node["outputs"].values()
            if output.get("preview")
        ]
        check("中间结果预览", len(previews) >= 3, f"previews={len(previews)}")
        if previews:
            url = previews[0]["url"].split("?")[0]
            check("预览可访问", client.get(url).status_code == 200, url)

        target = [nid for nid, info in run["nodes"].items() if info["nodeType"] == "adaptive_threshold"]
        if target:
            single = client.post(
                f"/api/projects/{project_id}/pipeline/run",
                json={"imageId": images[-1]["id"], "targetNode": target[0]},
            ).json()
            check("单节点调试", single["order"][-1] == target[0],
                  f"executed={len(single['order'])} cached={single['cache']}")

        validate = client.post(
            f"/api/projects/{project_id}/pipeline/validate", json={"graph": graph}
        ).json()
        check("Pipeline 校验", not [i for i in validate["issues"] if i["level"] == "error"],
              str(validate["issues"][:2]))

        started = client.post(f"/api/projects/{project_id}/batch", json={"split": "all"}).json()
        run_id = started["id"]
        summary = started
        for _ in range(60):
            time.sleep(0.3)
            summary = client.get(f"/api/batch/{run_id}").json()
            if summary["status"] != "running":
                break
        check("批量测试完成", summary["status"] == "finished",
              f"done={summary['done']}/{summary['total']} counts={summary['metrics'].get('counts')}")
        results = client.get(f"/api/batch/{run_id}/results").json()
        check("批量结果列表", results["total"] == 6, f"total={results['total']}")
        advice = client.get(f"/api/batch/{run_id}/advice").json()
        check("调试建议", len(advice["suggestions"]) >= 1, advice["suggestions"][0]["title"])
        csv_response = client.get(f"/api/batch/{run_id}/export.csv")
        check("结果导出 CSV", csv_response.status_code == 200 and "verdict" in csv_response.text)
        reflow = client.post(f"/api/batch/{run_id}/reflow", json={"split": "train"}).json()
        check("错误样本回流接口", "moved" in reflow, str(reflow))

        published = client.post(f"/api/projects/{project_id}/publish", json={"note": "smoke"})
        check("发布项目", published.status_code == 200,
              f"version={published.json().get('version')} "
              f"userParams={len(published.json().get('userParams', {}))}")

        status = client.get(f"/api/projects/{project_id}/runtime").json()
        check("Runtime 状态", status["published"], f"status={status['status']}")
        trigger = client.post(f"/api/projects/{project_id}/runtime/trigger").json()
        check("Runtime 单次触发", trigger["record"]["verdict"] in {"OK", "NG"},
              f"verdict={trigger['record']['verdict']} ms={trigger['record']['durationMs']}")
        params = status["userParams"]
        if params:
            key = next(iter(params))
            spec = params[key]
            if spec["type"] in {"int", "float"}:
                update = client.post(
                    f"/api/projects/{project_id}/runtime/params",
                    json={"values": {key: spec["value"]}},
                )
                check("用户参数调整", update.status_code == 200, key)
        bad = client.post(
            f"/api/projects/{project_id}/runtime/params",
            json={"values": {"nope.nope": 1}},
        )
        check("越权参数被拒绝", bad.status_code == 422, str(bad.json().get("error"))[:60])

        overview = client.get("/api/monitoring/overview?hours=24").json()
        watched = next(
            (row for row in overview["projects"] if row["projectId"] == project_id), None
        )
        check("监控概览统计到本次推理", watched is not None and watched["total"] >= 1,
              f"项目 {len(overview['projects'])} 个 · 推理 {overview['summary']['total']} 次 "
              f"· 设备 {overview['summary']['onlineDevices']}/{overview['summary']['totalDevices']} 在线")
        monitored = client.get(
            f"/api/monitoring/records?hours=24&projectId={project_id}&pageSize=5"
        ).json()
        check("监控推理明细", monitored["total"] >= 1 and monitored["records"][0]["projectId"] == project_id,
              f"{monitored['total']} 条 verdict={monitored['records'][0]['verdict']}")
        filtered = client.get("/api/monitoring/records?hours=24&verdict=NG&pageSize=5").json()
        check("监控明细按判定筛选",
              all(row["verdict"] == "NG" for row in filtered["records"]),
              f"NG {filtered['total']} 条")

        samples = client.get(f"/api/projects/{project_id}/models/samples").json()
        check("训练样本统计", samples["sampleCount"] >= 4, str(samples["distribution"]))
        trained = client.post(f"/api/projects/{project_id}/models/train", json={"name": "smoke-svm"})
        check("训练分类模型", trained.status_code == 201,
              str(trained.json().get("metrics", {}))[:120])
        model_id = trained.json().get("id")

        if model_id:
            classify_graph = {
                "nodes": [
                    {"id": "in", "type": "image_input", "params": {"color_mode": "gray"}},
                    {"id": "cls", "type": "ai_classify",
                     "params": {"model_id": model_id, "ok_classes": "OK"}},
                    {"id": "verdict", "type": "ok_ng", "params": {}},
                ],
                "edges": [
                    {"source": "in", "sourceHandle": "image", "target": "cls", "targetHandle": "image"},
                    {"source": "cls", "sourceHandle": "result", "target": "verdict",
                     "targetHandle": "result"},
                ],
            }
            inference = client.post(
                f"/api/projects/{project_id}/pipeline/run",
                json={"graph": classify_graph, "imageId": images[0]["id"], "saveGraph": False},
            ).json()
            check("AI 分类节点推理", not inference["errors"],
                  f"verdict={inference['verdict']} {inference['measurements']}")

        devices = client.get("/api/devices").json()
        check("设备列表", len(devices["devices"]) >= 5,
              f"implemented={devices['implementedCount']}/{len(devices['devices'])}")
        grab = client.post(
            "/api/devices/sim_folder/grab",
            json={"projectId": project_id, "saveToDataset": True},
        ).json()
        check("模拟相机采集", "image" in grab, f"{grab.get('width')}x{grab.get('height')}")
        reserved = client.post("/api/devices/hik_mvs/connect", json={"settings": {}})
        check("预留设备返回 501", reserved.status_code == 501, str(reserved.json().get("error"))[:60])

        export = client.get(f"/api/projects/{project_id}/annotations/export/coco").json()
        check("COCO 导出", "images" in export["data"],
              f"annotations={len(export['data']['annotations'])}")
        yolo = client.get(f"/api/projects/{project_id}/annotations/export/yolo").json()
        check("YOLO 导出", "labels" in yolo["data"], f"files={len(yolo['data']['labels'])}")

        duplicated = client.post(f"/api/projects/{project_id}/duplicate").json()
        check("复制项目", duplicated["id"] != project_id, duplicated["name"])
        check("删除项目", client.delete(f"/api/projects/{duplicated['id']}").status_code == 204)

        versions = client.get(f"/api/projects/{project_id}/versions").json()
        check("版本列表", len(versions["versions"]) >= 1, f"versions={len(versions['versions'])}")

        # keep the database free of throw-away projects so demo data stays readable
        check("清理测试项目", client.delete(f"/api/projects/{project_id}").status_code == 204)

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + ", ".join(_failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
