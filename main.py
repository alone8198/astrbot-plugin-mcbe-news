"""
Minecraft 官方博客文章监测插件 - AstrBot
==============================================
监测 Minecraft 官方博客文章发布，AI 总结并推送原文链接。

功能:
    - 定期检测 Minecraft 官方博客新文章
    - 使用 AI 对文章进行总结
    - 推送文章标题、AI 总结和原文链接
    - 自动订阅功能（使用命令自动订阅当前聊天）
    - 避免重复推送（记录已推送文章 ID）
"""

import json
import asyncio
import requests
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

# 订阅配置文件
SUBSCRIPTIONS_FILE = "subscriptions.json"


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

        # 订阅配置文件
        self.subs_file = self.data_dir / SUBSCRIPTIONS_FILE

        # 加载已推送文章 ID
        self.pushed_ids: Set[str] = self._load_pushed_ids()
        self.last_latest_id: str = self._load_last_latest_id()

        # 加载订阅列表
        self.subscriptions: List[Dict] = self._load_subscriptions()

        # 后台任务句柄
        self._task = None
        self._running = False

        # 启动后台定时检查任务
        self._start_background_task()

        logger.info(f"[MCBE新闻] 插件已加载，已记录 {len(self.pushed_ids)} 篇已推送文章")
        logger.info(f"[MCBE新闻] 当前订阅数：{len(self.subscriptions)}")

    def _start_background_task(self):
        """启动后台定时检查任务。"""
        if self._task is not None:
            return

        self._running = True
        self._task = asyncio.create_task(self._background_loop())
        logger.info("[MCBE新闻] 后台定时检查任务已启动")

    async def _background_loop(self):
        """后台循环，定期检查新文章。"""
        while self._running:
            try:
                # 读取配置的检测间隔（小时）
                check_interval = float(self.config.get("check_interval", 2.0))
                check_interval_seconds = check_interval * 3600

                logger.info(f"[MCBE新闻] 下次检查在 {check_interval} 小时后")

                # 等待指定时间
                await asyncio.sleep(check_interval_seconds)

                # 执行检查
                if self._running:
                    await self._do_check_and_push()

            except asyncio.CancelledError:
                logger.info("[MCBE新闻] 后台任务被取消")
                break
            except Exception as e:
                logger.error(f"[MCBE新闻] 后台任务出错: {e}")
                await asyncio.sleep(60)  # 出错后等待 1 分钟再试

    async def _do_check_and_push(self):
        """执行检查并推送新文章。"""
        logger.info("[MCBE新闻] 开始定时检查新文章...")

        # 检查是否有订阅
        if not self.subscriptions:
            logger.warning("[MCBE新闻] 没有订阅的聊天，跳过推送")
            return

        new_articles = await self.check_new_articles()

        if not new_articles:
            logger.info("[MCBE新闻] 没有新文章")

            # 检查是否需要推送最新文章
            if self.config.get("always_push_latest", True):
                latest_article = await self.get_latest_article()
                if latest_article:
                    # 检查这篇最新文章是否已经推送过
                    if latest_article["id"] != self.last_latest_id:
                        logger.info(f"[MCBE新闻] 推送最新文章: {latest_article['title']}")
                        await self._push_article_to_all(latest_article, is_latest=True)
                        self.last_latest_id = latest_article["id"]
                        self._save_pushed_ids()
                    else:
                        logger.info("[MCBE新闻] 最新文章已推送过，跳过")
                else:
                    logger.warning("[MCBE新闻] 获取最新文章失败")

            if self.config.get("notify_on_no_new", False):
                logger.info("[MCBE新闻] 无新文章通知已启用，但功能待实现")
            return

        # 推送到所有订阅
        for article in new_articles:
            await self._push_article_to_all(article, is_latest=False)

            # 记录已推送
            self.pushed_ids.add(article["id"])
            self._save_pushed_ids()

            # 避免频率限制
            await asyncio.sleep(1)

        logger.info(f"[MCBE新闻] 已完成 {len(new_articles)} 篇新文章的推送")

    async def _push_article_to_all(self, article: Dict, is_latest: bool = False):
        """
        推送文章到所有订阅的聊天。

        Args:
            article: 文章信息字典
            is_latest: 是否为最新文章（非新发布）
        """
        # AI 总结
        summary = await self.summarize_article(article)

        # 格式化消息
        message = await self.format_article_message(article, summary, is_latest)

        # 推送到所有订阅
        for sub in self.subscriptions:
            try:
                platform = sub.get("platform", "")
                conv_type = sub.get("type", "")
                conv_id = sub.get("id", "")

                if not platform or not conv_id:
                    continue

                logger.info(f"[MCBE新闻] 推送到 {platform}:{conv_type}:{conv_id}")

                # 发送消息
                await self._send_message(platform, conv_type, conv_id, message)

            except Exception as e:
                logger.error(f"[MCBE新闻] 推送到 {sub} 失败: {e}")

    async def _send_message(self, platform: str, conv_type: str, conv_id: str, message: str):
        """
        发送消息到指定聊天。

        Args:
            platform: 平台 ID（如 aiocqhttp）
            conv_type: 聊天类型（group 或 private）
            conv_id: 聊天 ID
            message: 消息内容
        """
        try:
            # 获取平台实例
            platform_instance = self.context.get_platform(platform)
            if not platform_instance:
                logger.error(f"[MCBE新闻] 找不到平台: {platform}")
                return

            # 根据平台发送消息
            if platform == "aiocqhttp":
                await self._send_aiocqhttp_message(platform_instance, conv_type, conv_id, message)
            else:
                # 通用方法（其他平台）
                logger.warning(f"[MCBE新闻] 未实现平台 {platform} 的消息发送")

        except Exception as e:
            logger.error(f"[MCBE新闻] 发送消息失败: {e}")

    async def _send_aiocqhttp_message(self, platform, conv_type: str, conv_id: str, message: str):
        """
        发送消息到 aiocqhttp（QQ）平台。

        Args:
            platform: aiocqhttp 平台实例
            conv_type: 聊天类型（group 或 private）
            conv_id: 聊天 ID
            message: 消息内容
        """
        try:
            if conv_type == "group":
                # 发送群消息
                if hasattr(platform, "send_group_msg"):
                    await platform.send_group_msg(group_id=int(conv_id), message=message)
                else:
                    logger.warning("[MCBE新闻] aiocqhttp 平台不支持 send_group_msg")
            elif conv_type == "private":
                # 发送私聊消息
                if hasattr(platform, "send_private_msg"):
                    await platform.send_private_msg(user_id=int(conv_id), message=message)
                else:
                    logger.warning("[MCBE新闻] aiocqhttp 平台不支持 send_private_msg")
            else:
                logger.error(f"[MCBE新闻] 未知的聊天类型: {conv_type}")
        except Exception as e:
            logger.error(f"[MCBE新闻] 发送 aiocqhttp 消息失败: {e}")

    def _load_subscriptions(self) -> List[Dict]:
        """
        加载订阅列表。

        Returns:
            订阅列表，每项是 {"platform": ..., "type": ..., "id": ...}
        """
        if not self.subs_file.exists():
            return []

        try:
            with open(self.subs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("subscriptions", [])
        except Exception as e:
            logger.error(f"[MCBE新闻] 加载订阅列表失败: {e}")
            return []

    def _save_subscriptions(self):
        """保存订阅列表。"""
        try:
            with open(self.subs_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "subscriptions": self.subscriptions,
                        "last_update": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"[MCBE新闻] 保存订阅列表失败: {e}")

    def _add_subscription(self, platform: str, conv_type: str, conv_id: str) -> bool:
        """
        添加订阅。

        Args:
            platform: 平台 ID
            conv_type: 聊天类型（group 或 private）
            conv_id: 聊天 ID

        Returns:
            是否添加成功（如果已存在则返回 False）
        """
        # 检查是否已订阅
        for sub in self.subscriptions:
            if sub.get("platform") == platform and sub.get("id") == conv_id:
                return False

        # 添加订阅
        self.subscriptions.append({
            "platform": platform,
            "type": conv_type,
            "id": conv_id,
        })
        self._save_subscriptions()
        return True

    def _remove_subscription(self, platform: str, conv_id: str) -> bool:
        """
        移除订阅。

        Args:
            platform: 平台 ID
            conv_id: 聊天 ID

        Returns:
            是否移除成功（如果不存在则返回 False）
        """
        for i, sub in enumerate(self.subscriptions):
            if sub.get("platform") == platform and sub.get("id") == conv_id:
                del self.subscriptions[i]
                self._save_subscriptions()
                return True

        return False

    async def check_new_articles(self) -> List[Dict]:
        """
        检查新文章。

        Returns:
            新文章列表，每项是 {"title": ..., "link": ..., "published": ..., "summary": ...}
        """
        try:
            logger.info("[MCBE新闻] 开始检查新文章...")

            # 使用 requests 获取 RSS Feed（绕过 Cloudflare 保护）
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(MINECRAFT_BLOG_RSS, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 使用 feedparser 解析 RSS 内容
            feed = feedparser.parse(response.text)

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

    async def get_latest_article(self) -> Dict:
        """
        获取最新的一篇文章（不管是否已推送）。

        Returns:
            最新文章字典，如果没有则返回 None
        """
        try:
            # 使用 requests 获取 RSS Feed（绕过 Cloudflare 保护）
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(MINECRAFT_BLOG_RSS, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 使用 feedparser 解析 RSS 内容
            feed = feedparser.parse(response.text)

            if not feed.entries:
                return None

            entry = feed.entries[0]  # 第一篇文章是最新的
            article_id = entry.get("id", entry.get("link", ""))

            return {
                "title": entry.get("title", "无标题"),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
                "id": article_id,
            }

        except Exception as e:
            logger.error(f"[MCBE新闻] 获取最新文章失败: {e}")
            return None

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

    async def format_article_message(self, article: Dict, summary: str, is_latest: bool = False) -> str:
        """格式化文章消息。"""
        prefix = "【Minecraft 最新文章】" if is_latest else "【Minecraft 官方新文章】"
        return (
            f"{prefix}\n"
            f"📝 标题：{article['title']}\n"
            f"🕐 发布时间：{article['published']}\n\n"
            f"🤖 AI 总结：\n{summary}\n\n"
            f"🔗 原文链接：{article['link']}"
        )

    @filter.command("mcbe_news_check")
    async def cmd_check_now(self, event: AstrMessageEvent):
        """手动检查新文章：/mcbe_news_check"""
        # 自动订阅（如果启用）
        if self.config.get("auto_subscribe", True):
            platform = event.platform
            group_id = event.group_id
            user_id = event.user_id

            if group_id:
                # 群聊
                self._add_subscription(platform, "group", str(group_id))
                logger.info(f"[MCBE新闻] 自动订阅群聊: {platform}:group:{group_id}")
            else:
                # 私聊
                self._add_subscription(platform, "private", str(user_id))
                logger.info(f"[MCBE新闻] 自动订阅私聊: {platform}:private:{user_id}")

        yield event.plain_result("开始检查 Minecraft 官方博客新文章...")

        new_articles = await self.check_new_articles()

        if not new_articles:
            # 没有新文章，检查是否需要推送最新文章
            if self.config.get("always_push_latest", True):
                latest_article = await self.get_latest_article()
                if latest_article:
                    summary = await self.summarize_article(latest_article)
                    message = await self.format_article_message(latest_article, summary, is_latest=True)
                    yield event.plain_result(message)
                    return
            yield event.plain_result("没有发现新文章。")
            return

        yield event.plain_result(f"发现 {len(new_articles)} 篇新文章：")

        for article in new_articles:
            summary = await self.summarize_article(article)
            message = await self.format_article_message(article, summary, is_latest=False)

            yield event.plain_result(message)

            # 记录已推送
            self.pushed_ids.add(article["id"])
            self._save_pushed_ids()

    @filter.command("mcbe_news_subscribe")
    async def cmd_subscribe(self, event: AstrMessageEvent):
        """订阅 MCBe 新闻：/mcbe_news_subscribe"""
        platform = event.platform
        group_id = event.group_id
        user_id = event.user_id

        if group_id:
            # 群聊
            success = self._add_subscription(platform, "group", str(group_id))
            if success:
                yield event.plain_result(f"✅ 已订阅 MCBe 新闻到本群")
            else:
                yield event.plain_result("ℹ️ 本群已订阅 MCBe 新闻")
        else:
            # 私聊
            success = self._add_subscription(platform, "private", str(user_id))
            if success:
                yield event.plain_result("✅ 已订阅 MCBe 新闻到本聊天")
            else:
                yield event.plain_result("ℹ️ 本聊天已订阅 MCBe 新闻")

    @filter.command("mcbe_news_unsubscribe")
    async def cmd_unsubscribe(self, event: AstrMessageEvent):
        """取消订阅 MCBe 新闻：/mcbe_news_unsubscribe"""
        platform = event.platform
        group_id = event.group_id
        user_id = event.user_id

        if group_id:
            # 群聊
            success = self._remove_subscription(platform, str(group_id))
            if success:
                yield event.plain_result("✅ 已取消订阅 MCBe 新闻")
            else:
                yield event.plain_result("ℹ️ 本群未订阅 MCBe 新闻")
        else:
            # 私聊
            success = self._remove_subscription(platform, str(user_id))
            if success:
                yield event.plain_result("✅ 已取消订阅 MCBe 新闻")
            else:
                yield event.plain_result("ℹ️ 本聊天未订阅 MCBe 新闻")

    @filter.command("mcbe_news_status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看插件状态：/mcbe_news_status"""
        status = (
            f"【MCBE 新闻监测插件状态】\n"
            f"📊 已记录文章数：{len(self.pushed_ids)}\n"
            f"⏰ 检测间隔：{self.config.get('check_interval', 2)} 小时\n"
            f"🤖 AI 总结：{'✅ 开启' if self.config.get('ai_summary', True) else '❌ 关闭'}\n"
            f"📬 订阅数：{len(self.subscriptions)}\n"
            f"🔔 自动订阅：{'✅ 开启' if self.config.get('auto_subscribe', True) else '❌ 关闭'}"
        )
        yield event.plain_result(status)

    @filter.command("mcbe_news_list")
    async def cmd_list_subscriptions(self, event: AstrMessageEvent):
        """查看订阅列表：/mcbe_news_list"""
        if not self.subscriptions:
            yield event.plain_result("当前没有订阅")
            return

        msg = "【订阅列表】\n"
        for i, sub in enumerate(self.subscriptions, 1):
            msg += f"{i}. {sub['platform']}:{sub['type']}:{sub['id']}\n"

        yield event.plain_result(msg)

    @filter.command("mcbe_news_clear")
    async def cmd_clear(self, event: AstrMessageEvent):
        """清除已推送记录（重新推送）：/mcbe_news_clear"""
        self.pushed_ids.clear()
        self.last_latest_id = ""
        self._save_pushed_ids()
        yield event.plain_result("已清除所有已推送记录，下次检查会重新推送。")

    def _load_pushed_ids(self) -> Set[str]:
        """加载已推送文章的 ID。"""
        if not self.pushed_file.exists():
            return set()

        try:
            with open(self.pushed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.last_latest_id = data.get("last_latest_id", "")
                return set(data.get("pushed_ids", []))
        except Exception as e:
            logger.error(f"[MCBE新闻] 加载已推送记录失败: {e}")
            return set()

    def _load_last_latest_id(self) -> str:
        """加载上次推送的最新文章 ID。"""
        if not self.pushed_file.exists():
            return ""
        try:
            with open(self.pushed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_latest_id", "")
        except Exception as e:
            logger.error(f"[MCBE新闻] 加载 last_latest_id 失败: {e}")
            return ""

    def _save_pushed_ids(self):
        """保存已推送文章的 ID 和最后推送的最新文章 ID。"""
        try:
            with open(self.pushed_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "pushed_ids": list(self.pushed_ids),
                        "last_latest_id": self.last_latest_id,
                        "last_update": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"[MCBE新闻] 保存已推送记录失败: {e}")

    async def terminate(self):
        """插件卸载时调用，清理后台任务。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[MCBE新闻] 后台任务已停止")
