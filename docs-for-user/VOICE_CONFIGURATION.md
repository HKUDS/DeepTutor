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

选项按服务商和具体模型提供。OpenAI 的不同 TTS 系列、OpenRouter 的 OpenAI/Gemini 模型、火山 TTS 1.0/2.0、Groq 英语/阿拉伯语模型分别使用对应音色建议。阿里云支持 Qwen3 TTS 和 Qwen-Audio TTS 的原生 HTTP 接口，并按模型自动选择调用端点；CosyVoice 等模型仍需另行适配。

建议列表不是完整的模型目录。对于账号专属模型、部署名、私有音色，可以手动填写 ID；需确认它们使用当前服务商适配器支持的接口协议。

## 阿里云百炼

在「设置 → 语音」添加 **Aliyun DashScope** 模型。提供方 URL 可使用北京地域 API 基地址 `https://dashscope.aliyuncs.com/api/v1`，也可使用业务空间地址 `https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/api/v1`。填入同地域的百炼 API Key。

| 模型 ID | 推荐音色 ID | 音频格式 | 语言 |
| --- | --- | --- | --- |
| `qwen3-tts-flash` | `Cherry`（芊悦，注意大小写） | WAV | `Chinese` 或 `Auto` |
| `qwen3-tts-instruct-flash` | `Cherry` | WAV | `Chinese` 或 `Auto` |
| `qwen-audio-3.0-tts-plus` | `longanlingxin`（龙安灵心） | MP3、WAV、Opus、PCM | `zh` 或 `en`；留空由文本和音色决定 |
| `qwen-audio-3.0-tts-flash` | `longanfengyue`（龙安风悦） | MP3、WAV、Opus、PCM | `zh` 或 `en`；留空由文本和音色决定 |

Qwen-Audio TTS 的非实时合成仅在北京地域可用。Qwen3 TTS 也可使用新加坡地域，但须使用对应地域的 URL 和 API Key。两类模型的音色 ID 和语言参数不同，切换模型时请从对应的推荐音色中选择。

提供方连接若使用阿里云官方的 `/compatible-mode/v1` 地址，语音调用会自动转换为原生 API 基地址。若填写完整的合成端点，该端点须与模型系列匹配；通常填写 API 基地址即可。

「获取模型列表」只验证列表接口可访问，不代表所选模型、音色已能合成语音。请点击「试听音色」验证，成功后保存并选择默认 TTS 模型。

## 试听

在 TTS 模型配置中选择音色、语言和参数，填写相应语言的示例文本，点击「试听音色」。试听使用当前表单，不要求先保存，也不修改默认模型。修改配置或试听文本后，旧试听会清除；生成中的请求可取消。

如果合成较慢，在同一模型配置中调整「请求超时（秒）」：范围为 5–600 秒，留空默认 60 秒。试听使用当前表单的值；应用设置后，正文朗读也使用该值。超时会提示调整此参数或缩短文本。

一般试听文本最多 500 字符，Groq Orpheus 最多 200 字符。试听会调用所配置的服务商，可能产生语音合成费用。

试听失败时，页面会区分 API Key/地域不匹配、模型或音色权限不足、地址或模型不存在、参数被拒绝、额度/限流、网络超时和音频下载失败。错误提示不显示服务商返回的原始报文或凭据。

## 官方接口资料

- [火山 TTS HTTP SSE](https://www.volcengine.com/docs/6561/1598757)
- [火山音色列表](https://www.volcengine.com/docs/6561/1257544)
- [火山录音识别极速版](https://www.volcengine.com/docs/6561/1631584)
- [Qwen TTS 音色列表](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list)
- [Qwen-Audio TTS 音色列表](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list)
- [Qwen-Audio TTS HTTP 接口](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api)
