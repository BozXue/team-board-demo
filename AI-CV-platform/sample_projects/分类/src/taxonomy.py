from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLASSES_PATH = ROOT / "config" / "classes.yaml"
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
TRAIN_DIR = DATA_DIR / "train"
VAL_DIR = DATA_DIR / "val"
YOLO_DATA_DIR = DATA_DIR / "yolo"
YOLO_WEIGHTS = MODEL_DIR / "grain_yolo.pt"
EFFNET_WEIGHTS = MODEL_DIR / "grain_effnet.pt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


RAW_DIR = ROOT / "rawdata" / "raw_data"


@dataclass(frozen=True)
class Species:
    id: str
    name: str
    aliases: list[str]
    subtypes: list[str]
    clip_prompts: list[str]


def load_species(path: Path = CLASSES_PATH) -> list[Species]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Species(
            id=item["id"],
            name=item["name"],
            aliases=list(item.get("aliases") or []),
            subtypes=list(item.get("subtypes") or []),
            clip_prompts=list(item.get("clip_prompts") or [item["name"]]),
        )
        for item in raw["species"]
    ]


def folder_to_species(species: list[Species] | None = None) -> dict[str, Species]:
    """目录名（中文或英文别名）→ 种类。"""
    species = species or load_species()
    mapping: dict[str, Species] = {}
    for item in species:
        mapping[item.name] = item
        mapping[item.id] = item
        for alias in item.aliases:
            mapping[alias] = item
    return mapping


def name_to_id(species: list[Species]) -> dict[str, str]:
    return {item.name: item.id for item in species}
