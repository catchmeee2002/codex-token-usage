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
- 最近 24 小时、最近 7 天、最近 30 天、全部历史和自定义日期
- 标准每日坐标图：横轴日期、纵轴 Token，并标记不足整天的统计区间
- 中文或英文文本输出
- 带 `schema_version: 1` 的稳定 JSON 输出
- 主线程和子代理用量拆分
- 基于结构化证据排除导入的 Claude Code 历史
- 处理重复快照，并显式报告数据完整性警告
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
| `Enter` | 应用选中的范围 |
| `r` | 刷新当前报告 |
| `l` | 在中文和英文之间切换 |
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
| `--timezone IANA` | 设置日期和每日统计使用的时区 |
| `--json` | 输出稳定的机器可读数据 |
| `--no-daily` | 隐藏文本输出中的每日趋势 |
| `--strict` | 出现完整性或认证警告时返回非零状态 |
| `--codex-home PATH` | 覆盖 `CODEX_HOME` 和 `~/.codex` 自动发现路径 |

## 统计原理

Codex rollout 日志是追加写入的活动记录，不是账单导出。直接累加每个 `total_tokens` 会重复统计，
因为快照可能重复、恢复的线程可能继承已有累计值，导入历史也可能包含合成估算值。

扫描器会：

1. 使用每个 rollout 文件的第一条 `session_meta` 确定线程归属。
2. 只有在结构化累计计数前进时才计入 `last_token_usage`。
3. 跨文件去除完全相同的事件副本。
4. 使用 `external_agent_session_imports.json` 和 Codex 导入标记排除导入前历史。
5. 保留导入线程在 Codex 中继续使用后产生的真实调用。

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
