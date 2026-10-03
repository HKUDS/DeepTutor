# 飞书通道消息解析与回复路由 — 失败测试集说明

- 基线：`origin/main` @ `ef2d9e5c3`（release v1.6.12），覆盖缺口 #9（`deeptutor/partners/channels/feishu.py`，495 缺失 / 55.5%）
- 测试文件：`tests/services/partners/test_feishu_message_parsing.py`（20 例）
- 分支：`myfork/test/feishu-message-parsing-20261003`（仅新增测试与证据，**未改任何产品代码**）

## 运行方式

```bash
.venv/bin/python -m pytest tests/services/partners/test_feishu_message_parsing.py -v
# 汇总：4 failed / 16 passed（失败为设计内红测试，对应下述 3 个真实缺陷）
.venv/bin/python -m pytest tests/services/partners/ -q
# 全目录：577 passed + 上述 4 failed，无既有用例回归
```

环境：mock SDK（SimpleNamespace/MagicMock 替身 `channel._client`），不需要真实飞书凭据；媒体落盘经 `partners_root` 夹具隔离到 `tmp_path`。

## 设计内红测试（3 个真实缺陷，4 例）

| # | 缺陷 | 定位（origin/main） | 红测试 | 修复建议 |
|---|------|--------------------|--------|----------|
| 1 | interactive 卡片正文全丢：`elements` 是扁平列表，却被按"列表的列表"双层遍历，元素被当成 dict 的 key 迭代，只剩标题 | `feishu.py:130-134`（`_extract_interactive_content`） | `test_interactive_card_extracts_header_title_and_element_bodies`、`test_interactive_json_string_content_is_parsed` | 改为单层 `for element in content.get("elements", []): parts.extend(_extract_element_content(element))` |
| 2 | 视频（`msg_type="media"`）下载请求带 `type="media"`，飞书资源接口只接受 `image`/`file`（函数自身注释已写明），当前只有 `audio` 被转换 → 视频消息下载必失败 | `feishu.py:1072-1075`（`_download_file_sync`） | `test_video_media_download_uses_file_resource_type` | `if resource_type in ("audio", "media"): resource_type = "file"` |
| 3 | 群聊 @ 提及占位符 `@_user_1` 原样透传给 LLM，未还原为可读名称 | `feishu.py:2061-2064`（`_on_message` text 分支） | `test_group_text_replaces_mention_placeholders_with_display_names` | 用 `message.mentions` 的 `key → name` 映射替换解析出的文本中的占位符 |

## 绿测试清单（钉住现状，防回归）

- 文本：p2p 文本转发到发送者会话（chat_id=sender、metadata 契约、THUMBSUP 回执）
- 富文本（post）：direct/localized/wrapped/未知语言回退/空块；正文 + @提及 + 内嵌图片下载（`type="image"`、image_key 断言）
- 媒体：audio → `type="file"` + `.opus` 后缀；file 落盘转发；image 下载失败降级为 `[image: download failed]`
- 分享卡：share_chat/share_user/share_calendar_event/system/merge_forward/未知类型占位符
- 路由：群消息未 @ 时跳过（mention 策略）且不加回执；@ 机器人时路由到 `oc_` 群聊；策略 open 时群媒体路由到群 + 媒体路径透传；`_is_bot_mentioned` 判定（bot 提及 / 用户提及 / `@_all` / 无提及）；message_id 去重；bot 发送者忽略；content JSON 畸形静默丢弃不崩溃
- 出站：p2p 用 `receive_id_type=open_id` 且回复锁定来源 message_id；群聊用 `receive_id_type=chat_id`

## 备注

- `lark_oapi` 缺失时整文件 skip（模块级 `importorskip`）。
- 既有测试 `test_feishu_reply_delivery.py` 等覆盖 reply 端点/回执清理/流式回退，本文件不重复，只补解析与私聊/群聊路由缺口。
