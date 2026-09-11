"""Task understanding: natural language -> structured vision task."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TASK_TYPES = [
    "defect_detection",
    "counting",
    "measurement",
    "presence",
    "colony_localization",
    "classification",
    "anomaly_detection",
    "positioning",
    "unknown",
]

TASK_LABELS = {
    "defect_detection": "缺陷/污渍检测",
    "counting": "计数",
    "measurement": "尺寸/面积测量",
    "presence": "存在性检测",
    "colony_localization": "克隆/目标定位",
    "classification": "分类判型",
    "anomaly_detection": "异常检测",
    "positioning": "定位",
    "unknown": "未识别",
}

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "defect_detection": ("缺陷", "污点", "污渍", "脏污", "瑕疵", "划痕", "破损", "异物", "黑点",
                         "白点", "麻点", "气泡", "defect", "scratch", "stain", "spot"),
    "counting": ("计数", "数量", "个数", "多少个", "统计数", "count"),
    "measurement": ("测量", "尺寸", "长度", "宽度", "直径", "面积", "间距", "公差", "角度",
                    "measure", "size", "diameter", "area"),
    "presence": ("有无", "存在", "漏装", "缺件", "装配", "是否有", "presence", "missing"),
    "colony_localization": ("克隆", "菌落", "集落", "colony", "ipsc", "细胞团", "克隆中心",
                            "培养", "干细胞"),
    "classification": ("分类", "判型", "形态", "类别", "等级", "分级", "classify", "grade",
                       "致密", "分化", "死细胞"),
    "anomaly_detection": ("异常", "无缺陷样本", "只有好样本", "anomaly", "novelty", "未知缺陷"),
    "positioning": ("定位", "位置", "坐标", "中心点", "抓取", "对位", "locate", "position"),
}

_DARK_TARGET = ("黑色", "黑点", "暗", "发黑", "dark", "black", "污点", "污渍")
_BRIGHT_TARGET = ("白色", "亮", "发白", "高亮", "bright", "white", "反光")
_BRIGHT_BACKGROUND = ("白布", "白色背景", "浅色", "白底", "亮背景")
_DARK_BACKGROUND = ("黑布", "黑色背景", "深色", "黑底", "暗背景")


@dataclass
class Intent:
    text: str
    task_type: str = "unknown"
    confidence: float = 0.0
    keywords: list[str] = field(default_factory=list)
    target_polarity: str = "unknown"
    background_polarity: str = "unknown"
    target_hint: str = ""
    constraints: dict = field(default_factory=dict)
    color_relevant: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "taskType": self.task_type,
            "taskLabel": TASK_LABELS.get(self.task_type, self.task_type),
            "confidence": round(self.confidence, 2),
            "keywords": self.keywords,
            "targetPolarity": self.target_polarity,
            "backgroundPolarity": self.background_polarity,
            "targetHint": self.target_hint,
            "constraints": self.constraints,
            "colorRelevant": self.color_relevant,
        }


def parse(text: str) -> Intent:
    """Keyword + pattern based intent parsing (no LLM required)."""
    raw = (text or "").strip()
    lowered = raw.lower()
    intent = Intent(text=raw)

    scores: dict[str, int] = {}
    matched: list[str] = []
    for task, words in _KEYWORDS.items():
        hits = [word for word in words if word in lowered]
        if hits:
            scores[task] = len(hits)
            matched.extend(hits)
    if scores:
        best = max(scores, key=lambda k: scores[k])
        intent.task_type = best
        intent.confidence = min(0.95, 0.45 + 0.18 * scores[best])
        intent.keywords = sorted(set(matched))

    if any(word in lowered for word in _DARK_TARGET):
        intent.target_polarity = "dark"
    elif any(word in lowered for word in _BRIGHT_TARGET):
        intent.target_polarity = "bright"
    if any(word in lowered for word in _BRIGHT_BACKGROUND):
        intent.background_polarity = "bright"
        if intent.target_polarity == "unknown":
            intent.target_polarity = "dark"
    elif any(word in lowered for word in _DARK_BACKGROUND):
        intent.background_polarity = "dark"
        if intent.target_polarity == "unknown":
            intent.target_polarity = "bright"

    intent.color_relevant = any(
        word in lowered for word in ("颜色", "色差", "红", "绿", "蓝", "黄", "color")
    )

    target = re.search(r"检测(.{1,12}?)(?:的)?(?:缺陷|污点|污渍|瑕疵|异物|$|，|。|,)", raw)
    if target:
        intent.target_hint = target.group(1).strip()

    constraints: dict = {}
    size = re.search(r"(?:大于|超过|最小|≥|>=)\s*(\d+(?:\.\d+)?)\s*(mm|毫米|像素|px|平方毫米|mm2|mm²)?",
                     raw)
    if size:
        constraints["minSize"] = float(size.group(1))
        constraints["minSizeUnit"] = size.group(2) or "px"
    count = re.search(r"(\d+)\s*(?:个|颗|只|件)", raw)
    if count:
        constraints["expectedCount"] = int(count.group(1))
    tolerance = re.search(r"(\d+(?:\.\d+)?)\s*(?:±|\+/-)\s*(\d+(?:\.\d+)?)", raw)
    if tolerance:
        constraints["nominal"] = float(tolerance.group(1))
        constraints["tolerance"] = float(tolerance.group(2))
    if any(word in lowered for word in ("不允许", "零缺陷", "不能有", "一个都不能")):
        constraints["zeroTolerance"] = True
    intent.constraints = constraints
    return intent


def merge_llm(intent: Intent, payload: dict | None) -> Intent:
    """Let the LLM refine the task type, but keep it inside the enum."""
    if not payload:
        return intent
    task = payload.get("taskType")
    if task in TASK_TYPES and task != "unknown":
        intent.task_type = task
        intent.confidence = max(intent.confidence, 0.8)
    polarity = payload.get("targetPolarity")
    if polarity in {"dark", "bright"}:
        intent.target_polarity = polarity
    if isinstance(payload.get("constraints"), dict):
        intent.constraints = {**intent.constraints, **payload["constraints"]}
    return intent
