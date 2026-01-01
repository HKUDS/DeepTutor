import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "DeepTutor",
  description: "AI-Powered Personalized Learning Assistant",

  // GitHub Pages 部署配置
  base: '/DeepTutor/',

  head: [
    ['link', { rel: 'icon', href: '/DeepTutor/logo.png' }]
  ],

  themeConfig: {
    logo: '/logo.png',

    nav: [
      { text: 'Home', link: '/' },
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Features', link: '/features/overview' },
      { text: 'Roadmap', link: '/roadmap' },
      { text: 'Community', link: '/community/contributing' },
      { text: 'GitHub', link: 'https://github.com/HKUDS/DeepTutor' }
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Guide',
          items: [
            { text: 'Getting Started', link: '/guide/getting-started' },
            { text: 'Configuration', link: '/guide/configuration' },
            { text: 'Troubleshooting', link: '/guide/troubleshooting' }
          ]
        }
      ],
      '/features/': [
        {
          text: 'Features',
          items: [
            { text: 'Overview', link: '/features/overview' }
          ]
        }
      ],
      '/community/': [
        {
          text: 'Community',
          items: [
            { text: 'Discussions', link: '/community/discussions' },
            { text: 'Contributing', link: '/community/contributing' }
          ]
        }
      ],
      '/roadmap': [
        {
          text: 'Roadmap',
          items: [
            { text: 'Roadmap', link: '/roadmap' }
          ]
        }
      ]
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/HKUDS/DeepTutor' }
    ],

    footer: {
      message: 'Released under the AGPL-3.0 License.',
      copyright: 'Copyright © 2024-2025 HKUDS'
    },

    search: {
      provider: 'local'
    }
  }
})
