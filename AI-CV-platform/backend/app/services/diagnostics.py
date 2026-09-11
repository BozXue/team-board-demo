"""Image quality diagnosis.

The Copilot needs numbers, not adjectives: this module measures exposure,
contrast, sharpness, noise, background uniformity and target scale so that
recommendations ("先改善照明", "改用局部阈值") can be justified and reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.engine.algorithms import texture as tex
from app.utils.imageio import fit_within, load_image, to_gray

SEVERITY_ORDER = {"ok": 0, "info": 1, "warning": 2, "critical": 3}


@dataclass
class Finding:
    key: str
    level: str
    title: str
    detail: str
    advice: str = ""
    value: float | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "level": self.level,
            "title": self.title,
            "detail": self.detail,
            "advice": self.advice,
            "value": None if self.value is None else round(float(self.value), 3),
        }


@dataclass
class Diagnosis:
    metrics: dict[str, float] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def level(self) -> str:
        if not self.findings:
            return "ok"
        return max((f.level for f in self.findings), key=lambda l: SEVERITY_ORDER.get(l, 0))

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "metrics": {k: round(float(v), 3) for k, v in self.metrics.items()},
            "findings": [f.to_dict() for f in sorted(
                self.findings, key=lambda f: -SEVERITY_ORDER.get(f.level, 0)
            )],
        }


def analyze_path(path: str | Path, max_side: int = 1024) -> Diagnosis:
    return analyze(fit_within(load_image(path), max_side))


def analyze(image: np.ndarray) -> Diagnosis:
    gray = to_gray(image)
    height, width = gray.shape[:2]
    data = gray.astype(np.float32)

    mean = float(data.mean())
    std = float(data.std())
    p1, p99 = (float(v) for v in np.percentile(data, [1, 99]))
    saturated_high = float(np.count_nonzero(gray >= 250)) / gray.size * 100.0
    saturated_low = float(np.count_nonzero(gray <= 5)) / gray.size * 100.0
    dynamic_range = p99 - p1

    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    # Noise estimate: high-frequency residual after median filtering.
    noise = float(np.median(np.abs(data - cv2.medianBlur(gray, 3).astype(np.float32)))) * 1.4826

    background = cv2.GaussianBlur(data, (0, 0), max(4.0, min(height, width) / 40.0))
    illumination_spread = float(background.max() - background.min())
    illumination_cv = float(background.std() / (background.mean() + 1e-6) * 100.0)

    texture_map = tex.local_std(gray, tex.resolve_window(height))
    texture_strength = float(texture_map.mean())
    texture_ratio = float(np.count_nonzero(texture_map > texture_map.mean() * 1.5)) / texture_map.size * 100.0

    edges = cv2.Canny(gray, 60, 160)
    edge_density = float(np.count_nonzero(edges)) / edges.size * 100.0

    is_color = image.ndim == 3
    color_saturation = 0.0
    if is_color:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        color_saturation = float(hsv[..., 1].mean())

    metrics = {
        "width": width,
        "height": height,
        "mean": mean,
        "std": std,
        "p1": p1,
        "p99": p99,
        "dynamicRange": dynamic_range,
        "overexposedPercent": saturated_high,
        "underexposedPercent": saturated_low,
        "sharpness": laplacian_var,
        "noiseSigma": noise,
        "illuminationSpread": illumination_spread,
        "illuminationCv": illumination_cv,
        "textureStrength": texture_strength,
        "texturePercent": texture_ratio,
        "edgeDensity": edge_density,
        "colorSaturation": color_saturation,
        "isColor": float(is_color),
    }

    findings: list[Finding] = []

    if saturated_high > 2.0:
        findings.append(Finding(
            "overexposure", "critical" if saturated_high > 10 else "warning",
            "过曝", f"{saturated_high:.1f}% 像素接近饱和（>=250）",
            "降低曝光/增益或增加漫射，饱和区域的信息无法用算法找回", saturated_high,
        ))
    if saturated_low > 5.0:
        findings.append(Finding(
            "underexposure", "critical" if saturated_low > 20 else "warning",
            "欠曝", f"{saturated_low:.1f}% 像素接近全黑（<=5）",
            "提高曝光或增强照明；必要时用 Gamma/Normalize 提亮暗部", saturated_low,
        ))
    if dynamic_range < 60:
        findings.append(Finding(
            "low_contrast", "warning", "对比度偏低",
            f"1%-99% 灰度跨度仅 {dynamic_range:.0f}",
            "优先改善照明角度；算法侧可加 CLAHE 或 Normalize", dynamic_range,
        ))
    if laplacian_var < 80:
        findings.append(Finding(
            "blur", "critical" if laplacian_var < 25 else "warning", "图像偏模糊",
            f"Laplacian 方差 {laplacian_var:.0f}（低于 80 通常偏软）",
            "检查对焦、景深与运动模糊；模糊图像会显著抬高漏检率", laplacian_var,
        ))
    if noise > 6.0:
        findings.append(Finding(
            "noise", "warning", "噪声偏大", f"估计噪声 σ≈{noise:.1f}",
            "增加曝光/降低增益；流程中加 Gaussian 或 Median 滤波", noise,
        ))
    if illumination_cv > 12.0:
        findings.append(Finding(
            "uneven_illumination", "warning", "背景不均匀",
            f"背景亮度变异系数 {illumination_cv:.1f}%（跨度 {illumination_spread:.0f} 灰阶）",
            "优先改善照明；算法侧使用 Adaptive Threshold 或 CLAHE，避免固定阈值",
            illumination_cv,
        ))
    if edge_density > 25.0:
        findings.append(Finding(
            "busy_background", "info", "纹理/边缘密集",
            f"边缘像素占比 {edge_density:.1f}%",
            "背景纹理复杂，建议先用 ROI 限定区域，或考虑纹理/AI 方法", edge_density,
        ))
    if not findings:
        findings.append(Finding(
            "quality_ok", "ok", "成像质量良好",
            f"均值 {mean:.0f}，动态范围 {dynamic_range:.0f}，清晰度 {laplacian_var:.0f}",
            "可直接进入流程搭建", None,
        ))

    return Diagnosis(metrics=metrics, findings=findings)


def aggregate(diagnoses: list[Diagnosis]) -> dict:
    """Average metrics across a sample of images plus the union of findings."""
    if not diagnoses:
        return {"level": "ok", "metrics": {}, "findings": [], "sampleCount": 0}
    keys = diagnoses[0].metrics.keys()
    metrics = {
        key: float(np.mean([d.metrics.get(key, 0.0) for d in diagnoses])) for key in keys
    }
    seen: dict[str, Finding] = {}
    for diagnosis in diagnoses:
        for finding in diagnosis.findings:
            if finding.key == "quality_ok" and len(diagnoses) > 1:
                continue
            current = seen.get(finding.key)
            if current is None or SEVERITY_ORDER.get(finding.level, 0) > SEVERITY_ORDER.get(
                current.level, 0
            ):
                seen[finding.key] = finding
    findings = sorted(seen.values(), key=lambda f: -SEVERITY_ORDER.get(f.level, 0))
    level = findings[0].level if findings else "ok"
    return {
        "level": level,
        "metrics": {k: round(v, 3) for k, v in metrics.items()},
        "findings": [f.to_dict() for f in findings],
        "sampleCount": len(diagnoses),
    }
