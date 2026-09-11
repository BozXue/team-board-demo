"""Output nodes: display, persist, export, signal."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.errors import NotImplementedFeature
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.render import judgement_banner, overlay_regions
from app.engine.types import Judgement, ParamSpec, PortSpec, PortType, Regions, Value
from app.utils.imageio import save_png, to_bgr


@register
class Display(Node):
    type = "display"
    label = "Display"
    category = "Output"
    description = "标记要在 Viewer / Runtime 主视图中显示的图像，可叠加区域轮廓与判定结果。"
    tags = ("output", "display", "显示")
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("regions", PortType.REGIONS, "区域（可选）", required=False),
        PortSpec("result", PortType.RESULT, "判定（可选）", required=False),
    )
    outputs = (PortSpec("image", PortType.IMAGE, "显示图"),)
    params = (
        ParamSpec("draw_regions", "bool", True, label="叠加区域轮廓"),
        ParamSpec("draw_verdict", "bool", True, label="叠加 OK/NG"),
        ParamSpec("primary", "bool", True, label="作为主显示",
                  description="Runtime 与批量测试的缩略图取自主显示节点"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        canvas = to_bgr(self.require_image(inputs))
        regions = inputs.get("regions")
        if params["draw_regions"] and isinstance(regions, Regions) and len(regions):
            canvas = overlay_regions(canvas, regions)
        result = inputs.get("result")
        if params["draw_verdict"] and isinstance(result, Judgement):
            canvas = judgement_banner(canvas, result)
        return {"image": canvas}


@register
class SaveImage(Node):
    type = "save_image"
    label = "Save Image"
    category = "Output"
    description = "把图像保存到项目 results 目录，可只在 NG 时保存（错误样本回流）。"
    tags = ("output", "save", "保存", "回流")
    deterministic = False
    inputs = (
        PortSpec("image", PortType.IMAGE, "图像"),
        PortSpec("result", PortType.RESULT, "判定（可选）", required=False),
    )
    outputs = (PortSpec("path", PortType.VALUE, "保存路径"),)
    params = (
        ParamSpec("folder", "str", "results", label="子目录"),
        ParamSpec("when", "enum", "always", label="保存条件", options=["always", "ng_only", "ok_only"],
                  level="business"),
        ParamSpec("prefix", "str", "", label="文件名前缀"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        image = self.require_image(inputs)
        result = inputs.get("result")
        verdict = result.verdict if isinstance(result, Judgement) else "UNKNOWN"
        if (params["when"] == "ng_only" and verdict != "NG") or (
            params["when"] == "ok_only" and verdict != "OK"
        ):
            ctx.log(f"跳过保存（条件 {params['when']}，当前 {verdict}）")
            return {"path": Value(0.0, "saved", "")}

        stem = (ctx.image_name or "frame").rsplit(".", 1)[0]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        folder = settings.projects_dir / (ctx.project_id or "_scratch") / params["folder"]
        filename = f"{params['prefix']}{stem}_{stamp}.png"
        path = save_png(folder / filename, image)
        ctx.log(f"已保存 {path}")
        return {
            "path": Value(1.0, "saved", ""),
            "report_payload": {"savedPath": str(path)},
        }


@register
class JsonResult(Node):
    type = "json_result"
    label = "JSON / CSV Result"
    category = "Output"
    description = "汇总测量值与判定，生成结构化结果（可导出 JSON/CSV，供 MES/上位机消费）。"
    tags = ("output", "json", "csv", "结果")
    inputs = (
        PortSpec("result", PortType.RESULT, "判定（可选）", required=False),
        PortSpec("regions", PortType.REGIONS, "区域（可选）", required=False),
        PortSpec("value", PortType.VALUE, "测量值（可选）", required=False),
    )
    outputs = (PortSpec("report", PortType.RESULT, "结果"),)
    params = (
        ParamSpec("format", "enum", "json", label="格式", options=["json", "csv"]),
        ParamSpec("include_regions", "bool", True, label="包含区域明细"),
        ParamSpec("max_regions", "int", 50, label="区域上限", min=1, max=1000),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        result = inputs.get("result")
        regions = inputs.get("regions")
        value = inputs.get("value")

        payload: dict[str, Any] = {
            "image": ctx.image_name,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "verdict": result.verdict if isinstance(result, Judgement) else "UNKNOWN",
            "reason": result.reason if isinstance(result, Judgement) else "",
            "measurements": dict(result.measurements) if isinstance(result, Judgement) else {},
        }
        if isinstance(value, Value):
            payload["measurements"][value.name] = value.value
        if params["include_regions"] and isinstance(regions, Regions):
            payload["regionCount"] = len(regions)
            payload["regions"] = [r.to_dict() for r in regions.items[: params["max_regions"]]]

        if params["format"] == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["key", "value"])
            writer.writerow(["image", payload["image"]])
            writer.writerow(["verdict", payload["verdict"]])
            for key, item in payload["measurements"].items():
                writer.writerow([key, item])
            payload["csv"] = buffer.getvalue()
        else:
            payload["json"] = json.dumps(payload, ensure_ascii=False, default=str)

        judgement = Judgement(
            verdict=payload["verdict"],
            reason=payload["reason"],
            measurements=payload["measurements"],
        )
        return {"report": judgement, "report_payload": payload}


@register
class SignalOutput(Node):
    type = "signal_output"
    label = "Signal (预留)"
    category = "Output"
    description = (
        "结果信号输出（数字 IO / TCP / Modbus / REST）。设备层以 Adapter 插件方式接入，"
        "核心平台只依赖统一的结果事件接口。"
    )
    tags = ("output", "plc", "signal", "预留")
    deterministic = False
    inputs = (PortSpec("result", PortType.RESULT, "判定"),)
    outputs = ()
    params = (
        ParamSpec("channel", "enum", "digital_io", label="通道",
                  options=["digital_io", "tcp", "modbus", "rest", "ros2"]),
        ParamSpec("address", "str", "", label="地址/端点"),
        ParamSpec("payload_template", "text", '{"verdict": "{verdict}"}', label="报文模板"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        raise NotImplementedFeature(
            f"信号输出通道 {params['channel']} 为 P2 能力：设备 Adapter 接入后启用（接口已预留）"
        )
