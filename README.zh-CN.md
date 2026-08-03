# Codex Token Usage

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/catchmeee2002/codex-token-usage/actions/workflows/ci.yml/badge.svg)](https://github.com/catchmeee2002/codex-token-usage/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

审计并可视化本机 Codex 会话日志中的 Token 用量。项目提供中英文终端仪表盘、适合脚本调用的
文本和 JSON 报告、滚动或自定义时间范围，并能排除导入的 Claude Code 历史，同时保留导入线程
在 Codex 中继续使用后产生的真实用量。

> 这是独立社区项目，与 OpenAI 没有隶属或官方背书关系。

## 功能

- 支持中文和英文的全屏终端 UI
- 在 UI 中按 `l` 即时切换语言
- 在 UI 中按 `Tab` 切换每日用量和 Effort 分析
- 滚动 24 小时、最近 7 天、最近 30 天、全部历史和自定义日期
- 标准坐标图：多日范围按日期、完整单日按小时展示，并标记尚未结束的统计区间
- 从多日柱逐层下钻到具体日期和小时详情，无需手工输入日期
- 中文或英文文本输出
- 带 `schema_version: 1` 的稳定 JSON 输出
- 主线程和子代理用量拆分
- 基于结构化证据排除导入的 Claude Code 历史
- 处理重复快照，并显式报告数据完整性警告
- 持久增量扫描缓存，并提供明确的强制重扫入口
- 报告不会包含提示词、回答、API Key、会话 ID 或源文件路径

## 安装

需要 Python 3.11 或更高版本。

使用 [`pipx`](https://pipx.pypa.io/) 从 GitHub 安装：

```bash
pipx install git+https://github.com/catchmeee2002/codex-token-usage.git
```

也可以从源码安装：

```bash
git clone https://github.com/catchmeee2002/codex-token-usage.git
cd codex-token-usage
python3 -m pip install .
```

在类 Unix 系统上，运行时只使用 Python 标准库；Windows 会自动安装 `windows-curses` 兼容包和
IANA `tzdata` 时区数据。

## 快速开始

打开交互式仪表盘：

```bash
codex-token-usage
```

按键说明：

| 按键 | 操作 |
|---|---|
| `↑` / `↓` 或 `j` / `k` | 选择统计范围 |
| `←` / `→` | 选择图表柱子并显示精确值 |
| `[` / `]` | 在日图选择日期柱，或在小时详情切换自然日 |
| `Enter` | 应用其他菜单范围，或下钻当前选中的日期柱 |
| `Backspace` | 返回上一级图表 |
| `r` | 检查文件变化并增量刷新当前报告 |
| `R` | 强制全盘重扫并重建扫描缓存 |
| `l` | 在中文和英文之间切换 |
| `Tab` 或 `e` | 切换用量页和 Effort 分析页 |
| `q` 或 `Esc` | 退出 |

直接以英文启动 UI：

```bash
codex-token-usage --ui --lang en
```

## 文本与 JSON 报告

传入报告参数时会使用非交互文本模式。不指定时间参数时，文本模式只统计滚动的最近 7 天，
并会明确提示这不是全部历史。

```bash
# 中文文本，滚动最近 7 天
codex-token-usage --text

# 英文文本
codex-token-usage --text --lang en

# 全部历史
codex-token-usage --all

# 其他滚动窗口
codex-token-usage --since 24h
codex-token-usage --since 2w

# 按本地日期统计，起止日期均包含
codex-token-usage \
  --from 2026-07-18 \
  --to 2026-07-25 \
  --timezone Asia/Shanghai

# 查看某个本地自然日的逐小时分布
codex-token-usage \
  --from 2026-07-25 \
  --to 2026-07-25 \
  --timezone Asia/Shanghai

# 机器可读输出
codex-token-usage --all --json
```

常用参数：

| 参数 | 用途 |
|---|---|
| `--ui` | 打开全屏终端 UI |
| `--text` | 强制使用非交互文本输出 |
| `--lang {zh,en}` | 选择 UI 初始语言或文本语言 |
| `--all` | 扫描全部历史 |
| `--since DURATION` | 选择 `24h`、`7d`、`2w` 等滚动窗口 |
| `--from ISO` / `--to ISO` | 选择自定义范围 |
| `--timezone IANA` | 设置日期解析和时间分桶使用的时区 |
| `--json` | 输出稳定的机器可读数据 |
| `--no-daily` | 隐藏文本输出中的用量分布图 |
| `--strict` | 出现完整性或认证警告时返回非零状态 |
| `--codex-home PATH` | 覆盖 `CODEX_HOME` 和 `~/.codex` 自动发现路径 |
| `--rebuild-cache` | 忽略已有证据，完整重扫全部会话文件并重建缓存 |
| `--no-cache` | 本次运行不读取或写入扫描缓存 |

## 扫描缓存

默认扫描会检查每个会话文件的元数据，复用未变化文件的解析证据，并且只读取持续增长 JSONL 的
新增后缀。每次报告仍会重新读取认证和导入账本，并重新执行计数、导入边界与跨文件去重逻辑。

可丢弃的 SQLite 缓存位于
`$CODEX_HOME/.cache/codex-token-usage/evidence-v1.sqlite3`。其中只包含计数证据和派生会话元数据，
不包含提示词、回答或 API Key。可以随时删除该文件，使用 `--rebuild-cache`，或在 UI 中按 `R`
从磁盘重建。缓存损坏或缓存位置不可写时，工具会回退到正确的完整扫描。

## 统计原理

Codex rollout 日志是追加写入的活动记录，不是账单导出。直接累加每个 `total_tokens` 会重复统计，
因为快照可能重复、恢复的线程可能继承已有累计值，导入历史也可能包含合成估算值。

扫描器会：

1. 使用每个 rollout 文件的第一条 `session_meta` 确定线程归属。
2. 只有在结构化累计计数前进时才计入 `last_token_usage`。
3. 排除 fork 子代理在首次结构化任务触发前复制的父线程历史记账事件，同时保留子代理真实请求及
   其继承上下文产生的输入 Token。
4. 跨文件去除完全相同的事件副本。
5. 使用 `external_agent_session_imports.json` 和 Codex 导入标记排除导入前历史。
6. 保留导入线程在 Codex 中继续使用后产生的真实调用。

`total_tokens` 等于 `input_tokens + output_tokens`。缓存输入是输入的子集，推理输出是输出的子集。

## 限制

- 本地会话日志是用量证据，不是供应商账单。
- 历史日志无法识别每次请求使用了哪个 API Key。
- 本地日志不包含价格和组织级结算信息，因此本工具不估算费用。

## 开发

```bash
python3 -m pip install -e '.[dev]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
python3 -m build
```

提交 Pull Request 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按
[SECURITY.md](SECURITY.md) 报告。项目变化记录在 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
