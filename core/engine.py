from __future__ import annotations

import random
from dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.message.components import BaseMessageComponent, Face, Image, Plain

from .config import PluginConfig
from .state import GroupState


@dataclass(slots=True)
class ActionPlan:
    repeat_count: int
    action: str
    output_segment: BaseMessageComponent | None = None


@dataclass(slots=True)
class Evaluation:
    """检测结果与可选动作相互独立。

    repeated 与概率、动作权重和动作去重无关：只要达到阈值即为复读。
    """

    repeated: bool
    action_plan: ActionPlan | None = None


class RereadEngine:
    ACTIONS = ("follow", "interrupt", "ban")

    def __init__(self, cfg: PluginConfig):
        self.cfg = cfg
        pool = []
        for action in self.ACTIONS:
            weight = cfg.weight_of(action)
            if weight > 0:
                pool.append((action, weight))

        self._actions, self._weights = zip(*pool) if pool else ((), ())
        if not self._actions:
            logger.warning(
                "[reread] all action weights are 0, reread actions are disabled"
            )

    @staticmethod
    def make_fingerprint(seg: BaseMessageComponent) -> str:
        if isinstance(seg, Plain):
            return f"text:{seg.text}"

        if isinstance(seg, Image):
            key = seg.file or seg.url or seg.path
            return f"image:{key}"

        if isinstance(seg, Face):
            return f"face:{seg.id}"

        return f"unknown:{seg.type}"

    def evaluate(
        self,
        state: GroupState,
        seg_type: str,
        send_id: str,
        seg: BaseMessageComponent,
    ) -> Evaluation:
        state.clear_if_same_sender(seg_type, send_id, self.cfg.need_different)

        fingerprint = self.make_fingerprint(seg)

        # 内容变化（含类型切换）结束旧链，本条消息开启新链
        if (
            state.current_fingerprint is not None
            and fingerprint != state.current_fingerprint
        ):
            state.reset_episode()

        state.push_message(seg_type, send_id, fingerprint)
        state.current_fingerprint = fingerprint

        reread_threshold = self.cfg.get_threshold(seg_type)

        repeated = state.is_episode_active_for(fingerprint)
        if not repeated:
            tail_fp = state.get_uniform_tail_fingerprint(seg_type, reread_threshold)
            if tail_fp == fingerprint:
                state.activate_episode(fingerprint)
                repeated = True

        if not repeated:
            return Evaluation(repeated=False, action_plan=None)

        # 复读动作：概率未命中、权重为 0、本链已执行过均不阻止抑制状态
        if state.has_action_for(fingerprint):
            return Evaluation(repeated=True, action_plan=None)

        if not self.cfg.should_reread():
            return Evaluation(repeated=True, action_plan=None)

        if not self._actions:
            return Evaluation(repeated=True, action_plan=None)

        state.mark_action(fingerprint)
        action = random.choices(self._actions, self._weights, k=1)[0]
        if action == "ban":
            return Evaluation(
                repeated=True,
                action_plan=ActionPlan(repeat_count=reread_threshold, action=action),
            )

        output_segment = (
            Plain(self.cfg.interrupt.text) if action == "interrupt" else seg
        )
        return Evaluation(
            repeated=True,
            action_plan=ActionPlan(
                repeat_count=reread_threshold,
                action=action,
                output_segment=output_segment,
            ),
        )
