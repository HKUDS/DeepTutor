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
      // Product-domain groups. Slugs stay on current paths until the directory move.
      sidebar: [
        {
          label: "Get started",
          translations: { "zh-CN": "从这里开始" },
          items: [
            { label: "Install choices", translations: { "zh-CN": "安装方式" }, slug: "get-started" },
            { label: "Desktop", translations: { "zh-CN": "桌面端" }, slug: "get-started/desktop" },
            { label: "Docker", translations: { "zh-CN": "Docker" }, slug: "get-started/docker" },
            { label: "Providers & models", translations: { "zh-CN": "提供方与模型" }, slug: "get-started/providers" },
            { label: "Changelog", translations: { "zh-CN": "更新日志" }, slug: "get-started/changelog" },
          ],
        },
        {
          label: "Learning workspace",
          translations: { "zh-CN": "学习工作区" },
          items: [
            { label: "A first study session", translations: { "zh-CN": "串起一次完整学习" }, slug: "explore" },
            { label: "Workspaces", translations: { "zh-CN": "工作区" }, slug: "explore/workspaces" },
            { label: "Chat", translations: { "zh-CN": "对话" }, slug: "explore/chat-workspace" },
            { label: "Questions & practice", translations: { "zh-CN": "出题与练习" }, slug: "explore/practice" },
            { label: "Mastery Path", translations: { "zh-CN": "精通之路" }, slug: "explore/mastery-path" },
            { label: "Knowledge", translations: { "zh-CN": "知识库" }, slug: "explore/knowledge" },
            { label: "Books", translations: { "zh-CN": "书籍" }, slug: "explore/book" },
            { label: "Immersive Reading", translations: { "zh-CN": "沉浸式阅读" }, slug: "explore/reading" },
            { label: "Notebook", translations: { "zh-CN": "笔记本" }, slug: "explore/co-writer" },
            { label: "Favorites", translations: { "zh-CN": "收藏夹" }, slug: "explore/favorites" },
            { label: "Resources", translations: { "zh-CN": "资料" }, slug: "explore/space" },
            { label: "Task Board", translations: { "zh-CN": "任务看板" }, slug: "explore/task-board" },
            { label: "Calendar", translations: { "zh-CN": "日历" }, slug: "explore/calendar" },
            { label: "Memory", translations: { "zh-CN": "记忆" }, slug: "explore/memory" },
            { label: "Choose a learning method", translations: { "zh-CN": "选择学习方式" }, slug: "explore/learning" },
          ],
        },
        {
          label: "Multimodal studio",
          translations: { "zh-CN": "多模态工作室" },
          items: [
            {
              label: "Generate from Chat",
              translations: { "zh-CN": "在对话里生成" },
              slug: "explore/chat-workspace",
            },
          ],
        },
        {
          label: "Customize",
          translations: { "zh-CN": "定制" },
          items: [
            { label: "Personas & account", translations: { "zh-CN": "人格与账号" }, slug: "explore/personalization" },
            { label: "Skills", translations: { "zh-CN": "技能" }, slug: "ecosystem/skills" },
            { label: "MCP services", translations: { "zh-CN": "MCP 服务" }, slug: "ecosystem/mcp" },
            { label: "CLI Apps", translations: { "zh-CN": "CLI 应用" }, slug: "ecosystem/cli-apps" },
            { label: "EduHub", translations: { "zh-CN": "EduHub" }, slug: "ecosystem/eduhub" },
            { label: "My Agents", translations: { "zh-CN": "我的智能体" }, slug: "explore/subagents" },
            { label: "RAG integrations", translations: { "zh-CN": "RAG 集成" }, slug: "ecosystem/rag-integration" },
            { label: "Extension overview", translations: { "zh-CN": "扩展概览" }, slug: "ecosystem" },
          ],
        },
        {
          label: "Channels",
          translations: { "zh-CN": "渠道" },
          items: [
            { label: "Partners", translations: { "zh-CN": "伙伴" }, slug: "explore/partners" },
            { label: "Create & manage", translations: { "zh-CN": "创建与管理" }, slug: "partners" },
            { label: "Channel matrix", translations: { "zh-CN": "渠道矩阵" }, slug: "partners/channels" },
            {
              label: "Domestic IM",
              translations: { "zh-CN": "国内 IM" },
              items: [
                { label: "WeChat", translations: { "zh-CN": "个人微信" }, slug: "partners/weixin" },
                { label: "WeCom", translations: { "zh-CN": "企业微信" }, slug: "partners/wecom" },
                { label: "QQ / NapCat", translations: { "zh-CN": "QQ / NapCat" }, slug: "partners/qq" },
                { label: "Feishu / Lark", translations: { "zh-CN": "飞书 / Lark" }, slug: "partners/feishu" },
                { label: "DingTalk", translations: { "zh-CN": "钉钉" }, slug: "partners/dingtalk" },
                { label: "Mochat", translations: { "zh-CN": "Mochat" }, slug: "partners/mochat" },
              ],
            },
            {
              label: "International IM",
              translations: { "zh-CN": "海外 IM" },
              items: [
                { label: "Telegram", translations: { "zh-CN": "Telegram" }, slug: "partners/telegram" },
                { label: "Discord", translations: { "zh-CN": "Discord" }, slug: "partners/discord" },
                { label: "Slack", translations: { "zh-CN": "Slack" }, slug: "partners/slack" },
                { label: "WhatsApp", translations: { "zh-CN": "WhatsApp" }, slug: "partners/whatsapp" },
                { label: "Matrix", translations: { "zh-CN": "Matrix" }, slug: "partners/matrix" },
                { label: "Zulip", translations: { "zh-CN": "Zulip" }, slug: "partners/zulip" },
                { label: "Mattermost", translations: { "zh-CN": "Mattermost" }, slug: "partners/mattermost" },
                { label: "Microsoft Teams", translations: { "zh-CN": "Microsoft Teams" }, slug: "partners/msteams" },
                { label: "Email", translations: { "zh-CN": "邮件" }, slug: "partners/email" },
              ],
            },
          ],
        },
        {
          label: "Self-hosting",
          translations: { "zh-CN": "自部署" },
          items: [
            { label: "PyPI", translations: { "zh-CN": "PyPI 安装" }, slug: "get-started/pypi" },
            { label: "From source", translations: { "zh-CN": "从源码运行" }, slug: "get-started/from-source" },
            { label: "CLI only", translations: { "zh-CN": "纯 CLI" }, slug: "get-started/cli-only" },
            { label: "Multi-user", translations: { "zh-CN": "多用户部署" }, slug: "get-started/multi-user" },
            { label: "Settings", translations: { "zh-CN": "设置" }, slug: "explore/settings" },
            { label: "Troubleshooting", translations: { "zh-CN": "故障排查" }, slug: "get-started/troubleshooting" },
          ],
        },
        {
          label: "Developers",
          translations: { "zh-CN": "开发者" },
          items: [
            { label: "CLI overview", translations: { "zh-CN": "CLI 概览" }, slug: "cli" },
            { label: "Command reference", translations: { "zh-CN": "命令参考" }, slug: "cli/commands" },
            { label: "Interactive REPL", translations: { "zh-CN": "交互式 REPL" }, slug: "cli/chat-repl" },
            { label: "Agent handoff", translations: { "zh-CN": "Agent 交接" }, slug: "cli/agent-handoff" },
            { label: "Python SDK", translations: { "zh-CN": "Python SDK" }, slug: "cli/python-sdk" },
            { label: "Server API", translations: { "zh-CN": "服务端 API" }, slug: "cli/server-api" },
            { label: "Contributing", translations: { "zh-CN": "参与贡献" }, slug: "contributing" },
          ],
        },
      ],
    }),
  ],
});
