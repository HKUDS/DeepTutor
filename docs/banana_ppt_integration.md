BananaPPT -> DeepTutor Integration Plan (Frontend Export Path)
==============================================================

Goal
----
Integrate BananaPPT-quality PPT generation into DeepTutor while keeping:
- Frontend PPTX export via pptxgenjs.
- All AI calls on the backend only (no API keys in browser).
- Notebook entry point only (no separate page).
- Single visible export path for users.

Non-Goals
---------
- Removing the existing python-pptx pipeline.
- Reworking the research report UI outside the Notebook page.
- Forcing Banana flow when disabled by config.

High-Level Architecture
-----------------------
Frontend (Next.js)
  Notebook page -> PPT Mode -> Preview Modal -> pptxgenjs export
                     |                 ^
                     |                 |
                     v                 |
Backend (FastAPI) -> /ppt_outline -----
                  -> /ppt_image
                  -> /ppt_config

Single-path UX: "Export PPT" uses Banana flow only.

Data Model
----------

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

Backend Config
--------------
Use a dedicated config block to avoid confusion with python-pptx settings.

File: `config/main.yaml`

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

Backend Implementation
----------------------
- Config loader:
  - `src/services/config/loader.py` adds BananaPptConfig + get_banana_ppt_config.
- Service:
  - `src/services/export/banana_ppt_service.py` provides outline + image generation.
- API:
  - `POST /api/v1/research/ppt_outline`
  - `POST /api/v1/research/ppt_image`
  - `GET /api/v1/research/ppt_config`

Frontend Implementation
-----------------------
- Types: `web/types/ppt.ts`
- PPTX export: `web/lib/pptGenerator.ts` (pptxgenjs, client-only)
- UI:
  - `web/components/ppt/SlidePreview.tsx`
  - `web/components/ppt/PptPreviewModal.tsx`
- Notebook integration:
  - `web/app/notebooks/[id]/page.tsx`
  - Replace PPT export flow:
    1) Call `/ppt_outline`
    2) Open preview modal
    3) Generate images in background via `/ppt_image`
    4) Export with pptxgenjs

Caching + Concurrency
---------------------
- Backend caches images in `data/user/ppt_images/<sha256>.png`.
- Frontend keeps data URLs in memory for preview/export.
- Frontend supports incremental UI updates during image generation.

Rollout
-------
- `export.banana_ppt.enabled` toggles UI availability.

Testing Checklist
-----------------
- Outline JSON validity for long reports.
- Image generation works and caches hits.
- PPTX opens correctly in PowerPoint/WPS.
- Slide edits affect export output.
- Single image failures do not block export.

Demo Constraints
----------------
- No single-slide image regeneration.
- No legacy export fallback in UI.
