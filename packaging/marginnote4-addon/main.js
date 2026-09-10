;(function () {
try {
// DeepTutor Sync — MarginNote 4 native add-on
// Pushes notes / excerpts / flashcards / mindmap nodes / documents to a
// self-hosted DeepTutor instance over its official MarginNote 4 bridge:
//   POST {server}/api/marginnote4/sync        (Authorization: MarginNote id:token, X-MN4-KB: <kb>)
//   POST {server}/api/marginnote4/heartbeat
// Written against the MN4 JSExtension contract:
//   JSB.newAddon = () => JSB.defineClass("DeepTutorSync : JSExtension", {...})
// No bundler, no external library — plain ES5 for JSCore.

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------

var SETTINGS_KEY = "deeptutor_sync_settings_v1"
var SYNC_INTERVAL_SEC = 60
var BATCH_SIZE = 500

var COLOR_NAMES = [
  "red", "orange", "yellow", "green", "teal", "blue", "purple", "pink",
  "brown", "gray", "cyan", "magenta", "lime", "indigo", "violet", "olive"
]

function defaultSettings() {
  return { serverUrl: "", kbName: "", credential: "", enabled: false,
           prompted: false,
           lastSyncAt: "", lastStored: 0, lastUpdated: 0, lastError: "" }
}

function loadSettings() {
  try {
    var s = NSUserDefaults.standardUserDefaults().objectForKey(SETTINGS_KEY)
    if (s && typeof s === "object") {
      var d = defaultSettings()
      for (var k in d) if (s[k] !== undefined) d[k] = s[k]
      return d
    }
  } catch (e) {}
  return defaultSettings()
}

function saveSettings(s) {
  try {
    NSUserDefaults.standardUserDefaults().setObjectForKey(s, SETTINGS_KEY)
  } catch (e) {}
}

function hud(text, duration) {
  try {
    var app = (typeof self !== "undefined" && self && self.app) ? self.app : Application.sharedInstance()
    var win = (typeof self !== "undefined" && self && self.window) ? self.window : app.focusWindow
    app.showHUD(String(text), win, duration === undefined ? 2 : duration)
  } catch (e) {}
}

// base64 -> utf8 (NSData.base64Encoding() returns standard base64)
function base64ToUtf8(b64) {
  var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  var lookup = {}
  for (var i = 0; i < 64; i++) lookup[chars.charAt(i)] = i
  b64 = String(b64).replace(/[^A-Za-z0-9+/=]/g, "")
  var bytes = []
  var buf = 0, bits = 0
  for (var j = 0; j < b64.length; j++) {
    var c = b64.charAt(j)
    if (c === "=") break
    var v = lookup[c]
    if (v === undefined) continue
    buf = (buf << 6) | v
    bits += 6
    if (bits >= 8) {
      bits -= 8
      bytes.push((buf >> bits) & 0xff)
    }
  }
  var out = ""
  var n = 0
  while (n < bytes.length) {
    var b0 = bytes[n++]
    if (b0 < 0x80) {
      out += String.fromCharCode(b0)
    } else if (b0 < 0xe0) {
      out += String.fromCharCode(((b0 & 0x1f) << 6) | (bytes[n++] & 0x3f))
    } else if (b0 < 0xf0) {
      out += String.fromCharCode(((b0 & 0x0f) << 12) | ((bytes[n++] & 0x3f) << 6) | (bytes[n++] & 0x3f))
    } else {
      var cp = ((b0 & 0x07) << 18) | ((bytes[n++] & 0x3f) << 12) | ((bytes[n++] & 0x3f) << 6) | (bytes[n++] & 0x3f)
      cp -= 0x10000
      out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff))
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// Network (NSURLConnection bridge; same approach as OhMyMN's fetch)
// ---------------------------------------------------------------------------

function dtFetch(url, options) {
  options = options || {}
  return new Promise(function (resolve, reject) {
    var request
    try {
      request = NSMutableURLRequest.requestWithURL(NSURL.URLWithString(String(url).trim()))
    } catch (e) { reject("bad url: " + e); return }
    request.setHTTPMethod(options.method || "GET")
    request.setTimeoutInterval(options.timeout || 15)
    var headers = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "User-Agent": "DeepTutorSync/1.0.0 (MarginNote 4 add-on)"
    }
    if (options.headers) for (var k in options.headers) headers[k] = options.headers[k]
    try { request.setAllHTTPHeaderFields(headers) } catch (e) {}
    if (options.json) {
      try { request.setHTTPBody(NSData.dataWithStringEncoding(JSON.stringify(options.json), 4)) } catch (e) { reject("body: " + e); return }
    }
    try {
      NSURLConnection.sendAsynchronousRequestQueueCompletionHandler(
        request,
        NSOperationQueue.mainQueue(),
        function () {
          // MN4 4.4.6 的回调数据形态与 4.1.x 不同：可能是 NSData（有 base64Encoding）、
          // 已解析的 JSON 对象、字符串、HTTP 元对象或 NSError。严格分类：
          // 找不到可信的成功载荷就当作失败，并把原始信息带上，绝不静默吞掉。
          try {
            var body = null
            var errMsg = null
            var fallback = null
            for (var i = 0; i < arguments.length; i++) {
              var d = arguments[i]
              if (d == null) continue
              if (typeof d === "object") {
                if (typeof d.base64Encoding === "function") {
                  body = base64ToUtf8(String(d.base64Encoding()))
                  break
                }
                if (typeof d.statusCode === "number" || d.allHeaderFields) continue // HTTP 响应元对象
                if (typeof d.code === "number" || d.domain || d.localizedDescription || d.localizedFailureReason || d.userInfo) {
                  if (errMsg === null) {
                    var codeStr = (typeof d.code === "number") ? d.code : ""
                    var hint = ""
                    if (codeStr === -1004) hint = "（无法连接服务器：地址不通或端口被拦截）"
                    else if (codeStr === -1009) hint = "（网络不可达：请检查服务器地址/网络）"
                    else if (codeStr === -1200) hint = "（SSL 错误）"
                    else if (codeStr === -1022) hint = "（App Transport Security 禁止明文 HTTP）"
                    errMsg = String(d.localizedDescription || d.localizedFailureReason || d.domain || d.code) + hint
                  }
                  continue
                }
                if (body === null && (d.detail !== undefined || d.stored !== undefined || d.updated !== undefined || d.deleted !== undefined || d.new_cursor !== undefined || d.object_count !== undefined || d.device_id !== undefined)) {
                  body = d
                } else if (fallback === null) fallback = d
              } else if (typeof d === "string") {
                var parsed = null
                try { parsed = JSON.parse(d) } catch (e) { parsed = null }
                if (parsed !== null && typeof parsed === "object") {
                  if (body === null && (parsed.detail !== undefined || parsed.stored !== undefined || parsed.updated !== undefined || parsed.object_count !== undefined || parsed.device_id !== undefined)) body = parsed
                  else if (fallback === null) fallback = parsed
                } else if (body === null) {
                  if (errMsg === null) errMsg = d.slice(0, 200)
                  if (fallback === null) fallback = { raw: d }
                }
              }
            }
            if (body === null && fallback !== null && errMsg === null) {
              // 有未知对象但没有可信载荷：按失败处理并带上原始形态
              var keys = []
              try { for (var k in fallback) keys.push(k) } catch (e) {}
              errMsg = "响应无法识别 (keys: " + keys.slice(0, 8).join(",") + ") " + String(fallback).slice(0, 150)
            }
            if (body === null || body === undefined) {
              reject(errMsg ? ("请求失败: " + errMsg) : "请求失败: 无响应数据")
              return
            }
            var obj = body
            if (typeof body === "string") {
              try { obj = JSON.parse(body) } catch (e) { reject("bad response: " + body.slice(0, 120)); return }
            }
            if (obj && obj.detail) { reject(String(obj.detail)); return }
            resolve(obj)
          } catch (e) {
            reject("bad response: " + e)
          }
        }
      )
    } catch (e) { reject("conn: " + e) }
  })
}

// ---------------------------------------------------------------------------
// Dialogs (UIAlertView bridge; style: 0=default buttons, 2=plain text input)
// ---------------------------------------------------------------------------

function popupButtons(title, message, buttons) {
  return new Promise(function (resolve) {
    UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
      title, message, 0, "Cancel", buttons,
      function (alert, buttonIndex) { resolve(buttonIndex - 1) }
    )
  })
}

function popupInput(title, message) {
  return new Promise(function (resolve) {
    UIAlertView.showWithTitleMessageStyleCancelButtonTitleOtherButtonTitlesTapBlock(
      title, message, 2, "Cancel", ["OK"],
      function (alert, buttonIndex) {
        if (buttonIndex - 1 < 0) { resolve(null); return }
        var text = ""
        try { text = alert.textFieldAtIndex(0).text } catch (e) {}
        resolve(text || "")
      }
    )
  })
}

// ---------------------------------------------------------------------------
// Sync engine
// ---------------------------------------------------------------------------

function isoDate(d) {
  if (!d) return ""
  try {
    if (d instanceof Date) return d.toISOString()
    var s = String(d)
    return s || ""
  } catch (e) { return "" }
}

function noteToObject(note, topic, docTitleByMd5) {
  var flags = topic.flags
  var type = "note"
  if (note.flashcard && note.flashcard > 0) type = "card"
  else if (flags === 2) type = "mindmap_node"

  var links = []
  try {
    if (note.linkedNotes) {
      for (var i = 0; i < note.linkedNotes.length; i++) {
        var l = note.linkedNotes[i]
        if (l && l.noteid) links.push(String(l.noteid))
      }
    }
  } catch (e) {}

  var docTitle = null
  try { if (note.docMd5 && docTitleByMd5[note.docMd5]) docTitle = docTitleByMd5[note.docMd5] } catch (e) {}

  var content = ""
  try { content = note.notesText || note.excerptText || "" } catch (e) {}

  var color = null
  try { if (note.colorIndex !== undefined && note.colorIndex !== null && note.colorIndex < COLOR_NAMES.length) color = COLOR_NAMES[note.colorIndex] } catch (e) {}

  return {
    object_id: String(note.noteId),
    object_type: type,
    title: (note.noteTitle || ""),
    content: content || "",
    excerpt: (note.excerptText || null),
    document_id: (note.docMd5 || null),
    document_title: docTitle,
    page: (note.startPage !== undefined && note.startPage !== null ? Number(note.startPage) : null),
    tags: [],
    links: links,
    color: color,
    created_at: isoDate(note.createDate),
    updated_at: isoDate(note.modifiedDate),
    raw: {}
  }
}

function documentToObject(doc) {
  return {
    object_id: String(doc.docMd5),
    object_type: "document",
    title: doc.docTitle || "(untitled)",
    content: "",
    excerpt: null,
    document_id: String(doc.docMd5),
    document_title: doc.docTitle || null,
    page: null,
    tags: [],
    links: [],
    color: null,
    created_at: "",
    updated_at: "",
    raw: {}
  }
}

function collectAllObjects() {
  var objs = []
  var db = Database.sharedInstance()
  var topics = db.allNotebooks() || []
  for (var i = 0; i < topics.length; i++) {
    var topic = topics[i]
    try {
      var docTitleByMd5 = {}
      if (topic.documents) {
        for (var d = 0; d < topic.documents.length; d++) {
          var doc = topic.documents[d]
          if (doc && doc.docMd5) docTitleByMd5[doc.docMd5] = doc.docTitle
        }
      }
      if (topic.notes) {
        for (var n = 0; n < topic.notes.length; n++) {
          try { objs.push(noteToObject(topic.notes[n], topic, docTitleByMd5)) } catch (e) {}
        }
      }
      if (topic.documents) {
        for (var dd = 0; dd < topic.documents.length; dd++) {
          try { objs.push(documentToObject(topic.documents[dd])) } catch (e) {}
        }
      }
    } catch (e) {}
  }
  return objs
}

var _syncing = false

function syncOnce() {
  var s = loadSettings()
  if (!s.enabled || !s.serverUrl || !s.credential || !s.kbName) {
    return Promise.reject("not configured")
  }
  if (_syncing) return Promise.resolve({ skipped: true })
  _syncing = true
  var objects
  try {
    objects = collectAllObjects()
  } catch (e) {
    _syncing = false
    return Promise.reject("collect failed: " + e)
  }
  if (!objects.length) {
    _syncing = false
    return Promise.resolve({ stored: 0, updated: 0, total: 0 })
  }

  var credParts = String(s.credential).split(":")
  var headers = {
    "Authorization": "MarginNote " + credParts[0] + ":" + credParts.slice(1).join(":"),
    "X-MN4-KB": s.kbName
  }

  var chain = Promise.resolve()
  var totalStored = 0, totalUpdated = 0, lastErr = null
  for (var offset = 0; offset < objects.length; offset += BATCH_SIZE) {
    (function (batch) {
      chain = chain.then(function () {
        return dtFetch(s.serverUrl.replace(/\/+$/, "") + "/api/marginnote4/sync", {
          method: "POST",
          headers: headers,
          json: { cursor: "", objects: batch, deleted_ids: [] }
        }).then(function (res) {
          totalStored += (res && res.stored) || 0
          totalUpdated += (res && res.updated) || 0
        }).catch(function (e) {
          lastErr = lastErr || String(e)
        })
      })
    })(objects.slice(offset, offset + BATCH_SIZE))
  }

  return chain.then(function () {
    _syncing = false
    if (lastErr) return Promise.reject(lastErr)
    var s2 = loadSettings()
    s2.lastStored = totalStored
    s2.lastUpdated = totalUpdated
    s2.lastSyncAt = new Date().toISOString()
    s2.lastError = ""
    saveSettings(s2)
    return { stored: totalStored, updated: totalUpdated, total: objects.length }
  }, function (e) {
    _syncing = false
    var s3 = loadSettings()
    s3.lastError = String(e)
    saveSettings(s3)
    return Promise.reject(e)
  })
}

function heartbeatOnce() {
  var s = loadSettings()
  if (!s.enabled || !s.serverUrl || !s.credential) return Promise.reject("not configured")
  var credParts = String(s.credential).split(":")
  return dtFetch(s.serverUrl.replace(/\/+$/, "") + "/api/marginnote4/heartbeat", {
    method: "POST",
    headers: {
      "Authorization": "MarginNote " + credParts[0] + ":" + credParts.slice(1).join(":"),
      "X-MN4-KB": s.kbName || ""
    }
  })
}

// ---------------------------------------------------------------------------
// Timers (NSTimer-driven loop, one global)
// ---------------------------------------------------------------------------

var _timerStop = true
var _timerLooping = false

function delay(sec) {
  return new Promise(function (resolve) {
    NSTimer.scheduledTimerWithTimeInterval(sec, false, resolve)
  })
}

function timerLoop() {
  if (_timerStop) { _timerLooping = false; return }
  syncOnce().catch(function () {}).then(function () {
    delay(SYNC_INTERVAL_SEC).then(timerLoop)
  })
}

function startTimer() {
  if (!_timerStop || _timerLooping) return
  _timerStop = false
  _timerLooping = true
  syncOnce().catch(function () {}).then(function () {
    delay(SYNC_INTERVAL_SEC).then(timerLoop)
  })
}

function stopTimer() {
  _timerStop = true
}

// ---------------------------------------------------------------------------
// Configure flow
// ---------------------------------------------------------------------------

function configureFlow() {
  var s = loadSettings()
  popupInput("DeepTutor Server URL", "服务器地址，例如 http://<你的服务器IP>:8001")
    .then(function (url) {
      if (url === null || !url.trim()) return null
      var t = { serverUrl: url.trim() }
      return popupInput("Knowledge Base Name", "DeepTutor 知识中心里配对的 MarginNote 库名（必须完全一致，如 mn4）")
        .then(function (kb) {
          if (kb === null) return null
          t.kbName = kb.trim()
          return popupInput("Device ID : Token", "在 DeepTutor 的 Devices 页点 Pair 得到的一次性凭据（完整粘贴，含冒号）")
            .then(function (cred) {
              if (cred === null) return null
              t.credential = cred.trim()
              return t
            })
        })
    })
    .then(function (cfg) {
      if (!cfg) { hud("已取消"); return }
      if (!cfg.credential || cfg.credential.split(":").length < 2) {
        hud("凭据格式不对：需要 device_id:token")
        return
      }
      var s = loadSettings()
      s.serverUrl = cfg.serverUrl
      s.kbName = cfg.kbName
      s.credential = cfg.credential
      s.enabled = true
      saveSettings(s)
      hud("已保存，测试连接…")
      heartbeatOnce().then(function (res) {
        hud("连接成功 (对象数 " + ((res && res.object_count) || 0) + ")")
        startTimer()
      }).catch(function (e) {
        // 保留配置（不再回滚成未配置），只记录错误；同步会在 scene 连接时自动重试
        var s2 = loadSettings()
        s2.lastError = String(e)
        saveSettings(s2)
        hud("连接失败: " + e)
      })
    })
}

// ---------------------------------------------------------------------------
// Addon entry (MN4 contract)
// ---------------------------------------------------------------------------

JSB.newAddon = function () {
  return JSB.defineClass("DeepTutorSync : JSExtension",
    {
      sceneWillConnect: function () {
        self.status = false
        try { self.app = Application.sharedInstance() } catch (e) {}
        try { self.studyController = self.app.studyController(self.window) } catch (e) {}
        var s = loadSettings()
        if (s.enabled && s.serverUrl && s.credential) startTimer()
      },

      sceneDidDisconnect: function () {
        stopTimer()
      },

      queryAddonCommandStatus: function () {
        try {
          if (self.studyController.studyMode === 3) return null
        } catch (e) {}
        return {
          image: "logo_44x44.png",
          object: self,
          selector: "onToggle:",
          checked: self.status
        }
      },

      onToggle: function () {
        var s = loadSettings()
        var statusLine = s.enabled
          ? ("已配置: " + s.serverUrl + " / " + s.kbName
             + (s.lastSyncAt ? ("\n上次同步 " + s.lastSyncAt + " +" + s.lastStored + " ~" + s.lastUpdated) : "")
             + (s.lastError ? ("\n错误: " + s.lastError) : ""))
          : "尚未配置"
        popupButtons("DeepTutor Sync", statusLine,
          ["Configure / 配置", "Sync Now / 立即同步", "Disable / 停用", "Reset / 重置"])
          .then(function (idx) {
            if (idx === 0) { configureFlow() }
            else if (idx === 1) {
              var s2 = loadSettings()
              if (!s2.enabled) { hud("尚未配置，请先 Configure"); return }
              hud("同步中…")
              syncOnce().then(function (r) {
                hud("同步完成 +" + r.stored + " ~" + r.updated + " / " + r.total)
              }).catch(function (e) {
                hud("同步失败: " + e)
              })
            }
            else if (idx === 2) {
              var s3 = loadSettings()
              s3.enabled = false
              saveSettings(s3)
              stopTimer()
              hud("已停用")
            }
            else if (idx === 3) {
              popupButtons("确认重置？", "将清空全部配置", ["确认重置"])
                .then(function (c) {
                  if (c === 0) {
                    saveSettings(defaultSettings())
                    stopTimer()
                    hud("已重置")
                  }
                })
            }
          })
      }
    },
    {
      addonDidConnect: function () {
        var s = loadSettings()
        if (!s.enabled && !s.prompted) {
          s.prompted = true
          saveSettings(s)
          configureFlow()
        }
      }
    }
  )
}

} catch (e) {
  try { Application.sharedInstance().alert("DeepTutor Sync: " + String(e)) } catch (e2) {}
}
})();
