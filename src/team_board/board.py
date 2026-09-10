"""Storage and business logic for the demo task board."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Task:
    id: int
    title: str
    done: bool = False


class TaskBoard:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []
        content = self.path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        payload = json.loads(content)
        return [Task(**item) for item in payload]

    def save(self, tasks: list[Task]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(task) for task in tasks]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def add(self, title: str) -> Task:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("task title cannot be empty")

        tasks = self.load()
        task = Task(id=max((item.id for item in tasks), default=0) + 1, title=clean_title)
        tasks.append(task)
        self.save(tasks)
        return task

    def complete(self, task_id: int) -> Task:
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                task.done = True
                self.save(tasks)
                return task
        raise ValueError(f"task {task_id} does not exist")
