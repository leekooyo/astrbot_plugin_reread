<div align="center">

# astrbot_plugin_reread

_✨ 复读插件 ✨_  

[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.html)

</div>

> 本仓库由 [leekooyo](https://github.com/leekooyo) 维护，基于 [Zhalslar 的原项目](https://github.com/Zhalslar/astrbot_plugin_reread)；安装和更新请使用本仓库地址。原始基线见 [UPSTREAM.md](UPSTREAM.md)。

**当前版本：v2.1.3。** 版本号以 [metadata.yaml](metadata.yaml) 为准。

## 🤝 介绍

不依赖任何数据库的群聊复读插件。

- 支持 **文本 / 图片 / 表情** 分别设置复读阈值  
- 支持 **总响应概率** 与 **动作权重**  
- 支持 **跟随 / 打断 / 禁言** 按权重随机触发  
- 可要求 **消息必须来自不同用户**  
- 仅处理 **单段消息**，逻辑清晰、行为可预期  
- 同一条连续复读链只执行一次复读动作；达到阈值后持续抑制同内容消息派生的其他自动发送

## 📦 安装

在 AstrBot 中选择「通过仓库地址安装」，填写 `https://github.com/leekooyo/astrbot_plugin_reread`。本仓库基于 [Zhalslar 原项目](https://github.com/Zhalslar/astrbot_plugin_reread) 独立维护，维护差异见 [UPSTREAM.md](UPSTREAM.md)。

> 此维护版依赖本机 AstrBot 核心提供 `astrbot.core.utils.message_send_policy` 并接入 OneBot 公共发送入口。安装到未接入该模块的 AstrBot 核心会导致插件导入失败；插件仓库本身不包含核心改动。

默认对所有群生效（群白名单为空）、达到阈值后以 `0.8` 的概率响应，且禁言动作权重为 `5`。不希望复读触发禁言时将 `ban.weight` 设为 `0`；建议先在测试群确认阈值与响应频率。复读状态只保存在内存中，不需要上传聊天记录或运行数据。

## ⌨️ 配置

请前往插件配置面板进行配置。

主要配置项包括：

- `thresholds`：各消息类型的复读阈值  
- `reread_prob`：达到阈值后的总响应概率  
- `follow.weight`：跟随复读权重  
- `interrupt.weight` / `interrupt.text`：打断动作权重与打断文本  
- `ban.weight` / `ban.duration` / `ban.prompt`：禁言动作权重、时长与提示词  
- `need_different`：是否要求来自不同用户  
- `group_whitelist`：群白名单  

## ⚙️ 工作机制说明

- 每个平台、机器人账号和群的组合维护独立的复读状态（内存态，不落库）
- 按 **消息类型** 分别统计复读窗口
- 当窗口内消息：
  - 数量达到阈值
  - 内容指纹完全一致  
  才进入复读状态；是否执行动作由概率和动作权重决定
- 达到阈值后先按 `reread_prob` 判定是否响应，再按动作权重随机触发跟随、打断或禁言
- 图片判等优先使用 `file`，为空时自动退化为 `url / path`

## 🔇 复读发送隔离（OneBot）

达到复读阈值后，插件会标记本条入站消息的**发送来源**，核心发送路径据此取消**该消息派生的其他自动发送**：

- 表情收集、入库、统计、模型请求等**非发送处理不受影响**，照常执行
- 后续**同内容**消息持续抑制；**换内容、切换类型、明确命令**立即结束复读链并恢复发送
- 影响范围仅限「来源消息 + 平台适配器实例 + 机器人账号 + 当前群」；其他群、私聊、同群其他入站事件、独立定时推送均不受影响
- 复读插件自身的跟随、打断与禁言提示通过**一次性精确授权**直接发送，不借用给其他消息或子任务
- 被取消的发送不会记为成功、不消耗成功冷却、不写入实际发送历史；AI 发送工具会收到「已跳过，无需重试」而不是平台故障

已知覆盖的发送路径：普通/图片/语音/文件/合并转发消息、流式输出、`context.send_message` 主动发送、关系插件的名片裸 API、群管插件的群公告发布。独立的管理 API（戳一戳、撤回、禁言等）与明确命令不受影响。

**维护说明**：本功能依赖核心的 `astrbot.core.utils.message_send_policy` 模块与 OneBot 公共发送入口，升级 AstrBot 核心或关系/群管插件后需重新确认这些接入点是否仍在；新增自行建立发送客户端的插件不在自动覆盖范围内。

## 反馈与维护

此维护版的问题和改进请在本仓库提交 Issue 或 Pull Request。上游版本会在核对差异后手动合并。

## 📌 注意事项

- 复读阈值不建议设置过低，容易刷屏
- 插件只处理单段消息，多段消息会被忽略
