---
title: 配置文件
description: 部署实际读取的设置 JSON，以及 setup 能力可以写入的键。
quadrant: reference
---

DeepTutor 从运行目录里的 `data/user/settings/*.json` 读取配置。进程环境变量只覆盖启动时的少量值。Podman 的宿主机端口映射是 `.env.example` 里的变量。

## 应用读取的文件

| 文件 | 内容 |
| --- | --- |
| `interface.json` | 个人界面选择，包括语言和主题。 |
| `system.json` | 端口，以及服务端使用的 API 基址。`next_public_api_base` 是前端服务器访问后端的地址。开启认证后，`cors_origins` 列出允许调用 API 的页面来源。 |
| `document_parsing.json` | 文档解析引擎。 |
| `model_catalog.json` | 提供方配置和选中的模型。 |
| `auth.json` | 多用户认证。`enabled`、`token_expire_hours` 和 `cookie_secure` 是[多用户部署](/zh-cn/self-hosting/multi-user/)里写明的开关。 |

编辑这些值的界面是[设置](/zh-cn/self-hosting/settings/)。

## setup 能力可以写入的键

这些行来自 `deeptutor/services/config/settings_spec.py`，是该能力被允许修改的旋钮，不是每个 JSON 字段的清单。密钥不在这张表里；凭据在设置卡片中填写。

| 键 | 区域 | 范围 | 生效 |
| --- | --- | --- | --- |
| `interface.language` | interface | personal | 立即 |
| `interface.response_language` | interface | personal | 立即 |
| `interface.theme` | interface | personal | 立即 |
| `document_parsing.engine` | parsing | global | 立即；已解析的文档保持原文，直到重新上传 |
| `catalog.llm` | models | global | 立即，连通性探测通过之后 |
| `catalog.embedding` | models | global | 需要重建索引，连通性探测通过之后 |
| `catalog.search` | models | global | 立即 |
| `web_fetch.backend` | models | global | 立即 |

个人行写在调用者自己的 `interface.json`。全局行写在部署共享设置里，只有管理员可以改。
