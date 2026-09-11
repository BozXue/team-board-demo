"""Judge nodes: values/results -> OK/NG."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.engine.base import Node, NodeContext
from app.engine.registry import register
from app.engine.types import Judgement, ParamSpec, PortSpec, PortType, Regions, Value

_OPERATORS = ["<", "<=", ">", ">=", "between", "outside"]


def _compare(value: float, operator: str, limit: float, upper: float) -> bool:
    if operator == "<":
        return value < limit
    if operator == "<=":
        return value <= limit
    if operator == ">":
        return value > limit
    if operator == ">=":
        return value >= limit
    if operator == "between":
        return limit <= value <= upper
    return value < limit or value > upper


@register
class ThresholdJudge(Node):
    type = "threshold_judge"
    label = "Threshold Judge"
    category = "Judge"
    description = "把测量值与判定阈值比较，输出 OK/NG。用户模式下通常只暴露这里的阈值。"
    tags = ("judge", "判定", "阈值")
    inputs = (PortSpec("value", PortType.VALUE, "测量值"),)
    outputs = (PortSpec("result", PortType.RESULT, "判定"),)
    params = (
        ParamSpec("operator", "enum", "<=", label="判定条件", options=_OPERATORS, level="business"),
        ParamSpec("limit", "float", 100.0, label="阈值", min=-1e9, max=1e9, step=0.1,
                  level="business"),
        ParamSpec("upper", "float", 0.0, label="上限", min=-1e9, max=1e9, step=0.1,
                  level="business", depends_on=("operator", ("between", "outside"))),
        ParamSpec("name", "str", "judge", label="判定名称"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        value = inputs.get("value")
        if isinstance(value, Value):
            measured = float(value.value)
            label = value.name
            unit = value.unit
        elif isinstance(value, (int, float)):
            measured = float(value)
            label, unit = "value", ""
        else:
            raise ValidationError("Threshold Judge 需要 Value 输入")
        ok = _compare(measured, params["operator"], params["limit"], params["upper"])
        bound = (
            f"{params['limit']} ~ {params['upper']}"
            if params["operator"] in {"between", "outside"} else str(params["limit"])
        )
        reason = f"{label}={round(measured, 3)}{unit} {params['operator']} {bound} → {'OK' if ok else 'NG'}"
        return {
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason=reason,
                measurements={label: round(measured, 4), f"{params['name']}_limit": params["limit"]},
            )
        }


@register
class CountJudge(Node):
    type = "count_judge"
    label = "Count Judge"
    category = "Judge"
    description = "按区域数量判定，例如“不允许出现任何缺陷”或“必须有 4 个孔”。"
    tags = ("judge", "count", "计数判定")
    inputs = (PortSpec("regions", PortType.REGIONS, "区域"),)
    outputs = (PortSpec("result", PortType.RESULT, "判定"),)
    params = (
        ParamSpec("operator", "enum", "<=", label="判定条件", options=_OPERATORS, level="business"),
        ParamSpec("limit", "float", 0.0, label="数量阈值", min=0.0, max=1e6, step=1, level="business"),
        ParamSpec("upper", "float", 0.0, label="上限", min=0.0, max=1e6, step=1, level="business",
                  depends_on=("operator", ("between", "outside"))),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        regions = inputs.get("regions")
        if not isinstance(regions, Regions):
            raise ValidationError("Count Judge 需要 Regions 输入")
        count = float(len(regions))
        ok = _compare(count, params["operator"], params["limit"], params["upper"])
        return {
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason=f"缺陷数量={int(count)} {params['operator']} {params['limit']} → {'OK' if ok else 'NG'}",
                measurements={"defect_count": int(count)},
            )
        }


class _LogicBase(Node):
    category = "Judge"
    inputs = (
        PortSpec("a", PortType.RESULT, "判定 A"),
        PortSpec("b", PortType.RESULT, "判定 B"),
    )
    outputs = (PortSpec("result", PortType.RESULT, "判定"),)
    op = "and"

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        a, b = inputs.get("a"), inputs.get("b")
        if not isinstance(a, Judgement) or not isinstance(b, Judgement):
            raise ValidationError("逻辑节点需要两个判定输入")
        ok = (a.ok and b.ok) if self.op == "and" else (a.ok or b.ok)
        measurements = {**a.measurements, **b.measurements}
        joiner = " 且 " if self.op == "and" else " 或 "
        return {
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason=joiner.join(filter(None, [a.reason, b.reason])),
                measurements=measurements,
            )
        }


@register
class LogicAnd(_LogicBase):
    type = "logic_and"
    label = "AND"
    op = "and"
    description = "两个判定同时 OK 才 OK。"
    tags = ("judge", "logic", "与")


@register
class LogicOr(_LogicBase):
    type = "logic_or"
    label = "OR"
    op = "or"
    description = "任一判定 OK 即 OK。"
    tags = ("judge", "logic", "或")


@register
class OkNg(Node):
    type = "ok_ng"
    label = "OK / NG"
    category = "Judge"
    description = "流程终点：汇总判定，输出最终 OK/NG 与说明文本（Runtime 显示的就是它）。"
    tags = ("judge", "ok", "ng", "输出")
    inputs = (PortSpec("result", PortType.RESULT, "判定"),)
    outputs = (PortSpec("result", PortType.RESULT, "最终判定"),)
    params = (
        ParamSpec("invert", "bool", False, label="反转判定"),
        ParamSpec("ok_message", "str", "合格", label="OK 提示", level="business"),
        ParamSpec("ng_message", "str", "不合格", label="NG 提示", level="business"),
    )

    def process(self, inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        source = inputs.get("result")
        if not isinstance(source, Judgement):
            raise ValidationError("OK/NG 需要判定输入")
        ok = source.ok if not params["invert"] else not source.ok
        message = params["ok_message"] if ok else params["ng_message"]
        return {
            "result": Judgement(
                verdict="OK" if ok else "NG",
                reason=f"{message}｜{source.reason}" if source.reason else message,
                measurements=source.measurements,
            )
        }
