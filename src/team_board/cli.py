"""Command-line interface for Team Board."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from team_board.board import TaskBoard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A tiny shared task board demo")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("data/tasks.json"),
        help="JSON storage path (default: data/tasks.json)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add_parser = commands.add_parser("add", help="add a task")
    add_parser.add_argument("title")

    commands.add_parser("list", help="list tasks")

    done_parser = commands.add_parser("done", help="complete a task")
    done_parser.add_argument("id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    board = TaskBoard(args.file)

    try:
        if args.command == "add":
            task = board.add(args.title)
            print(f"Added #{task.id}: {task.title}")
        elif args.command == "done":
            task = board.complete(args.id)
            print(f"Completed #{task.id}: {task.title}")
        else:
            tasks = board.load()
            if not tasks:
                print("No tasks yet.")
            for task in tasks:
                marker = "x" if task.done else " "
                print(f"[{marker}] #{task.id} {task.title}")
    except (OSError, ValueError, TypeError) as error:
        print(f"Error: {error}")
        return 1
    return 0
