from __future__ import annotations

from astrbot.api import logger
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.utils.message_send_policy import send_reread_message

from .config import PluginConfig


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class RereadBanHandler:
    def __init__(self, cfg: PluginConfig):
        self.cfg = cfg

    async def handle(self, event: AstrMessageEvent, repeat_count: int) -> bool:
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "set_group_ban"):
            logger.warning("[reread] current adapter does not support group bans")
            return False

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        try:
            await bot.set_group_ban(
                group_id=int(group_id),
                user_id=int(sender_id),
                duration=self.cfg.ban.duration,
            )
        except Exception as exc:
            logger.warning(
                f"[reread] failed to ban user {sender_id} in group {group_id}: {exc}"
            )
            return False

        prompt = self._format_prompt(event, repeat_count)
        if prompt:
            if event.get_platform_name() == "aiocqhttp":
                # OneBot 新模式：提示语走精确授权的直接发送，不停止事件
                await send_reread_message(event, MessageChain([Plain(prompt)]))
            else:
                # 其他平台保持旧行为
                await event.send(event.plain_result(prompt))
        if event.get_platform_name() != "aiocqhttp":
            event.stop_event()
        return True

    def _format_prompt(self, event: AstrMessageEvent, repeat_count: int) -> str:
        prompt = self.cfg.ban.prompt.strip()
        if not prompt:
            return ""

        values = _SafeFormatDict(
            user_name=event.get_sender_name(),
            user_id=event.get_sender_id(),
            group_id=event.get_group_id(),
            ban_duration=str(self.cfg.ban.duration),
            repeat_count=str(repeat_count),
        )
        try:
            return prompt.format_map(values)
        except Exception as exc:
            logger.warning(f"[reread] failed to format ban prompt: {exc}")
            return prompt
