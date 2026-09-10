import tempfile
import unittest
from pathlib import Path

from team_board.board import TaskBoard


class TaskBoardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.board = TaskBoard(Path(self.temp_dir.name) / "tasks.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_assigns_incrementing_ids(self) -> None:
        first = self.board.add("write docs")
        second = self.board.add("open pull request")

        self.assertEqual((first.id, second.id), (1, 2))
        self.assertEqual(len(self.board.load()), 2)

    def test_add_accepts_an_existing_empty_file(self) -> None:
        self.board.path.touch()

        task = self.board.add("first task")

        self.assertEqual(task.id, 1)

    def test_add_rejects_blank_title(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.board.add("   ")

    def test_complete_updates_task(self) -> None:
        task = self.board.add("run tests")

        completed = self.board.complete(task.id)

        self.assertTrue(completed.done)
        self.assertTrue(self.board.load()[0].done)

    def test_complete_rejects_unknown_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.board.complete(99)


if __name__ == "__main__":
    unittest.main()
