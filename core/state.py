import asyncio
from collections import deque
from typing import TypedDict


class MsgRecord(TypedDict):
    """
    单条复读窗口记录（仅用于判定）
    """

    send_id: str
    fp: str


class GroupState:
    """
    单群状态容器
    - 按消息类型分组的消息窗口（deque + maxlen）
    - 当前连续复读链：当前链指纹、已激活指纹、本链已执行动作的指纹
    """

    def __init__(self, window_sizes: dict[str, int]):
        # 群级并发保护
        self.lock = asyncio.Lock()

        # {seg_type: deque[MsgRecord]}
        self.messages: dict[str, deque[MsgRecord]] = {
            seg_type: deque(maxlen=limit) for seg_type, limit in window_sizes.items()
        }

        # 当前连续复读链的指纹（最近一条进入判定的消息）
        self.current_fingerprint: str | None = None
        # 本链中已达到阈值、进入发送抑制的指纹
        self.active_fingerprint: str | None = None
        # 本链中已执行过复读动作的指纹（每链每个指纹至多一次）
        self._actioned_fingerprints: set[str] = set()

    # ───────── 窗口维护 ─────────

    def clear_if_same_sender(
        self,
        seg_type: str,
        send_id: str,
        need_different: bool,
    ) -> None:
        """
        若要求必须不同人复读：
        - 当前消息发送者与窗口中最后一条相同 → 清空窗口
        """
        if not need_different:
            return

        lst = self.messages[seg_type]
        if lst and lst[-1]["send_id"] == send_id:
            lst.clear()

    def push_message(
        self,
        seg_type: str,
        send_id: str,
        fp: str,
    ) -> None:
        """
        将单段消息指纹压入对应类型的窗口
        """
        self.messages[seg_type].append(
            {
                "send_id": send_id,
                "fp": fp,
            }
        )

    def get_messages(self, seg_type: str) -> deque[MsgRecord]:
        """
        获取指定消息类型的窗口
        """
        return self.messages[seg_type]

    def get_uniform_tail_fingerprint(self, seg_type: str, count: int) -> str | None:
        if count <= 0:
            return None

        messages = self.messages[seg_type]
        if len(messages) < count:
            return None

        tail = list(messages)[-count:]
        first_fp = tail[0]["fp"]
        if any(msg["fp"] != first_fp for msg in tail):
            return None
        return first_fp

    def clear_all(self) -> None:
        """
        清空当前群内所有消息窗口
        """
        for lst in self.messages.values():
            lst.clear()

    def reset_episode(self) -> None:
        """结束当前连续复读链。

        清空全部类型窗口、当前/激活指纹和本链动作去重记录。
        """
        self.clear_all()
        self.current_fingerprint = None
        self.active_fingerprint = None
        self._actioned_fingerprints.clear()

    # ───────── 复读链状态 ─────────

    def is_episode_active_for(self, fingerprint: str) -> bool:
        """当前链是否已因该指纹进入抑制状态。"""
        return self.active_fingerprint == fingerprint

    def activate_episode(self, fingerprint: str) -> None:
        self.active_fingerprint = fingerprint

    def has_action_for(self, fingerprint: str) -> bool:
        """本链是否已对该指纹执行过复读动作。"""
        return fingerprint in self._actioned_fingerprints

    def mark_action(self, fingerprint: str) -> None:
        self._actioned_fingerprints.add(fingerprint)


class StateManager:
    """
    全局状态管理器（按 平台/机器人/群 三元组）
    """

    def __init__(self, window_sizes: dict[str, int]):
        self.window_sizes = window_sizes
        self._group_states: dict[tuple[str, str, str], GroupState] = {}

    def get_state(self, scope: tuple[str, str, str]) -> GroupState:
        """
        获取或初始化指定范围（platform_id, self_id, group_id）的状态对象
        """
        if scope not in self._group_states:
            self._group_states[scope] = GroupState(self.window_sizes)
        return self._group_states[scope]

    def reset_scope(self, scope: tuple[str, str, str]) -> None:
        """结束指定范围的连续复读链（若存在）。"""
        state = self._group_states.get(scope)
        if state is not None:
            state.reset_episode()
