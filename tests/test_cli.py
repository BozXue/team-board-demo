import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from team_board.cli import main


class CliTest(unittest.TestCase):
    def test_add_list_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "tasks.json")
            output = io.StringIO()

            with redirect_stdout(output):
                self.assertEqual(main(["--file", path, "add", "review PR"]), 0)
                self.assertEqual(main(["--file", path, "list"]), 0)
                self.assertEqual(main(["--file", path, "done", "1"]), 0)

            text = output.getvalue()
            self.assertIn("Added #1: review PR", text)
            self.assertIn("[ ] #1 review PR", text)
            self.assertIn("Completed #1: review PR", text)


if __name__ == "__main__":
    unittest.main()
