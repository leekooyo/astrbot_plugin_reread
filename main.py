from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.utils.message_send_policy import (
    mark_repeat_suppressed,
    send_reread_message,
)

from .core.ban import RereadBanHandler
from .core.config import PluginConfig
from .core.engine import RereadEngine
from .core.state import StateManager

# 复读检测在既有闸门之后运行：local_help(1000000) > gatekeeper(999999) >
# wakepro(99999) > 复读(99997) > 其他插件。
REREAD_PRIORITY = 99997


class RereadPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config)
        self.state_mgr = StateManager(self.cfg.window_sizes)
        self.engine = RereadEngine(self.cfg)
        self.ban_handler = RereadBanHandler(self.cfg)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=REREAD_PRIORITY)
    async def reread_handle(self, event: AstrMessageEvent):
        # 机器人自身回显、群通知/请求事件不计入也不打断复读链
        if self._is_self_or_notice(event):
            return

        # 明确命令：放行，并结束此前的复读链
        if self._is_explicit_command(event):
            self._end_episode(event)
            return

        # 自动唤醒（非命令）不参与检测，但结束旧链
        if event.is_at_or_wake_command:
            self._end_episode(event)
            return

        chain = event.get_messages()
        if len(chain) != 1:
            # 混合消息结束旧链，自身不进入复读判定
            self._end_episode(event)
            return

        seg = chain[0]
        seg_type = str(seg.type).split(".")[-1]

        if not self.cfg.is_supported_type(seg_type):
            self._end_episode(event)
            return

        if isinstance(seg, Plain) and any(
            word in seg.text for word in self.cfg.blocked_words
        ):
            self._end_episode(event)
            return

        group_id = event.get_group_id()
        send_id = event.get_sender_id()

        if self.cfg.group_whitelist and not self.cfg.is_white_group(group_id):
            return

        scope = (
            str(event.get_platform_id()),
            str(event.get_self_id()),
            str(group_id),
        )
        state = self.state_mgr.get_state(scope)

        async with state.lock:
            evaluation = self.engine.evaluate(state, seg_type, send_id, seg)

        if not evaluation.repeated:
            return

        # 命中复读：先标记发送抑制，再执行可选动作。
        # 概率未命中/动作去重时 repeated 仍为真，抑制保持。
        mark_repeat_suppressed(event)

        plan = evaluation.action_plan
        if plan is None:
            return

        if plan.action == "ban":
            await self.ban_handler.handle(event, plan.repeat_count)
            return

        if not plan.output_segment:
            return

        if event.get_platform_name() == "aiocqhttp":
            # OneBot 新模式：直接发送自身输出，绕过实例包装，
            # 不停止事件，其他插件的非发送处理照常进行。
            await send_reread_message(event, MessageChain([plan.output_segment]))
            return

        # 其他平台保持旧行为
        msg = event.chain_result([plan.output_segment])
        if self.cfg.skip_pipeline:
            await event.send(msg)
            event.stop_event()
        else:
            yield msg

    # ───────── 辅助 ─────────

    def _is_self_or_notice(self, event: AstrMessageEvent) -> bool:
        if not event.get_group_id():
            return True
        if event.get_sender_id() and event.get_sender_id() == event.get_self_id():
            return True
        raw = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw, dict) and raw.get("post_type") in ("notice", "request"):
            return True
        return False

    def _is_explicit_command(self, event: AstrMessageEvent) -> bool:
        """明确命令判定：activated_handlers 与 handlers_parsed_params 的键交集。

        无参命令的值可以是空 dict，不能据此判断值的真伪；自动唤醒不算命令。
        """
        activated = event.get_extra("activated_handlers", None) or []
        params = event.get_extra("handlers_parsed_params", None) or {}
        if not isinstance(params, dict) or not params:
            return False
        names = set()
        for handler in activated:
            full_name = getattr(handler, "handler_full_name", None)
            if full_name:
                names.add(full_name)
        return bool(names & set(params.keys()))

    def _end_episode(self, event: AstrMessageEvent) -> None:
        """结束当前群的连续复读链（若存在）。"""
        scope = (
            str(event.get_platform_id()),
            str(event.get_self_id()),
            str(event.get_group_id()),
        )
        self.state_mgr.reset_scope(scope)
