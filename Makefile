.PHONY: install test check demo

install:
	python3 -m pip install -e .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: test
	PYTHONPATH=src python3 -m compileall -q src tests

demo:
	PYTHONPATH=src python3 -m team_board --file /tmp/team-board-demo.json add "创建第一个 Pull Request"
	PYTHONPATH=src python3 -m team_board --file /tmp/team-board-demo.json list
