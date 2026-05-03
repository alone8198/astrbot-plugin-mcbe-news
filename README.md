# AstrBot 插件：MCBE 官方文章监测

> 监测 Minecraft 官方博客文章发布，AI 总结并推送原文链接。

## ✨ 功能特性

- 🔍 **自动监测** - 定期检测 Minecraft 官方博客新文章（默认每 2 小时）
- 🤖 **AI 总结** - 使用 AI 对文章进行智能总结，提取关键信息
- 🔗 **原文链接** - 推送文章标题、AI 总结和原文链接
- 🎯 **精准推送** - 支持配置多个推送目标（群聊、私聊）
- 🚫 **去重机制** - 记录已推送文章，避免重复推送
- ⚙️ **灵活配置** - 可配置检测间隔、AI 模型、推送目标等

## 📋 配置说明

在 AstrBot 管理面板配置以下选项：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `check_interval` | 浮点数 | `2.0` | 检测间隔（小时），支持小数（0.5 = 30 分钟） |
| `push_targets` | 文本 | 空 | 推送目标列表，逗号分隔，格式：`platform:user_id` 或 `platform:group_id` |
| `ai_summary` | 布尔 | `true` | 是否启用 AI 总结 |
| `summary_provider` | 字符串 | 空 | 总结使用的 AI 模型（留空则使用当前对话模型） |
| `max_articles_per_check` | 整数 | `5` | 每次检查最多推送文章数 |
| `notify_on_no_new` | 布尔 | `false` | 无新文章时是否也通知 |

### 推送目标格式示例

```
aiocqhttp:123456789,aiocqhttp:987654321
```

表示推送到 QQ 号 `123456789` 和 `987654321`。

## 🔧 使用指令

| 指令 | 说明 |
|------|------|
| `/mcbe_news_check` | 手动检查新文章 |
| `/mcbe_news_status` | 查看插件状态（已记录文章数、配置等） |
| `/mcbe_news_clear` | 清除已推送记录（用于重新推送） |

## 📦 安装方法

### 方法 1：从 GitHub 安装（推荐）

1. 打开 AstrBot 管理面板
2. 进入 **插件市场** → **从 URL 安装**
3. 输入以下仓库地址：
   ```
   https://github.com/alone8198/astrbot-plugin-mcbe-news
   ```
4. 点击安装，等待安装完成
5. 配置插件参数
6. 重启 AstrBot

### 方法 2：手动安装

1. 下载插件代码：
   ```bash
   git clone https://github.com/alone8198/astrbot-plugin-mcbe-news.git
   ```

2. 将 `astrbot_plugin_mcbe_news/` 目录复制到 AstrBot 的插件目录：
   ```
   <AstrBot>/data/plugins/
   ```

3. 重启 AstrBot

## 📝 数据文件

插件会在 AstrBot 数据目录创建以下文件：

```
<astrbot_data_path>/plugin_data/astrbot_plugin_mcbe_news/
└── pushed_articles.json  # 已推送文章记录
```

## 🔗 相关链接

- **AstrBot 官方文档**: https://astrbot.app
- **AstrBot GitHub**: https://github.com/AstrBotDevs/AstrBot
- **Minecraft 官方博客**: https://feedback.minecraft.net

## 🐛 问题反馈

遇到问题？请在以下地方反馈：

- **GitHub Issues**: https://github.com/alone8198/astrbot-plugin-mcbe-news/issues
- **AstrBot 社区**: https://github.com/AstrBotDevs/AstrBot/discussions

## 📄 开源协议

MIT License

---

**⭐ 如果这个插件对你有帮助，请在 GitHub 上给我一个 Star！**
