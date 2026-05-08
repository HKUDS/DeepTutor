<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: एजेंट-नेटिव व्यक्तिगत शिक्षण

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[मुख्य विशेषताएँ](#key-features) · [शुरू करें](#get-started) · [अन्वेषण](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [रोडमैप](#roadmap) · [समुदाय](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **हर तरह का योगदान स्वागत है!** शाखा रणनीति, कोड मानक और शुरुआत के लिए [Contributing गाइड](../../CONTRIBUTING.md) देखें।

### 📦 रिलीज़

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — थिंकिंग-मॉडल/प्रोवाइडर फिक्स, विज़िबल नॉलेज इंडेक्स हिस्ट्री, और सेफर Co-Writer क्लियर/टेम्पलेट एडिटिंग।

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — चैट और TutorBot के लिए कैटलॉग-बेस्ड मॉडल सिलेक्शन, सेफर RAG री-इंडेक्सिंग, OpenAI Responses टोकन-लिमिट फिक्स, और Skills एडिटर वैलिडेशन।

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — स्मूदर लोकल लॉन्च सेटिंग्स, सेफर RAG क्वेरीज, क्लीनर लोकल एम्बेडिंग ऑथ, और Settings डार्क-मोड पॉलिश।

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — बुक पेज चैट पर्सिस्टेंस और रिबिल्ड फ्लोज, चैट-टु-बुक रेफरेंसेज, स्ट्रॉन्गर लैंग्वेज/रीजनिंग हैंडलिंग, RAG डॉक्यूमेंट एक्सट्रैक्शन हार्डनिंग।

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — NVIDIA NIM + Gemini एम्बेडिंग समर्थन, चैट इतिहास / स्किल / मेमोरी के लिए एकीकृत Space संदर्भ, सत्र स्नैपशॉट, RAG पुनः-अनुक्रमण लचीलापन।

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — पारदर्शी एम्बेडिंग एंडपॉइंट URL, अमान्य स्थायी वेक्टर पर RAG पुनः-अनुक्रमण लचीलापन, थिंकिंग-मॉडल आउटपुट के लिए मेमोरी सफाई, Deep Solve रनटाइम फिक्स।

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — स्थिरता: सुरक्षित RAG रूटिंग व एम्बेडिंग सत्यापन, Docker स्थिरता, IME-सुरक्षित इनपुट, Windows/GBK मजबूती।

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — संस्करणित KB इंडेक्स व पुनः-अनुक्रमण वर्कफ़्लो, नॉलेज वर्कस्पेस पुनर्निर्माण, नए अडैप्टर के साथ एम्बेडिंग ऑटो-डिस्कवरी, Space हब।

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — फ़ाइल-पूर्वावलोकन दराज के साथ स्थायी चैट संलग्नक, संलग्नक-जागरूक क्षमता पाइपलाइन, TutorBot Markdown निर्यात।

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — टेक्स्ट / कोड / SVG संलग्नक, एक-कमांड सेटअप टूर, Markdown चैट निर्यात, कॉम्पैक्ट KB प्रबंधन UI।

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — दस्तावेज़ संलग्नक (PDF/DOCX/XLSX/PPTX), तर्क मॉडल सोच-ब्लॉक, Soul टेम्पलेट संपादक, Co-Writer से नोटबुक सहेजें।

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — उपयोगकर्ता-लिखित Skills, चैट इनपुट प्रदर्शन ओवरहॉल, TutorBot ऑटो-स्टार्ट, बुक लाइब्रेरी UI, विज़ुअलाइज़ेशन फ़ुलस्क्रीन।

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — चरण-दर-चरण टोकन सीमाएँ, सभी प्रवेश बिंदुओं पर उत्तर पुनर्जनन, RAG व Gemma अनुकूलता फिक्स।

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Book Engine «जीवंत पुस्तक» संकलक, मल्टी-दस्तावेज़ Co-Writer, इंटरैक्टिव HTML विज़ुअलाइज़ेशन, चैट में प्रश्न बैंक @-उल्लेख।

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — स्कीमा-चालित Channels टैब, एकल RAG पाइपलाइन, चैट प्रॉम्प्ट बाहरी फ़ाइलों में।

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — सार्वभौमिक «अभी उत्तर दें», Co-Writer स्क्रॉल सिंक, एकीकृत सेटिंग्स पैनल, स्ट्रीमिंग Stop बटन।


<details>
<summary><b>पुराने रिलीज़ (2 सप्ताह से अधिक पहले)</b></summary>

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — LaTeX ब्लॉक गणित पार्सिंग ओवरहॉल; `agents.yaml` के माध्यम से LLM डायग्नोस्टिक प्रोब; अतिरिक्त हेडर फॉरवर्डिंग फिक्स; SaveToNotebook UUID फिक्स; Docker + स्थानीय LLM मार्गदर्शिका।

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — URL-आधारित बुकमार्क योग्य सत्र; Snow थीम; WebSocket हार्टबीट व ऑटो-रीकनेक्ट; ChatComposer प्रदर्शन सुधार; एम्बेडिंग प्रदाता रजिस्ट्री ओवरहॉल; Serper खोज प्रदाता।

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — बुकमार्क व श्रेणियों के साथ प्रश्न नोटबुक; Visualize में Mermaid; एम्बेडिंग बेमेल पहचान; Qwen/vLLM अनुकूलता; LM Studio व llama.cpp समर्थन; Glass थीम।

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — SearXNG फ़ॉलबैक के साथ खोज समेकन; प्रदाता स्विच फिक्स; फ्रंटएंड संसाधन रिसाव फिक्स।

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize क्षमता (Chart.js/SVG); क्विज़ डुप्लिकेट रोकथाम; o4-mini मॉडल समर्थन।

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — दर सीमा पर पुनःप्रयास के साथ एम्बेडिंग प्रगति; क्रॉस-प्लेटफ़ॉर्म निर्भरता फिक्स; MIME सत्यापन।

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — नेटिव OpenAI/Anthropic SDK (litellm हटाया); Windows पर Math Animator; मजबूत JSON पार्सिंग; पूर्ण चीनी i18n।

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — गर्म सेटिंग रीलोड; MinerU नेस्टेड आउटपुट; WebSocket फिक्स; न्यूनतम Python 3.11+।

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — एजेंट-नेटिव आर्किटेक्चर रिराइट (~200k पंक्तियाँ): Tools + Capabilities प्लगइन मॉडल, CLI व SDK, TutorBot, Co-Writer, Guided Learning, स्थायी मेमोरी।

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — सत्र स्थिरता, इंक्रीमेंटल अपलोड, लचीला RAG, पूर्ण चीनी स्थानीयकरण।

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, लॉग, बग फिक्स।

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — एकीकृत कॉन्फ़िग, KB प्रति RAG, प्रश्न जनरेशन, साइडबार।

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — मल्टी-प्रोवाइडर LLM/एम्बेडिंग, नया होम, RAG डिकप्लिंग, env वेरिएबल।

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, GHCR इमेज।

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 व React 19, WebSocket, कमज़ोरियाँ।

</details>

### 📰 समाचार

> **[2026.4.19]** 🎉 111 दिनों में 20k सितारे! समर्थन के लिए धन्यवाद — हम वास्तव में व्यक्तिगत, बुद्धिमान शिक्षण की दिशा में निरंतर सुधार करते रहेंगे।

> **[2026.4.10]** 📄 हमारा पेपर अब arXiv पर है! [प्रीप्रिंट](https://arxiv.org/abs/2604.26962) पढ़ें और DeepTutor की रचना व विचारधारा जानें।

> **[2026.4.4]** बहुत दिन बाद! ✨ DeepTutor v1.0.0 आ गया — Apache-2.0 के तहत एजेंट-नेटिव विकास: ज़मीन से आर्किटेक्चर रिराइट, TutorBot, लचीले मोड। नया अध्याय शुरू!

> **[2026.2.6]** 🚀 39 दिनों में 10k सितारे — समुदाय का धन्यवाद!

> **[2026.1.1]** नया साल मुबारक! [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), [Discussions](https://github.com/HKUDS/DeepTutor/discussions) से जुड़ें।

> **[2025.12.29]** DeepTutor आधिकारिक रूप से जारी।

<a id="key-features"></a>
## ✨ मुख्य विशेषताएँ

- **एकीकृत चैट वर्कस्पेस** — छह मोड, एक थ्रेड: Chat, Deep Solve, क्विज़, Deep Research, Math Animator और Visualize एक संदर्भ साझा करते हैं।
- **AI Co-Writer** — मल्टी-दस्तावेज़ Markdown वर्कस्पेस में AI सह-लेखक: फिर से लिखें, विस्तार, संक्षेप; KB व वेब।
- **Book Engine** — संरचित इंटरैक्टिव «जीवंत पुस्तकें»: मल्टी-एजेंट पाइपलाइन, 13 ब्लॉक प्रकार (क्विज़, फ्लैशकार्ड, टाइमलाइन, कॉन्सेप्ट ग्राफ़ आदि)।
- **नॉलेज हब** — RAG KB, रंगीन नोटबुक, प्रश्न बैंक, कस्टम Skills से शिक्षण शैली।
- **स्थायी मेमोरी** — प्रगति सारांश व शिक्षार्थी प्रोफ़ाइल; TutorBot के साथ साझा।
- **व्यक्तिगत TutorBot** — चैटबॉट नहीं: स्वायत्त ट्यूटर, अपना वर्कस्पेस, मेमोरी, व्यक्तित्व, कौशल। [nanobot](https://github.com/HKUDS/nanobot)।
- **एजेंट-नेटिव CLI** — क्षमता, KB, सत्र, TutorBot एक कमांड में; Rich व JSON। [`SKILL.md`](../../SKILL.md)।

---

<a id="get-started"></a>
## 🚀 शुरू करें

### पूर्वापेक्षाएँ

शुरू करने से पहले सुनिश्चित करें कि ये स्थापित हैं:

| आवश्यकता | संस्करण | जाँच | नोट |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | कोई भी | `git --version` | क्लोन के लिए |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | बैकएंड |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | लोकल वेब इंस्टॉल के लिए फ्रंटएंड रनटाइम |
| [npm](https://www.npmjs.com/) | Node.js के साथ बंडल | `npm --version` | Node.js के साथ इंस्टॉल |

कम से कम एक LLM प्रदाता की **API कुंजी** आवश्यक है (उदा. [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/))। सेटअप टूर भरने में मार्गदर्शन देता है।

### विकल्प A — सेटअप टूर (अनुशंसित)

**एक इंटरैक्टिव CLI स्क्रिप्ट** ताजे क्लोन से चलते ऐप तक ले जाती है — बिना मैनुअल `pip install`, `npm install` या `.env` संपादन। 7-चरणीय गाइडेड प्रवाह में सब कुछ पता लगाया, इंस्टॉल व कॉन्फ़िगर होता है।

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Python वर्चुअल वातावरण (एक चुनें):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # Anaconda/Miniconda
python -m venv .venv && source .venv/bin/activate                    # macOS/Linux
python -m venv .venv && .venv\Scripts\activate                       # Windows

# टूर चलाएँ
python scripts/start_tour.py
```

विज़ार्ड पूरा होने पर:

```bash
python scripts/start_web.py
```

> **दैनिक लॉन्च** — आमतौर पर टूर एक बार। बाद में `python scripts/start_web.py` से बैकएंड व फ्रंटएंड एक साथ (फ्रंट URL टर्मिनल में)। `start_tour.py` तभी दोबारा जब प्रदाता/पोर्ट बदलें या extra इंस्टॉल हों। वेब **सेटिंग्स** में **Run Tour** से UI हाइलाइट वॉकथ्रू दोहरा सकते हैं।

<a id="option-b-manual"></a>
### विकल्प B — मैन्युअल स्थानीय इंस्टॉल

पूर्ण नियंत्रण चाहिए तो सब कुछ स्वयं स्थापित व कॉन्फ़िगर करें।

**1. निर्भरताएँ स्थापित करें**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# वर्चुअल वातावरण बनाएँ व सक्रिय करें (विकल्प A जैसा)
conda create -n deeptutor python=3.11 && conda activate deeptutor

# बैकएंड + वेब सर्वर निर्भरताओं के साथ DeepTutor
pip install -e ".[server]"

# फ्रंटएंड (Node.js 18+ आवश्यक)
cd web && npm install && cd ..
```

**2. वातावरण कॉन्फ़िगर करें**

```bash
cp .env.example .env
```

`.env` संपादित करें और कम से कम आवश्यक फ़ील्ड भरें:

```dotenv
# LLM (आवश्यक)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# एम्बेडिंग (नॉलेज बेस के लिए आवश्यक)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>समर्थित LLM प्रदाता</b></summary>

| प्रदाता | Binding | डिफ़ॉल्ट Base URL |
|:--|:--|:--|
| AiHubMix | `aihubmix` | `https://aihubmix.com/v1` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` |
| Azure OpenAI | `azure_openai` | — |
| BytePlus | `byteplus` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| BytePlus Coding Plan | `byteplus_coding_plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` |
| Custom | `custom` | — |
| Custom (Anthropic API) | `custom_anthropic` | — |
| DashScope | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` |
| Gemini | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| GitHub Copilot | `github_copilot` | `https://api.githubcopilot.com` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| llama.cpp | `llama_cpp` | `http://localhost:8080/v1` |
| LM Studio | `lm_studio` | `http://localhost:1234/v1` |
| MiniMax | `minimax` | `https://api.minimaxi.com/v1` |
| MiniMax (Anthropic) | `minimax_anthropic` | `https://api.minimaxi.com/anthropic` |
| Mistral | `mistral` | `https://api.mistral.ai/v1` |
| Moonshot | `moonshot` | `https://api.moonshot.cn/v1` |
| Ollama | `ollama` | `http://localhost:11434/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| OpenAI Codex | `openai_codex` | `https://chatgpt.com/backend-api` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` |
| OpenVINO Model Server | `ovms` | `http://localhost:8000/v3` |
| Qianfan | `qianfan` | `https://qianfan.baidubce.com/v2` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` |
| Step Fun | `stepfun` | `https://api.stepfun.com/v1` |
| vLLM/Local | `vllm` | — |
| VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1` |
| Zhipu AI | `zhipu` | `https://open.bigmodel.cn/api/paas/v4` |

</details>

<details>
<summary><b>समर्थित एम्बेडिंग प्रदाता</b></summary>

| प्रदाता | Binding | मॉडल उदाहरण | डिफ़ॉल्ट आयाम |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | परिनियोजन नाम | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | कोई भी एम्बेडिंग मॉडल | — |
| OpenAI-संगत | `custom` | — | — |

OpenAI-संगत प्रदाता (DashScope, SiliconFlow, आदि) `custom` या `openai` binding से काम करते हैं।

</details>

<details>
<summary><b>समर्थित वेब खोज प्रदाता</b></summary>

| प्रदाता | एन्व कुंजी | नोट |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | अनुशंसित, मुफ़्त स्तर |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | Serper के माध्यम से Google परिणाम |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | सेल्फ-होस्ट, API कुंजी नहीं |
| DuckDuckGo | — | API कुंजी नहीं |
| Perplexity | `PERPLEXITY_API_KEY` | API कुंजी आवश्यक |

</details>

**3. सेवाएँ शुरू करें**

सबसे तेज़ तरीका:

```bash
python scripts/start_web.py
```

बैकएंड व फ्रंटएंड एक साथ चालू करता है और ब्राउज़र खोलता है।

अलग-अलग टर्मिनल में मैन्युअल:

```bash
# Backend (FastAPI)
python -m deeptutor.api.run_server

# Frontend (Next.js) — दूसरा टर्मिनल
cd web && npm run dev -- -p 3782
```

| सेवा | डिफ़ॉल्ट पोर्ट |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

[http://localhost:3782](http://localhost:3782) खोलें।

### विकल्प C — Docker

Docker बैकएंड व फ्रंटएंड को एक कंटेनर में लपेटता है; स्थानीय Python या Node.js अनावश्यक। [Docker Desktop](https://www.docker.com/products/docker-desktop/) (या Linux पर Docker Engine + Compose) पर्याप्त है।

**1. पर्यावरण चर** (नीचे दोनों विकल्पों के लिए आवश्यक)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

`.env` में कम से कम आवश्यक फ़ील्ड भरें ([विकल्प B](#option-b-manual) जैसा)।

**2a. आधिकारिक इमेज खींचें (अनुशंसित)**

आधिकारिक इमेज [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) पर प्रत्येक रिलीज़ के लिए `linux/amd64` व `linux/arm64` के लिए प्रकाशित होती हैं।

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

संस्करण पिन करने के लिए `docker-compose.ghcr.yml` में इमेज टैग संपादित करें:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # या :latest
```

**2b. स्रोत से बिल्ड**

```bash
docker compose up -d
```

`Dockerfile` से स्थानीय रूप से इमेज बनाता है और कंटेनर चालू करता है।

**3. सत्यापन व प्रबंधन**

कंटेनर healthy होने पर [http://localhost:3782](http://localhost:3782) खोलें।

```bash
docker compose logs -f   # लॉग टेल
docker compose down       # कंटेनर रोकें व हटाएँ
```

<details>
<summary><b>क्लाउड / रिमोट सर्वर</b></summary>

रिमोट सर्वर पर ब्राउज़र को बैकएंड API का सार्वजनिक URL चाहिए। `.env` में जोड़ें:

```dotenv
# सार्वजनिक URL जहाँ बैकएंड पहुँच योग्य है
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

फ्रंटएंड स्टार्टअप स्क्रिप्ट रनटाइम पर यह मान लागू करती है — रीबिल्ड अनावश्यक।

</details>

<details>
<summary><b>प्रमाणीकरण (सार्वजनिक डिप्लॉयमेंट)</b></summary>

प्रमाणीकरण **डिफ़ॉल्ट रूप से अक्षम** है — localhost पर लॉगिन आवश्यक नहीं। मल्टी-टेनेंट डिप्लॉयमेंट के लिए नीचे [मल्टी-यूज़र](#multi-user) अनुभाग देखें।

**हेडलेस सिंगल-यूज़र (बिना `/register` फ्लो):** env वेरिएबल के माध्यम से पहले एडमिन को प्री-सीड करें:

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<यहाँ हैश पेस्ट करें>
AUTH_SECRET=your-secret-here
```

</details>

<details>
<summary><b>PocketBase साइडकार (वैकल्पिक ऑथ + स्टोरेज)</b></summary>

PocketBase एक वैकल्पिक हल्का बैकएंड है जो बिल्ट-इन SQLite/JSON ऑथ और सेशन स्टोरेज को रिप्लेस करता है।

> ⚠️ **PocketBase मोड अभी केवल सिंगल-यूज़र के लिए है।** डिफ़ॉल्ट स्कीमा में `users` पर `role` फ़ील्ड नहीं है और queries `user_id` से फ़िल्टर नहीं होती हैं। मल्टी-यूज़र: `POCKETBASE_URL` खाली रखें।

```bash
docker compose up -d
open http://localhost:8090/_/
pip install pocketbase
python scripts/pb_setup.py
```

```dotenv
POCKETBASE_URL=http://localhost:8090
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=your-admin-password
```

</details>

<details>
<summary><b>डेव मोड (हॉट-रिलोड)</b></summary>

स्रोत माउंट करने व दोनों सेवाओं पर हॉट-रिलोड के लिए डेव ओवरले लगाएँ:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

`deeptutor/`, `deeptutor_cli/`, `scripts/` व `web/` में परिवर्तन तुरंत दिखते हैं।

</details>

<details>
<summary><b>कस्टम पोर्ट</b></summary>

`.env` में डिफ़ॉल्ट पोर्ट ओवरराइड करें:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

फिर पुनः आरंभ करें:

```bash
docker compose up -d     # या docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>डेटा स्थिरता</b></summary>

उपयोगकर्ता डेटा व नॉलेज बेस Docker वॉल्यूम के माध्यम से स्थानीय निर्देशिकाओं पर मैप होते हैं:

| कंटेनर पथ | होस्ट पथ | सामग्री |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | सेटिंग्स, वर्कस्पेस, सत्र, लॉग |
| `/app/data/memory` | `./data/memory` | साझा दीर्घकालिक मेमोरी (`SUMMARY.md`, `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | अपलोड दस्तावेज़ व वेक्टर इंडेक्स |

`docker compose down` के बाद भी ये निर्देशिकाएँ बनी रहती हैं और अगले `up` पर पुनः उपयोग होती हैं।

</details>

<details>
<summary><b>पर्यावरण चर संदर्भ</b></summary>

| चर | आवश्यक | विवरण |
|:---|:---:|:---|
| `LLM_BINDING` | **हाँ** | LLM प्रदाता (`openai`, `anthropic`, आदि) |
| `LLM_MODEL` | **हाँ** | मॉडल नाम (उदा. `gpt-4o`) |
| `LLM_API_KEY` | **हाँ** | LLM API कुंजी |
| `LLM_HOST` | **हाँ** | API URL |
| `EMBEDDING_BINDING` | **हाँ** | एम्बेडिंग प्रदाता |
| `EMBEDDING_MODEL` | **हाँ** | एम्बेडिंग मॉडल नाम |
| `EMBEDDING_API_KEY` | **हाँ** | एम्बेडिंग API कुंजी |
| `EMBEDDING_HOST` | **हाँ** | एम्बेडिंग एंडपॉइंट |
| `EMBEDDING_DIMENSION` | **हाँ** | वेक्टर आयाम |
| `SEARCH_PROVIDER` | नहीं | खोज (`tavily`, `jina`, `serper`, `perplexity`, आदि) |
| `SEARCH_API_KEY` | नहीं | खोज API कुंजी |
| `BACKEND_PORT` | नहीं | बैकएंड पोर्ट (डिफ़ॉल्ट `8001`) |
| `FRONTEND_PORT` | नहीं | फ्रंटएंड पोर्ट (डिफ़ॉल्ट `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | नहीं | क्लाउड के लिए सार्वजनिक बैकएंड URL |
| `DISABLE_SSL_VERIFY` | नहीं | SSL सत्यापन बंद (डिफ़ॉल्ट `false`) |

</details>

### विकल्प D — केवल CLI

यदि केवल CLI चाहिए, वेब फ्रंटएंड के बिना:

```bash
pip install -e ".[cli]"
```

LLM प्रदाता कॉन्फ़िगर करना अभी भी आवश्यक है। सबसे तेज़:

```bash
cp .env.example .env   # फिर .env में API कुंजियाँ भरें
```

कॉन्फ़िगरेशन के बाद:

```bash
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> पूर्ण गाइड: [DeepTutor CLI](#deeptutor-cli-guide)।

---

<a id="explore-deeptutor"></a>
## 📖 DeepTutor का अन्वेषण

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="DeepTutor आर्किटेक्चर" width="800">
</div>

### 💬 चैट — एकीकृत बुद्धिमान वर्कस्पेस

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="चैट" width="800">
</div>

छह मोड, **एकीकृत संदर्भ प्रबंधन**।

| मोड | कार्य |
|:---|:---|
| **Chat** | RAG, वेब, कोड, तर्क, ब्रेनस्टॉर्म, पेपर। |
| **Deep Solve** | मल्टी-एजेंट, उद्धरण। |
| **क्विज़ जनरेशन** | KB आधारित मूल्यांकन। |
| **Deep Research** | उप-विषय, समानांतर एजेंट, उद्धृत रिपोर्ट। |
| **Math Animator** | Manim। |
| **Visualize** | प्राकृतिक भाषा से SVG, Chart.js, Mermaid या स्वतंत्र HTML। |

टूल **वर्कफ़्लो से अलग** — आप चुनते हैं क्या सक्रिय करना है।

### ✍️ Co-Writer — मल्टी-दस्तावेज़ AI लेखन वर्कस्पेस

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

कई दस्तावेज़ बनाएं, प्रत्येक सहेजा गया — एक बार का मसौदा नहीं: पूर्ण Markdown, AI सह-लेखक। **फिर से लिखें**, **विस्तार**, **संक्षेप**; अनडू/रीडू; नोटबुक।

### 📖 Book Engine — इंटरैक्टिव «जीवंत पुस्तकें»

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="लाइब्रेरी" width="270"><img src="../../assets/figs/dt-book-1.png" alt="रीडर" width="270"><img src="../../assets/figs/dt-book-2.png" alt="एनीमेशन" width="270">
</div>

विषय दें, नॉलेज बेस दिखाएँ — संरचित इंटरैक्टिव पुस्तक: पढ़ने, स्व-परीक्षण और संदर्भ में चर्चा के लिए जीवित दस्तावेज़।

पर्दे के पीछे मल्टी-एजेंट रूपरेखा, स्रोत, अध्याय वृक्ष, पृष्ठ योजना और ब्लॉक संकलन। आप नियंत्रण में: प्रस्ताव समीक्षा, अध्याय पुनःक्रम, किसी भी पृष्ठ पर चैट।

13 ब्लॉक प्रकार — पाठ, कॉलआउट, क्विज़, फ्लैशकार्ड, कोड, आकृति, डीप डाइव, एनीमेशन, इंटरैक्टिव, टाइमलाइन, कॉन्सेप्ट ग्राफ़, अनुभाग, उपयोगकर्ता नोट — प्रत्येक अपने इंटरैक्टिव घटक के साथ। वास्तविक समय प्रगति टाइमलाइन।

### 📚 ज्ञान प्रबंधन

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="ज्ञान" width="800">
</div>

दस्तावेज़ संग्रह, नोट्स और शिक्षण व्यक्तित्व।

- **नॉलेज बेस** — PDF, TXT, MD।  
- **नोटबुक** — Chat, Co-Writer, Book या Deep Research से अंतर्दृष्टि, रंगों से।
- **प्रश्न बैंक** — जनरेट किए गए क्विज़ देखें; बुकमार्क और चैट में @-उल्लेख पिछले प्रदर्शन के लिए।
- **Skills** — `SKILL.md` से कस्टम शिक्षण व्यक्तित्व: नाम, विवरण, वैकल्पिक ट्रिगर, सक्रिय होने पर चैट सिस्टम प्रॉम्प्ट में Markdown।

### 🧠 मेमोरी

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="मेमोरी" width="800">
</div>

- **सारांश** — प्रगति।  
- **प्रोफ़ाइल** — पसंद, स्तर, लक्ष्य। TutorBot साझा।

---

<a id="tutorbot"></a>
### 🦞 TutorBot — स्थायी स्वायत्त AI ट्यूटर

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot आर्किटेक्चर" width="800">
</div>

[nanobot](https://github.com/HKUDS/nanobot) पर **बहु-इंस्टेंस** स्थायी एजेंट।

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul टेम्पलेट** — व्यक्तित्व व शिक्षण दर्शन।  
- **स्वतंत्र वर्कस्पेस** — मेमोरी, सत्र, कौशल; साझा ज्ञान परत।  
- **प्रोएक्टिव Heartbeat** — अनुस्मारक व कार्य।  
- **पूर्ण टूल** — RAG, कोड, वेब, पेपर, तर्क, ब्रेनस्टॉर्म।  
- **कौशल सीखना** — skill फ़ाइलें।  
- **मल्टी-चैनल** — Telegram, Discord, Slack, Feishu, WeCom, DingTalk, ईमेल आदि।  
- **टीम व उप-एजेंट**।

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — एजेंट-नेटिव इंटरफ़ेस

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

बिना ब्राउज़र: क्षमता, KB, सत्र, मेमोरी, TutorBot। Rich + JSON। [`SKILL.md`](../../SKILL.md)।

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

```bash
deeptutor chat --capability deep_solve --kb my-kb
# REPL में: /cap, /tool, /kb, /history, /notebook, /config से तुरंत बदलाव
```

```bash
deeptutor kb create my-kb --doc textbook.pdf
deeptutor kb add my-kb --docs-dir ./papers/
deeptutor kb search my-kb "gradient descent"
deeptutor kb set-default my-kb
```

```bash
deeptutor run chat "Summarize chapter 3" -f rich
deeptutor run chat "Summarize chapter 3" -f json
```

```bash
deeptutor session list
deeptutor session open <id>
```

<details>
<summary><b>पूर्ण CLI संदर्भ</b></summary>

**शीर्ष स्तर**

| कमांड | विवरण |
|:---|:---|
| `deeptutor run <capability> <message>` | एक बार में क्षमता चलाएँ (`chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`) |
| `deeptutor chat` | इंटरैक्टिव REPL (`--capability`, `--tool`, `--kb`, `--language` आदि) |
| `deeptutor serve` | DeepTutor API सर्वर शुरू करें |

**`deeptutor bot`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor bot list` | सभी TutorBot इंस्टेंस |
| `deeptutor bot create <id>` | नया बॉट बनाएँ और चलाएँ (`--name`, `--persona`, `--model`) |
| `deeptutor bot start <id>` | बॉट शुरू |
| `deeptutor bot stop <id>` | बॉट रोकें |

**`deeptutor kb`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor kb list` | नॉलेज बेस सूची |
| `deeptutor kb info <name>` | विवरण |
| `deeptutor kb create <name>` | दस्तावेज़ों से बनाएँ (`--doc`, `--docs-dir`) |
| `deeptutor kb add <name>` | दस्तावेज़ जोड़ें |
| `deeptutor kb search <name> <query>` | खोज |
| `deeptutor kb set-default <name>` | डिफ़ॉल्ट KB |
| `deeptutor kb delete <name>` | हटाएँ (`--force`) |

**`deeptutor memory`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor memory show [file]` | देखें (`summary`, `profile`, `all`) |
| `deeptutor memory clear [file]` | साफ़ करें (`--force`) |

**`deeptutor session`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor session list` | सत्र सूची (`--limit`) |
| `deeptutor session show <id>` | संदेश |
| `deeptutor session open <id>` | REPL में जारी रखें |
| `deeptutor session rename <id>` | नाम बदलें (`--title`) |
| `deeptutor session delete <id>` | हटाएँ |

**`deeptutor notebook`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor notebook list` | नोटबुक सूची |
| `deeptutor notebook create <name>` | बनाएँ (`--description`) |
| `deeptutor notebook show <id>` | रिकॉर्ड |
| `deeptutor notebook add-md <id> <path>` | Markdown आयात |
| `deeptutor notebook replace-md <id> <rec> <path>` | रिकॉर्ड बदलें |
| `deeptutor notebook remove-record <id> <rec>` | रिकॉर्ड हटाएँ |

**`deeptutor book`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor book list` | वर्कस्पेस में सभी पुस्तकें |
| `deeptutor book health <book_id>` | KB ड्रिफ्ट व पुस्तक स्वास्थ्य |
| `deeptutor book refresh-fingerprints <book_id>` | KB फिंगरप्रिंट ताज़ा करें, पुराने पृष्ठ साफ़ करें |

**`deeptutor config` / `plugin` / `provider`**

| कमांड | विवरण |
|:---|:---|
| `deeptutor config show` | कॉन्फ़िग सारांश |
| `deeptutor plugin list` | पंजीकृत टूल और क्षमताएँ |
| `deeptutor plugin info <name>` | टूल या क्षमता विवरण |
| `deeptutor provider login <provider>` | प्रदाता प्रमाणीकरण (`openai-codex` OAuth लॉगिन; `github-copilot` मौजूदा Copilot सत्र सत्यापित करता है) |

</details>

---

<a id="multi-user"></a>
### 👥 मल्टी-यूज़र — प्रति-उपयोगकर्ता वर्कस्पेस के साथ साझा डिप्लॉयमेंट

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="मल्टी-यूज़र" width="800">
</div>

प्रमाणीकरण चालू करने पर DeepTutor एक मल्टी-टेनेंट डिप्लॉयमेंट बन जाता है: **प्रति-उपयोगकर्ता आइसोलेटेड वर्कस्पेस** और **एडमिन-क्यूरेटेड रिसोर्स**। पहला रजिस्टर करने वाला एडमिन बनता है। बाद के अकाउंट एडमिन (इनवाइट-ओनली) द्वारा बनाए जाते हैं, प्रत्येक को स्कोप्ड चैट हिस्ट्री/मेमोरी/नोटबुक/नॉलेज बेस मिलती है।

**क्विक स्टार्ट (5 स्टेप्स):**

```bash
# 1. प्रोजेक्ट रूट .env में ऑथ सक्षम करें
echo 'AUTH_ENABLED=true' >> .env
echo 'AUTH_SECRET=<64+ रैंडम कैरेक्टर पेस्ट करें>' >> .env

# 2. Web स्टैक रीस्टार्ट करें
python scripts/start_web.py

# 3. http://localhost:3782/register खोलें और पहला अकाउंट बनाएं
#    पहला रजिस्ट्रेशन ही सार्वजनिक है; वह यूज़र एडमिन बनता है
#    और /register एंडपॉइंट स्वचालित रूप से बंद हो जाता है

# 4. एडमिन के रूप में /admin/users → "Add user" पर जाएं

# 5. प्रत्येक यूज़र के लिए स्लाइडर आइकन क्लिक करें → LLM प्रोफाइल,
#    नॉलेज बेस, और Skills असाइन करें → सेव करें
```

**एडमिन को क्या दिखता है:**

- `/settings` पर **पूरा सेटिंग्स पेज** — LLM/एम्बेडिंग/सर्च, API कीज़, मॉडल कैटलॉग।
- `/admin/users` पर **यूज़र मैनेजमेंट** — अकाउंट बनाना, प्रमोट करना, डिमोट करना, डिलीट करना।
- **ग्रांट एडिटर** — नॉन-एडमिन यूज़र के लिए मॉडल प्रोफाइल, KB, Skills चुनें; ग्रांट में **केवल लॉजिकल IDs**।
- **ऑडिट ट्रेल** — हर ग्रांट बदलाव `multi-user/_system/audit/usage.jsonl` में।

**सामान्य यूज़र को क्या मिलता है:**

- `multi-user/<uid>/` के तहत **आइसोलेटेड वर्कस्पेस** — अपना `chat_history.db`, मेमोरी, नोटबुक, KB।
- एडमिन-असाइन्ड KB/स्किल्स का **रीड-ओनली एक्सेस**, "एडमिन द्वारा असाइन्ड" बैज के साथ।
- **रिडैक्टेड सेटिंग्स पेज** — थीम, लैंग्वेज, ग्रांटेड मॉडल्स का सारांश; API कीज़ नॉन-एडमिन को नहीं दिखतीं।
- **स्कोप्ड LLM** — एडमिन-असाइन्ड मॉडल से चैट; ग्रांट न होने पर अप-फ्रंट रिजेक्शन।

**वर्कस्पेस लेआउट:**

```
multi-user/
├── _system/
│   ├── auth/users.json
│   ├── auth/auth_secret
│   ├── grants/<uid>.json
│   └── audit/usage.jsonl
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**कॉन्फ़िगरेशन रेफरेंस:**

| वेरिएबल | आवश्यक | विवरण |
|:---|:---|:---|
| `AUTH_ENABLED` | हाँ | `true` से मल्टी-यूज़र ऑथ सक्षम। डिफ़ॉल्ट `false`। |
| `AUTH_SECRET` | अनुशंसित | JWT साइनिंग सीक्रेट; खाली हो तो `multi-user/_system/auth/auth_secret` में लिखा जाता है। |
| `AUTH_TOKEN_EXPIRE_HOURS` | नहीं | JWT अवधि; डिफ़ॉल्ट 24 घंटे। |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | नहीं | सिंगल-यूज़र फ़ॉलबैक; मल्टी-यूज़र में खाली रखें। |
| `NEXT_PUBLIC_AUTH_ENABLED` | ऑटो | `start_web.py` द्वारा `AUTH_ENABLED` से मिरर किया जाता है। |

> ⚠️ **PocketBase मोड (`POCKETBASE_URL` सेट) केवल सिंगल-यूज़र** — कोई `role` फ़ील्ड नहीं, `user_id` से फ़िल्टर नहीं। मल्टी-यूज़र: `POCKETBASE_URL` खाली रखें।

> ⚠️ **सिंगल-प्रोसेस रिकमेंडेड।** पहले एडमिन प्रमोशन को `threading.Lock` से सुरक्षित किया गया है। मल्टी-वर्कर: पहले एडमिन को ऑफलाइन बनाएं।

<a id="roadmap"></a>
## 🗺️ रोडमैप

| स्थिति | माइलस्टोन |
|:---:|:---|
| 🎯 | **प्रमाणीकरण व लॉगिन** — सार्वजनिक डिप्लॉय के लिए वैकल्पिक लॉगिन पृष्ठ व बहु-उपयोगकर्ता समर्थन |
| 🎯 | **थीम व रूप** — विविध थीम व अनुकूलित UI दिखावट |
| 🎯 | **इंटरैक्शन में सुधार** — आइकन डिज़ाइन व इंटरैक्शन विवरणों का अनुकूलन |
| 🔜 | **बेहतर मेमोरी** — बेहतर मेमोरी प्रबंधन का एकीकरण |
| 🔜 | **LightRAG एकीकरण** — [LightRAG](https://github.com/HKUDS/LightRAG) को उन्नत नॉलेज बेस इंजन के रूप में |
| 🔜 | **दस्तावेज़ साइट** — गाइड, API संदर्भ व ट्यूटोरियल सहित पूर्ण दस्तावेज़ीकरण |

> यदि DeepTutor उपयोगी लगे तो [स्टार दें](https://github.com/HKUDS/DeepTutor/stargazers) — हमें प्रोत्साहन मिलता है!

---

<a id="community"></a>
## 🌐 समुदाय व पारिस्थितिकी तंत्र

| परियोजना | भूमिका |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | TutorBot इंजन |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| तेज़ RAG | बिना-कोड एजेंट | स्वचालित अनुसंधान | अल्ट्रा-लाइट एजेंट |

## 🤝 योगदान

<div align="center">

हम चाहते हैं कि DeepTutor समुदाय के लिए उपहार बने। 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

[CONTRIBUTING.md](../../CONTRIBUTING.md) देखें।

## ⭐ स्टार इतिहास

<div align="center">
<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="Star History" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
  </picture>
</a>
</div>

<p align="center">
 <a href="https://www.star-history.com/hkuds/deeptutor">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
   <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
  </picture>
 </a>
</p>

<div align="center">

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Issues](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

[Apache License 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
