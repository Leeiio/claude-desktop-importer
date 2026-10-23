# claude-desktop-importer

[English](README.md) | 简体中文

把 Claude Code CLI 的会话导入 Claude Desktop 侧边栏：一个不漏，标题用真实标题，顺序按真实活动时间。

Claude Desktop 自带 **帮助 → 故障排除 → 导入 Claude Code CLI 会话…**，但它：

- **静默跳过** 通过 Agent SDK 或 `claude -p` 启动的会话（无界面、`sdk-*` 入口）；
- **静默跳过** 未在 `~/.claude.json` 中按完全相同路径标记为受信任的项目；
- **一律用第一句提问当标题**，即使 Claude Code 已经生成了标题，或者你用 `/rename` 起过名字（[anthropics/claude-code#89857](https://github.com/anthropics/claude-code/issues/89857)）；
- **用会话文件的修改时间当"最后活动时间"**，导致侧边栏排序错乱：Claude Code 会在最后一条消息之后很久还往文件末尾追加元数据（[anthropics/claude-code#83203](https://github.com/anthropics/claude-code/issues/83203)）；
- 跳过了什么、为什么跳过，一概不告诉你。

这个工具做同样的事，但每一步都摆在明面上，还能修复内置导入已经加进去的会话。

## 安装

需要 Python 3.9 及以上，无第三方依赖。装了 [uv](https://docs.astral.sh/uv/) 的话，不用安装就能直接运行：

```bash
uvx claude-desktop-importer scan
```

也可以把命令安装到系统里：

```bash
uv tool install claude-desktop-importer     # 或者：pipx install claude-desktop-importer
```

以后升级用 `uv tool upgrade claude-desktop-importer`（或 `pipx upgrade claude-desktop-importer`）；`uvx claude-desktop-importer@latest` 则每次都运行最新版本。

也可以从源码运行：

```bash
git clone https://github.com/Leeiio/claude-desktop-importer.git
cd claude-desktop-importer
python3 -m claude_desktop_importer scan
```

## 用法

下面的例子用的是安装后的命令；用 uvx 的话在前面加上 `uvx` 即可（`uvx claude-desktop-importer import --apply`）。不加 `--apply` 时，所有命令都只展示将要做什么，不写任何文件。

```bash
claude-desktop-importer scan             # 哪些会话不在侧边栏里，以及跳过某些会话的原因
claude-desktop-importer import           # 预览
claude-desktop-importer import --apply   # 导入，然后完全退出并重新打开 Claude Desktop
```

以后 CLI 里有了新会话，再跑一遍 `scan` 和 `import --apply`，然后重启 Claude Desktop 即可。已经在侧边栏里的会话，`import` 一律不碰。

要修复 Claude Desktop 自带导入产生的标题和顺序，**先退出 Claude Desktop**（按 Cmd+Q，只关窗口不算）：

```bash
claude-desktop-importer fix              # 预览
claude-desktop-importer fix --apply
```

每次 `--apply` 都会先备份。撤销方法：

```bash
claude-desktop-importer restore                          # 列出所有备份
claude-desktop-importer restore 20261022-195403-fix      # 预览
claude-desktop-importer restore 20261022-195403-fix --apply
```

所有命令共用的选项：

| 选项 | 默认值 |
| --- | --- |
| `--claude-dir` | `$CLAUDE_CONFIG_DIR`，否则 `~/.claude` |
| `--store` | 自动查找 Claude Desktop 的 `claude-code-sessions` 文件夹 |
| `--profile` | 只有一个 `<account>/<org>` 文件夹时用它，否则用 Claude Desktop 最近登录的那个 |
| `--backup-dir` | `~/.claude-desktop-importer/backups` |

`import` 还支持 `--only ID…`（完整 ID 或前缀）和 `--include-desktop`（见下文）。

## 工作原理

Claude Code 把每个会话存在 `~/.claude/projects/<文件夹>/<会话 ID>.jsonl`。Claude Desktop 的侧边栏则是一个文件夹，每个会话对应一个小 JSON 记录，位于 `~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/`。Claude Desktop 在启动时读取这个文件夹。

`import` 为每个缺失的会话写一个 `local_<会话 ID>.json`，格式与内置导入相同，其中：

- **标题**：优先用你 `/rename` 的标题，其次是 Claude Code 生成的标题，最后才是第一句真正的提问（会去掉 IDE 上下文，并跳过 `/model` 这类不带参数的斜杠命令）；
- **创建时间 / 最后活动时间**：第一条和最后一条真实消息的时间戳；
- **模型** 和 **权限模式**：会话最后一次使用的值。

它从不修改会话文件本身。以下情况会被跳过：

- 没有任何消息；
- 没有记录工作目录，或者该目录已经不存在；
- 会话文件不在其工作目录对应的项目文件夹里（Claude Desktop 无法恢复这种会话）；
- 正被某个运行中的 Claude Code 进程打开；
- 已经在侧边栏里，包括 Desktop 会话被压缩或续接之前的那些旧会话文件；
- 在 Claude Desktop 里创建、但已不在其侧边栏中。这种多半是你在那里删掉的，所以需要加 `--include-desktop` 才会导入。

它不会仅仅因为项目文件夹没有在 `~/.claude.json` 里标记为受信任就跳过它。

`fix` 只处理被标记为"从其他界面导入"的记录（也就是内置导入创建的那些）。你在 Claude Desktop 里手动改过的标题，以及相差不到 5 分钟的时间，都不会动。被替换掉的旧标题会保存在记录的 `previousTitles` 里。

## 安全性

- 不加 `--apply` 就只是预演。
- 每次 `--apply` 都会先写备份，并附一份清单，记下这次要新增的文件，以及将被修改文件的原件；`restore` 可以原样还原。
- `import` 可以在 Claude Desktop 运行时执行，新会话在下次重启后出现。
- `fix` 和 `restore` 在 Claude Desktop 开着时会拒绝执行。Claude Desktop 把会话列表保存在内存里，某个会话一有变化就会把它的记录写回磁盘，这会冲掉你的修改。
- 记录采用原子写入、紧凑格式、仅本人可读（权限 600），与 Claude Desktop 自己的写法一致。

## 已知限制

- 在 macOS 和 2026 年 10 月版的 Claude Desktop 上开发和测试。Windows 和 Linux 的文件夹位置是推测的，而且在这两个平台上工具无法判断 Claude Desktop 是否在运行，所以退出 Claude Desktop 之后，`fix --apply` 和 `restore --apply` 需要加 `--force`。
- 依赖 Claude Desktop 的内部文件，这些文件没有公开文档，任何一次更新都可能改变格式。请先跑 `scan` 和预演；如果结果不对，用 `restore` 还原。
- 你在 Claude Desktop 里删除会话后，本工具找不到任何删除痕迹。如果你从侧边栏删掉了一个导入的 CLI 会话，下次 `import` 还会再列出它：请改用归档，或者用 `--only` 只导入指定会话。
- 一次只处理一个侧边栏：如果你用多个账号或组织，请用 `--profile` 指定。

## 开发

```bash
python3 -m unittest discover -s tests -t .
```

测试会在临时目录里构造假的会话文件和侧边栏文件夹，不会读取你的真实数据。新版本由 GitHub Actions 发布到 PyPI，流程见 [RELEASING.md](RELEASING.md)。

## 许可证

[MIT](LICENSE)。本项目与 Anthropic 无关联，也未获其认可。
