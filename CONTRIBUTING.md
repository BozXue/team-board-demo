# 协作指南

## 一项任务，一个分支，一个 Pull Request

不要让 Cursor 和 Codex 同时修改同一个分支。每项工作从最新的 `main` 创建独立分支：

```bash
git switch main
git pull --ff-only
git switch -c codex/add-filter
# Cursor 使用：git switch -c cursor/add-filter
```

完成后运行检查并提交：

```bash
make check
git status
git add <本次相关文件>
git commit -m "feat: add task filtering"
git push -u origin HEAD
```

然后在 GitHub 创建 Pull Request。CI 通过、另一位维护者审阅后再合并；合并方式建议使用 **Squash and merge**。

## 减少冲突

- 先在 GitHub Issue 写清验收标准，再分配给一个人或一个 AI 工具。
- 两个分支不要同时大改相同文件。
- 每天开始工作前同步 `main`，长任务中也要定期同步。
- 只暂存本任务文件，不使用无差别的 `git add .`。
- 遇到冲突时由熟悉这部分代码的人处理，并重新运行 `make check`。

## 提交消息

使用 Conventional Commits：

- `feat: ...`：新功能
- `fix: ...`：修复问题
- `test: ...`：只改测试
- `docs: ...`：只改文档
- `chore: ...`：维护工作
