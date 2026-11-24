// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// i18n — English is the source-of-truth locale. Chinese pages live under
// `src/content/docs/zh-cn/` mirroring the English structure. Pages not yet
// translated fall back to English automatically.
const zh = "zh-CN";

export default defineConfig({
  site: "https://docs.deeptutor.info",
  redirects: {
    "/developer/contributing/": "/contributing/",
    "/zh-cn/developer/contributing/": "/zh-cn/contributing/",
    "/tutorbot/": "/partners/",
    "/tutorbot/discord/": "/partners/discord/",
    "/tutorbot/slack/": "/partners/slack/",
    "/tutorbot/telegram/": "/partners/telegram/",
    "/tutorbot/whatsapp/": "/partners/whatsapp/",
    "/tutorbot/wecom/": "/partners/wecom/",
    "/tutorbot/feishu/": "/partners/feishu/",
    "/tutorbot/dingtalk/": "/partners/dingtalk/",
    "/tutorbot/qq/": "/partners/qq/",
    "/tutorbot/mattermost/": "/partners/mattermost/",
    "/tutorbot/matrix/": "/partners/matrix/",
    "/tutorbot/zulip/": "/partners/zulip/",
    "/tutorbot/mochat/": "/partners/mochat/",
    "/zh-cn/tutorbot/": "/zh-cn/partners/",
    "/zh-cn/tutorbot/discord/": "/zh-cn/partners/discord/",
    "/zh-cn/tutorbot/slack/": "/zh-cn/partners/slack/",
    "/zh-cn/tutorbot/telegram/": "/zh-cn/partners/telegram/",
    "/zh-cn/tutorbot/whatsapp/": "/zh-cn/partners/whatsapp/",
    "/zh-cn/tutorbot/wecom/": "/zh-cn/partners/wecom/",
    "/zh-cn/tutorbot/feishu/": "/zh-cn/partners/feishu/",
    "/zh-cn/tutorbot/dingtalk/": "/zh-cn/partners/dingtalk/",
    "/zh-cn/tutorbot/qq/": "/zh-cn/partners/qq/",
    "/zh-cn/tutorbot/mattermost/": "/zh-cn/partners/mattermost/",
    "/zh-cn/tutorbot/matrix/": "/zh-cn/partners/matrix/",
    "/zh-cn/tutorbot/zulip/": "/zh-cn/partners/zulip/",
    "/zh-cn/tutorbot/mochat/": "/zh-cn/partners/mochat/",
    "/explore/extensions/": "/ecosystem/",
    "/zh-cn/explore/extensions/": "/zh-cn/ecosystem/",
    // 旧的 /docs/* 路径（拆站前）整体回到根
    "/docs": "/",
    "/docs/[...slug]": "/[...slug]",
  },
  integrations: [
    starlight({
      title: "DeepTutor",
      favicon: "/brand/favicon-32x32.png",
      description: "Agent-native, open-source personalized tutoring.",
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        "zh-cn": { label: "简体中文", lang: "zh-CN" },
      },
      logo: {
        src: "./src/assets/logo.png",
        replacesTitle: false,
      },
      customCss: ["./src/styles/global.css", "./src/styles/starlight.css"],
      components: {
        SiteTitle: "./src/components/SiteTitle.astro",
        SocialIcons: "./src/components/SocialIcons.astro",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/HKUDS/DeepTutor",
        },
        {
          icon: "discord",
          label: "Discord",
          href: "https://discord.gg/eRsjPgMU4t",
        },
      ],
      sidebar: [
        {
          "label": "Start here",
          "translations": {
            "zh-CN": "从这里开始"
          },
          "items": [
            {
              "label": "Documentation home",
              "translations": {
                "zh-CN": "文档主页"
              },
              "link": "/"
            },
            {
              "label": "Product guide",
              "translations": {
                "zh-CN": "产品使用路线"
              },
              "slug": "explore"
            }
          ]
        },
        {
          "label": "Install & configure",
          "translations": {
            "zh-CN": "安装与配置"
          },
          "items": [
            {
              "label": "Choose an installation",
              "translations": {
                "zh-CN": "选择安装方式"
              },
              "slug": "get-started"
            },
            {
              "label": "From source · dev",
              "translations": {
                "zh-CN": "源码安装 · dev"
              },
              "slug": "get-started/from-source"
            },
            {
              "label": "PyPI packages",
              "translations": {
                "zh-CN": "PyPI 安装"
              },
              "slug": "get-started/pypi"
            },
            {
              "label": "Docker",
              "translations": {
                "zh-CN": "Docker 部署"
              },
              "slug": "get-started/docker"
            },
            {
              "label": "CLI only",
              "translations": {
                "zh-CN": "纯 CLI"
              },
              "slug": "get-started/cli-only"
            },
            {
              "label": "Model providers",
              "translations": {
                "zh-CN": "模型提供方"
              },
              "slug": "get-started/providers"
            },
            {
              "label": "Multi-user deployment",
              "translations": {
                "zh-CN": "多用户部署"
              },
              "slug": "get-started/multi-user"
            },
            {
              "label": "Troubleshooting",
              "translations": {
                "zh-CN": "故障排查"
              },
              "slug": "get-started/troubleshooting"
            }
          ]
        },
        {
          "label": "Workspace",
          "translations": {
            "zh-CN": "工作区"
          },
          "items": [
            {
              "label": "Scope & switching",
              "translations": {
                "zh-CN": "范围与切换"
              },
              "slug": "explore/workspaces"
            },
            {
              "label": "Home",
              "translations": {
                "zh-CN": "主页"
              },
              "items": [
                {
                  "label": "Chat & capabilities",
                  "translations": {
                    "zh-CN": "对话与能力"
                  },
                  "slug": "explore/chat-workspace"
                },
                {
                  "label": "Notebook",
                  "translations": {
                    "zh-CN": "笔记本"
                  },
                  "slug": "explore/co-writer"
                },
                {
                  "label": "Task Board",
                  "translations": {
                    "zh-CN": "任务看板"
                  },
                  "slug": "explore/task-board"
                },
                {
                  "label": "Calendar",
                  "translations": {
                    "zh-CN": "日历"
                  },
                  "slug": "explore/calendar"
                }
              ]
            },
            {
              "label": "Learning",
              "translations": {
                "zh-CN": "学习"
              },
              "items": [
                {
                  "label": "Choose a learning method",
                  "translations": {
                    "zh-CN": "选择学习方式"
                  },
                  "slug": "explore/learning"
                },
                {
                  "label": "Books",
                  "translations": {
                    "zh-CN": "书籍"
                  },
                  "slug": "explore/book"
                },
                {
                  "label": "Mastery Path",
                  "translations": {
                    "zh-CN": "精通之路"
                  },
                  "slug": "explore/mastery-path"
                },
                {
                  "label": "Reading",
                  "translations": {
                    "zh-CN": "阅读"
                  },
                  "slug": "explore/reading"
                },
                {
                  "label": "Practice",
                  "translations": {
                    "zh-CN": "练习"
                  },
                  "slug": "explore/practice"
                }
              ]
            },
            {
              "label": "Resources",
              "translations": {
                "zh-CN": "资料"
              },
              "items": [
                {
                  "label": "Library & learning records",
                  "translations": {
                    "zh-CN": "资料库与学习记录"
                  },
                  "slug": "explore/space"
                },
                {
                  "label": "Favorites",
                  "translations": {
                    "zh-CN": "收藏夹"
                  },
                  "slug": "explore/favorites"
                },
                {
                  "label": "Knowledge Center",
                  "translations": {
                    "zh-CN": "知识库"
                  },
                  "slug": "explore/knowledge"
                },
                {
                  "label": "RAG integrations",
                  "translations": {
                    "zh-CN": "RAG 集成"
                  },
                  "slug": "ecosystem/rag-integration"
                }
              ]
            }
          ]
        },
        {
          "label": "Partners",
          "translations": {
            "zh-CN": "伙伴"
          },
          "items": [
            {
              "label": "Companions & workspace context",
              "translations": {
                "zh-CN": "伙伴与工作区上下文"
              },
              "slug": "explore/partners"
            },
            {
              "label": "Create & manage a partner",
              "translations": {
                "zh-CN": "创建与管理伙伴"
              },
              "slug": "partners"
            },
            {
              "label": "Channels",
              "translations": {
                "zh-CN": "渠道"
              },
              "items": [
                {
                  "label": "Channel matrix",
                  "translations": {
                    "zh-CN": "渠道选择"
                  },
                  "slug": "partners/channels"
                },
                {
                  "label": "WeChat",
                  "translations": {
                    "zh-CN": "个人微信"
                  },
                  "slug": "partners/weixin"
                },
                {
                  "label": "WeCom",
                  "translations": {
                    "zh-CN": "企业微信"
                  },
                  "slug": "partners/wecom"
                },
                {
                  "label": "QQ / NapCat",
                  "translations": {
                    "zh-CN": "QQ / NapCat"
                  },
                  "slug": "partners/qq"
                },
                {
                  "label": "Telegram",
                  "translations": {
                    "zh-CN": "Telegram"
                  },
                  "slug": "partners/telegram"
                },
                {
                  "label": "Discord",
                  "translations": {
                    "zh-CN": "Discord"
                  },
                  "slug": "partners/discord"
                },
                {
                  "label": "Slack",
                  "translations": {
                    "zh-CN": "Slack"
                  },
                  "slug": "partners/slack"
                },
                {
                  "label": "Feishu / Lark",
                  "translations": {
                    "zh-CN": "飞书 / Lark"
                  },
                  "slug": "partners/feishu"
                },
                {
                  "label": "DingTalk",
                  "translations": {
                    "zh-CN": "钉钉"
                  },
                  "slug": "partners/dingtalk"
                },
                {
                  "label": "Matrix",
                  "translations": {
                    "zh-CN": "Matrix"
                  },
                  "slug": "partners/matrix"
                },
                {
                  "label": "Zulip",
                  "translations": {
                    "zh-CN": "Zulip"
                  },
                  "slug": "partners/zulip"
                },
                {
                  "label": "Mattermost",
                  "translations": {
                    "zh-CN": "Mattermost"
                  },
                  "slug": "partners/mattermost"
                },
                {
                  "label": "WhatsApp",
                  "translations": {
                    "zh-CN": "WhatsApp"
                  },
                  "slug": "partners/whatsapp"
                },
                {
                  "label": "Email",
                  "translations": {
                    "zh-CN": "邮件"
                  },
                  "slug": "partners/email"
                },
                {
                  "label": "Mochat",
                  "translations": {
                    "zh-CN": "Mochat"
                  },
                  "slug": "partners/mochat"
                },
                {
                  "label": "Microsoft Teams",
                  "translations": {
                    "zh-CN": "Microsoft Teams"
                  },
                  "slug": "partners/msteams"
                }
              ]
            }
          ]
        },
        {
          "label": "Personalization",
          "translations": {
            "zh-CN": "个性化"
          },
          "items": [
            {
              "label": "Personas & reusable tools",
              "translations": {
                "zh-CN": "角色与可复用工具"
              },
              "slug": "explore/personalization"
            },
            {
              "label": "My Agents",
              "translations": {
                "zh-CN": "我的智能体"
              },
              "slug": "explore/subagents"
            },
            {
              "label": "Skills",
              "translations": {
                "zh-CN": "技能"
              },
              "slug": "ecosystem/skills"
            },
            {
              "label": "MCP Services",
              "translations": {
                "zh-CN": "MCP 服务"
              },
              "slug": "ecosystem/mcp"
            },
            {
              "label": "CLI Apps",
              "translations": {
                "zh-CN": "CLI 应用"
              },
              "slug": "ecosystem/cli-apps"
            },
            {
              "label": "Memory",
              "translations": {
                "zh-CN": "记忆"
              },
              "slug": "explore/memory"
            },
            {
              "label": "EduHub",
              "translations": {
                "zh-CN": "EduHub"
              },
              "slug": "ecosystem/eduhub"
            },
            {
              "label": "Extension overview",
              "translations": {
                "zh-CN": "扩展概览"
              },
              "slug": "ecosystem"
            }
          ]
        },
        {
          "label": "Settings & development",
          "translations": {
            "zh-CN": "设置与开发"
          },
          "items": [
            {
              "label": "Settings",
              "translations": {
                "zh-CN": "设置"
              },
              "slug": "explore/settings"
            },
            {
              "label": "CLI overview",
              "translations": {
                "zh-CN": "CLI 概览"
              },
              "slug": "cli"
            },
            {
              "label": "Command reference",
              "translations": {
                "zh-CN": "命令参考"
              },
              "slug": "cli/commands"
            },
            {
              "label": "Interactive REPL",
              "translations": {
                "zh-CN": "交互式 REPL"
              },
              "slug": "cli/chat-repl"
            },
            {
              "label": "Agent setup & handoff",
              "translations": {
                "zh-CN": "Agent 配置与交接"
              },
              "slug": "cli/agent-handoff"
            },
            {
              "label": "Python SDK",
              "translations": {
                "zh-CN": "Python SDK"
              },
              "slug": "cli/python-sdk"
            },
            {
              "label": "Server API",
              "translations": {
                "zh-CN": "服务端 API"
              },
              "slug": "cli/server-api"
            },
            {
              "label": "Contributing",
              "translations": {
                "zh-CN": "参与贡献"
              },
              "slug": "contributing"
            }
          ]
        }
      ],
    }),
  ],
});
