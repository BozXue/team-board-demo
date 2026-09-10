# Team Board Demo

这是一个用于练习 **Cursor + Codex + GitHub** 协作的虚拟项目。它提供一个很小的命令行任务板：可以添加、查看和完成任务。项目只使用 Python 标准库，便于把注意力放在 Git 工作流上。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

team-board add "练习创建 Pull Request"
team-board list
team-board done 1
make check
```

也可以不安装，直接运行：

```bash
PYTHONPATH=src python3 -m team_board add "第一个任务"
PYTHONPATH=src python3 -m team_board list
```

本地任务保存在 `data/tasks.json`；该文件已被 Git 忽略，不会进入共享仓库。

## 仓库结构

```text
.
├── .cursor/rules/project.mdc   # Cursor 的长期项目规则
├── .github/                    # CI、Issue 和 PR 模板
├── AGENTS.md                   # Codex 的长期项目规则
├── CONTRIBUTING.md             # 人和 AI 共用的 Git 协作方式
├── src/team_board/             # 应用代码
└── tests/                      # 自动化测试
```

## 推荐工作流

`main` 始终保持可运行。每项任务先建 Issue，然后只交给 Cursor 或 Codex 中的一方在独立分支完成：

```text
GitHub Issue
    ↓
codex/<topic> 或 cursor/<topic>
    ↓
提交小而清晰的 commit
    ↓
Pull Request + GitHub Actions
    ↓
审阅后合并到 main
```

详细规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。在 GitHub 仓库设置中，建议保护 `main`，要求通过 Pull Request 和 `test` 检查后才能合并。

## 首次连接 GitHub

先在 GitHub 新建一个**空仓库**（不要勾选自动创建 README），然后执行：

```bash
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

如果使用 SSH，把远程地址换成 `git@github.com:<你的用户名>/<仓库名>.git`。
