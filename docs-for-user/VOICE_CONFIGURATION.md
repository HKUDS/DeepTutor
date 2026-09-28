# 语音配置与音色试听

语音合成（TTS）和语音识别（STT）位于「设置 → 语音」；图像、视频生成位于「设置 → 多模态生成」。两者分别选择模型和默认配置。

## 火山引擎原生语音

在语音页面新增 **Volcengine Speech (Doubao)** 服务商。这里使用火山语音控制台的凭据，与方舟 Ark 的模型 API Key 分开。

- 新版控制台：填入 Speech API Key，App ID 留空。
- 旧版控制台：填入 App ID，并在密钥栏填 Access Token。
- 默认地址：`https://openspeech.bytedance.com/api/v3`。
- TTS：选择模型资源 ID，例如 `seed-tts-2.0`，再选择相同版本的音色，例如 Vivi 2.0。可配置语言、语速、格式、采样率；TTS 2.0 可填写表达指令。
- STT：模型使用 `bigmodel`，默认资源 ID 为 `volc.bigasr.auc_turbo`，使用录音文件识别极速版接口。浏览器录音会转换为 16 kHz 单声道 WAV；转换需要系统安装 ffmpeg。

账号须已开通所选资源及音色权限。模型或音色出现在建议列表中，不代表当前账号已获授权。

## 按模型配置

选项按服务商和具体模型提供。OpenAI 的不同 TTS 系列、OpenRouter 的 OpenAI/Gemini 模型、火山 TTS 1.0/2.0、Groq 英语/阿拉伯语模型分别使用对应音色建议。阿里云目前对接 Qwen TTS 的原生 HTTP 接口；CosyVoice 等使用其他协议的模型需要另行适配。

建议列表不是完整的模型目录。对于账号专属模型、部署名、私有音色，可以手动填写 ID；需确认它们使用当前服务商适配器支持的接口协议。

## 试听

在 TTS 模型配置中选择音色、语言和参数，填写相应语言的示例文本，点击「试听音色」。试听使用当前表单，不要求先保存，也不修改默认模型。修改配置或试听文本后，旧试听会清除；生成中的请求可取消。

一般试听文本最多 500 字符，Groq Orpheus 最多 200 字符。试听会调用所配置的服务商，可能产生语音合成费用。

## 官方接口资料

- [火山 TTS HTTP SSE](https://www.volcengine.com/docs/6561/1598757)
- [火山音色列表](https://www.volcengine.com/docs/6561/1257544)
- [火山录音识别极速版](https://www.volcengine.com/docs/6561/1631584)
- [Qwen TTS 音色列表](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list)
