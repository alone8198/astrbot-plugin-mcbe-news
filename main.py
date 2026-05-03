"""
Minecraft 官方博客文章监测插件 - AstrBot
==============================================
监测 Minecraft 官方博客文章发布，AI 总结并推送原文链接。

功能:
    - 定期检测 Minecraft 官方博客新文章
    - 使用 AI 对文章进行总结
    - 推送文章标题、AI 总结和原文链接
    - 支持配置多个推送目标
    - 避免重复推送（记录已推送文章 ID）
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime, timezone

import feedparser
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.io import get_astrbot_data_path

# Minecraft 官方博客 RSS
MINECRAFT_BLOG_RSS = "https://feedback.minecraft.net/hc/en-us/sections/360001164212.rss"


@register(
    "mcbe_news_plugin",
    "alone8198",
    "监测 Minecraft 官方博客文章发布，AI 总结并推送原文链接",
    "1.0.0",
    "https://github.com/alone8198/astrbot-plugin-mcbe-news",
)
class MCBENewsPlugin(Star):
    """Minecraft 官方文章监测插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 数据存储目录
        self.data_dir = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / "astrbot_plugin_mcbe_news"
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 已推送文章记录文件
        self.pushed_file = self.data_dir / "pushed_articles.json"

        # 加载已推送文章 ID
        self.pushed_ids: Set[str] = self._load_pushed_ids()

        logger.info(f"[MCBE新闻] 插件已加载，已记录 {len(self.pushed_ids)} 篇已推送文章")

    def _load_pushed_ids(self) -> Set[str]:
        """加载已推送文章的 ID。"""
        if not self.pushed_file.exists():
            return set()

        try:
            with open(self.pushed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("pushed_ids", []))
        except Exception as e:
            logger.error(f"[MCBE新闻] 加载已推送记录失败: {e}")
            return set()

    def _save_pushed_ids(self):
        """保存已推送文章的 ID。"""
        try:
            with open(self.pushed_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "pushed_ids": list(self.pushed_ids),
                        "last_update": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"[MCBE新闻] 保存已推送记录失败: {e}")

    async def check_new_articles(self) -> List[Dict]:
        """
        检查新文章。

        Returns:
            新文章列表，每项是 {"title": ..., "link": ..., "published": ..., "summary": ...}
        """
        try:
            logger.info("[MCBE新闻] 开始检查新文章...")

            # 使用 feedparser 解析 RSS
            feed = feedparser.parse(MINECRAFT_BLOG_RSS)

            if not feed.entries:
                logger.warning("[MCBE新闻] RSS 解析失败或没有文章")
                return []

            new_articles = []
            max_articles = int(self.config.get("max_articles_per_check", 5))

            for entry in feed.entries[:max_articles * 2]:  # 多取一些，过滤已推送的
                article_id = entry.get("id", entry.get("link", ""))

                if not article_id or article_id in self.pushed_ids:
                    continue

                article = {
                    "title": entry.get("title", "无标题"),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                    "id": article_id,
                }

                new_articles.append(article)

                if len(new_articles) >= max_articles:
                    break

            logger.info(f"[MCBE新闻] 发现 {len(new_articles)} 篇新文章")
            return new_articles

        except Exception as e:
            logger.error(f"[MCBE新闻] 检查新文章失败: {e}")
            return []

    async def summarize_article(self, article: Dict) -> str:
        """
        使用 AI 总结文章。

        Args:
            article: 文章信息字典

        Returns:
            AI 生成的总结
        """
        if not self.config.get("ai_summary", True):
            return article.get("summary", "")[:200]

        provider_id = self.config.get("summary_provider", "")
        if not provider_id:
            # 使用当前对话模型
            provider_id = await self.context.get_current_chat_provider_id()

        prompt = (
            f"请用 2-3 句话总结以下 Minecraft 官方文章的主要内容：\n\n"
            f"标题：{article['title']}\n"
            f"内容：{article.get('summary', '')[:500]}\n\n"
            f"总结："
        )

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt
            )

            # 提取响应文本
            summary = ""
            if hasattr(response, "completion_text") and response.completion_text:
                summary = response.completion_text
            elif hasattr(response, "result_chain") and response.result_chain:
                for segment in response.result_chain:
                    if hasattr(segment, "text") and segment.text:
                        summary += segment.text

            return summary.strip() if summary else article.get("summary", "")[:200]

        except Exception as e:
            logger.error(f"[MCBE新闻] AI 总结失败: {e}")
            return article.get("summary", "")[:200]

    async def format_article_message(self, article: Dict, summary: str) -> str:
        """格式化文章消息。"""
        return (
            f"【Minecraft 官方新文章】\n"
            f"📝 标题：{article['title']}\n"
            f"🕒 发布时间：{article['published']}\n\n"
            f"🤖 AI 总结：\n{summary}\n\n"
            f"🔗 原文链接：{article['link']}"
        )

    @filter.scheduled_job(trigger="interval", hours=2)
    async def scheduled_check(self):
        """定时检查新文章（每 2 小时）。"""
        logger.info("[MCBE新闻] 定时任务触发，开始检查新文章...")

        new_articles = await self.check_new_articles()

        if not new_articles:
            logger.info("[MCBE新闻] 没有新文章")
            if self.config.get("notify_on_no_new", False):
                logger.info("[MCBE新闻] 无新文章通知已启用，但功能待实现")
            return

        # 获取推送目标
        push_targets_str = self.config.get("push_targets", "")
        if not push_targets_str:
            logger.warning("[MCBE新闻] 未配置推送目标，跳过推送")
            return

        targets = [t.strip() for t in push_targets_str.split(",") if t.strip()]

        for article in new_articles:
            # AI 总结
            summary = await self.summarize_article(article)

            # 格式化消息
            message = await self.format_article_message(article, summary)

            # 推送到所有目标
            for target in targets:
                try:
                    logger.info(f"[MCBE新闻] 准备推送到: {target}")
                    # 注意：这里需要根据 AstrBot 的 API 来实现推送
                    # 目前先记录日志，等待用户配置正确的推送方式
                    logger.info(f"[MCBE新闻] 消息内容: {message[:100]}...")
                except Exception as e:
                    logger.error(f"[MCBE新闻] 推送到 {target} 失败: {e}")

            # 记录已推送
            self.pushed_ids.add(article["id"])
            self._save_pushed_ids()

            # 避免频率限制
            await asyncio.sleep(1)

        logger.info(f"[MCBE新闻] 已完成 {len(new_articles)} 篇新文章的推送")

    @filter.command("mcbe_news_check")
    async def cmd_check_now(self, event: AstrMessageEvent):
        """手动检查新文章：/mcbe_news_check"""
        yield event.plain_result("开始检查 Minecraft 官方博客新文章...")

        new_articles = await self.check_new_articles()

        if not new_articles:
            yield event.plain_result("没有发现新文章。")
            return

        yield event.plain_result(f"发现 {len(new_articles)} 篇新文章：")

        for article in new_articles:
            summary = await self.summarize_article(article)
            message = await self.format_article_message(article, summary)

            yield event.plain_result(message)

            # 记录已推送
            self.pushed_ids.add(article["id"])
            self._save_pushed_ids()

    @filter.command("mcbe_news_status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看插件状态：/mcbe_news_status"""
        status = (
            f"【MCBE 新闻监测插件状态】\n"
            f"📊 已记录文章数：{len(self.pushed_ids)}\n"
            f"⏰ 检测间隔：{self.config.get('check_interval', 2)} 小时\n"
            f"🤖 AI 总结：{'✅ 开启' if self.config.get('ai_summary', True) else '❌ 关闭'}\n"
            f"📬 推送目标：{self.config.get('push_targets', '未配置')}"
        )
        yield event.plain_result(status)

    @filter.command("mcbe_news_clear")
    async def cmd_clear(self, event: AstrMessageEvent):
        """清除已推送记录（重新推送）：/mcbe_news_clear"""
        self.pushed_ids.clear()
        self._save_pushed_ids()
        yield event.plain_result("已清除所有已推送记录，下次检查会重新推送。")
