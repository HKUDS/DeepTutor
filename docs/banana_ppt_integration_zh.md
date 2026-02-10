BananaPPT -> DeepTutor 融合方案（前端导出路径）
==========================================

目标
----
在 DeepTutor 中引入 BananaPPT 生成质量，同时满足：
- 前端用 pptxgenjs 导出 PPTX。
- 所有 AI 调用在后端完成（前端不暴露密钥）。
- 仅在 Notebook 入口使用（不新增独立页面）。
- 用户只看到单一路径（避免冗余）。

非目标
------
- 不移除现有 python-pptx 导出链路。
- 不改造 Notebook 之外的报告导出入口。
- 不强制所有用户走 Banana 流程（支持配置开关）。

总体架构
--------
前端（Next.js）
  Notebook Page -> PPT Mode -> 预览弹窗 -> pptxgenjs 导出
                     |                 ^
                     |                 |
                     v                 |
后端（FastAPI） -> /ppt_outline -------
                -> /ppt_image
                -> /ppt_config

用户侧仅展示 Banana 导出路径。

数据模型
--------

```json
{
  "title": "string",
  "subtitle": "string",
  "themeColor": "#RRGGBB",
  "accentColor": "#RRGGBB",
  "slides": [
    {
      "title": "string",
      "points": ["string", "..."],
      "layout": "SECTION_HEADER|OVERVIEW|SPLIT_IMAGE_LEFT|SPLIT_IMAGE_RIGHT|TOP_IMAGE|TYPOGRAPHIC_WITH_IMAGE|QUOTE|TYPOGRAPHIC",
      "imagePrompt": "string (optional)",
      "generatedImageUrl": "data:image/... (optional)"
    }
  ]
}
```

后端配置
--------
使用独立配置段，避免与 python-pptx 混淆。

文件：`config/main.yaml`

```yaml
export:
  banana_ppt:
    enabled: true
    max_slides: 15
    outline:
      temperature: 0.4
      max_tokens: 4000
    image:
      model: "gemini-2.5-flash-image"
      api_key: ""
      base_url: ""
      binding: "gemini"
      aspect_ratio: "16:9"
    style_templates: []
```

后端实现
--------
- 配置加载：`src/services/config/loader.py`
- 服务：`src/services/export/banana_ppt_service.py`
- API：
  - `POST /api/v1/research/ppt_outline`
  - `POST /api/v1/research/ppt_image`
  - `GET /api/v1/research/ppt_config`

前端实现
--------
- Types：`web/types/ppt.ts`
- 导出逻辑：`web/lib/pptGenerator.ts`
- 组件：
  - `web/components/ppt/SlidePreview.tsx`
  - `web/components/ppt/PptPreviewModal.tsx`
- Notebook 集成：
  - `web/app/notebooks/[id]/page.tsx`
  - 流程：outline -> 预览 -> 图片 -> pptxgenjs 导出

缓存与并发
----------
- 图片缓存：`data/user/ppt_images/<sha256>.png`。
- 前端内存持有 data URL 供预览/导出。
- 前端逐步更新图片生成进度。

开关
----
- `export.banana_ppt.enabled` 控制可用性。

测试清单
--------
- Outline JSON 稳定性。
- 图片生成与缓存命中。
- PPTX 在 PowerPoint/WPS 正常打开。
- 编辑后导出正确。
- 单图失败不阻塞导出。

Demo 约束
---------
- 不提供单页重新生成图片。
- 不在 UI 暴露旧导出回退。
