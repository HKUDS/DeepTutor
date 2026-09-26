# DeepTutor Desktop（Tauri v2）

桌面外壳负责三件事：把 Python launcher 拉起来并守护它、等它的就绪握手、把窗口交给本地
Next.js 服务；外加原生菜单、托盘、单实例、窗口状态与错误弹窗。业务逻辑（端口、设置、
前端构建、更新交接）全部留在 `deeptutor/runtime/launcher.py`，所以 Web 与 CLI 模式不受影响。

完整方案见 [`../docs-for-user/DESKTOP_TAURI_PLAN.md`](../docs-for-user/DESKTOP_TAURI_PLAN.md)；
分阶段验证记录见 [`PHASE0_REPORT.md`](PHASE0_REPORT.md)、
[`PHASE1_REPORT.md`](PHASE1_REPORT.md)、[`PHASE2_REPORT.md`](PHASE2_REPORT.md) 与
[`PHASE3_REPORT.md`](PHASE3_REPORT.md)、[`PHASE4_REPORT.md`](PHASE4_REPORT.md)。

## 结构

| 路径 | 作用 |
| --- | --- |
| `Cargo.toml` | workspace 根（一个 lockfile、一个 target 目录） |
| `src-tauri/src/main.rs` | 进程入口、插件装配、`--self-check` 冒烟模式 |
| `src-tauri/src/app.rs` | 菜单栏、托盘与它们的动作 |
| `src-tauri/src/window.rs` | 主窗口（代码创建）：外链外开、下载落盘、关闭 Tauri 拖放处理器 |
| `src-tauri/src/supervisor.rs` | 拉起/守护/重启 Python launcher、就绪握手、首启闸门、退出清理 |
| `src-tauri/src/settings.rs` | `desktop/shell.json`（偏好）+ `desktop/bootstrap.json`（数据目录指针） |
| `src-tauri/src/deeplink.rs` | `deeptutor://` / 文件路径 → 路由或文件的分类（含拒绝规则） |
| `src-tauri/src/handoff.rs` | 深链 / 文件关联 / Dock 拖放的待投递队列 |
| `src-tauri/src/notify.rs` | 通知目标记账（一次通知只把用户带回一次） |
| `src-tauri/src/runtime_info.rs` | 读取 launcher 的 `--runtime-info` 状态文件 |
| `plugins/tauri-plugin-deeptutor/` | 外壳命令（供 UI 调用）+ permission set |
| `src-tauri/capabilities/` | `main.json`（本窗口）+ `remote-web.json`（本地 UI 的 IPC 授权） |
| `web/` | splash 页面（内嵌，不需要 Node 构建） |
| `scripts/phase0_*.sh` | 不依赖 Tauri 的握手 / 孤儿守卫验证脚本 |
| `pack/` | 运行时包：`runtime.lock.txt`、`build_pack.py`、`assemble_catalog.py` |
| `scripts/sync_version.py` | 版本同步与 `--check` 守卫 |
| `scripts/assemble_updater_manifest.py` | 逐平台合并 Tauri 的 `latest.json`（含签名结构校验） |
| `pack/build_delta.py` | 两个 pack 树求差 → 增量包 + 目录片段（Phase 4） |
| `RELEASE_SIGNING.md` | 发布密钥清单、缺失时的降级行为、本地演练与自检命令 |

## 运行时包（Phase 2）

包 = 自带 CPython + 内含 DeepTutor 的可重定位 venv + Node + 前端产物。装好之后用户机器上
**不需要任何 Python/Node/环境变量**。

```bash
# 构建（必须在目标平台上跑；CI 用 macos-14 / macos-13 / windows-2022 矩阵）
python3 desktop/pack/build_pack.py                 # 产出 dist/*.tar.gz + .sha256 + .catalog.json
python3 desktop/pack/assemble_catalog.py           # 合并成 runtime-packs.json

# 安装 / 查看 / 更新 / 回滚（无头，不需要开窗口）
deeptutor-desktop --install-pack dist/1.6.10-macos-aarch64.tar.gz --sha256 <digest>
deeptutor-desktop --pack-status
deeptutor-desktop --pack-catalog https://…/runtime-packs.json
deeptutor-desktop --update-pack --catalog https://…/runtime-packs.json
deeptutor-desktop --rollback-pack
```

装好的包放在 `<home>/runtimes/<pack_id>/`，当前使用与上一个包记录在
`<home>/desktop/state.json`；解释器候选链里**运行时包排在 app-data venv 之前**（显式
`DEEPTUTOR_DESKTOP_PYTHON` 仍然优先）。

安装时会做四件事：校验 sha256（不匹配直接拒绝，不落盘）→ 安全解包（拒绝绝对路径与 `..`）
→ rehydrate（把 venv 里指向构建机的绝对路径改成这台机器的）→ 冒烟（`import deeptutor_cli.main,
deeptutor_web`）。

## 为什么外壳命令是"插件"

UI 由 loopback 上的 Next 服务提供，相对 Tauri 属于**远程源**。Phase 0 实测：

```
core-app-ok=1.6.10 ; app-cmd-error=desktop_probe not allowed. Plugin not found
```

- core / 插件命令可以从 loopback 页面调用（`http://127.0.0.1:*` 通配授权有效）；
- **应用自定义命令（`generate_handler!`）不带 ACL 条目，远程源无法调用**。

所以 `plugin:deeptutor|desktop_status`、`plugin:deeptutor|restart_service` 都在
`plugins/tauri-plugin-deeptutor` 里，并在 capability 中授予 `deeptutor:default`。
需要被 UI 调用的新能力，继续往这个插件里加，不要再加应用命令。

## 构建与运行

```bash
# 只检查外壳本身
cd desktop
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo build --locked

# 冒烟：解析运行时目录并打印，不开窗口、不起 launcher
./target/debug/deeptutor-desktop --self-check

# Phase 3 无头流：首启状态 / 代答向导 / 偏好 / 只读更新检查
./target/debug/deeptutor-desktop --first-run-status
./target/debug/deeptutor-desktop --complete-first-run --locale zh-CN \
    [--data-dir DIR] [--no-close-to-tray] [--no-notifications]
./target/debug/deeptutor-desktop --shell-settings
./target/debug/deeptutor-desktop --check-updates [--catalog <url|path>]

# Phase 4：增量运行时更新（先由 build_delta.py 产出增量包）
./target/debug/deeptutor-desktop --apply-delta <file|url> [--sha256 …]
./target/debug/deeptutor-desktop --pack-fingerprint <dir> [--stale-root <path>]…

# 外壳更新通道（Phase 2 收尾）：下载验签 / 真装
./target/debug/deeptutor-desktop --verify-shell-update
./target/debug/deeptutor-desktop --install-shell-update

# 真正跑起来（Phase 1 直接指向源码 checkout）
export DEEPTUTOR_HOME="$HOME/Library/Application Support/DeepTutor"
export DEEPTUTOR_DESKTOP_WORKDIR="/path/to/DeepTutor"
export DEEPTUTOR_DESKTOP_PYTHON="/path/to/DeepTutor/.venv/bin/python"
./target/debug/deeptutor-desktop

# 诊断：把 loopback 页面的 IPC 自检跑一遍（默认关闭，只读、不重启服务）
./target/debug/deeptutor-desktop --remote-ipc-probe
```

`--check-updates` 只报告"有没有新版本"，**不下载、不安装、不重启服务**；要真的装用
`--update-pack --catalog …`。第一次启动会先出现向导（语言、数据目录、关窗行为、通知），
答案落在 `<home>/desktop/shell.json`；选了别的数据目录时，指针写在**平台默认位置**的
`desktop/bootstrap.json` 里，重启后生效。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPTUTOR_HOME` | macOS `~/Library/Application Support/DeepTutor` | 运行时目录（`data/`、`desktop/`） |
| `DEEPTUTOR_DESKTOP_WORKDIR` | 同 `DEEPTUTOR_HOME` | launcher 的工作目录；Phase 1 指向仓库根 |
| `DEEPTUTOR_DESKTOP_PYTHON` | 见下节 | 显式指定 launcher 解释器 |

## 解释器与运行环境

外壳按顺序尝试这些解释器，并**逐个用 `import deeptutor_cli.main` 实测**，取第一个真的能用的：

1. `DEEPTUTOR_DESKTOP_PYTHON`（显式覆盖）
2. `<home>/.venv/bin/python`（Phase 2 运行时包的位置）
3. `<workdir>/.venv/bin/python`（开发时仓库里的虚拟环境）
4. `PATH` 上的 `python3` / `python`

所以从仓库开发时，**只要设 `DEEPTUTOR_DESKTOP_WORKDIR` 就够了**：

```bash
DEEPTUTOR_DESKTOP_WORKDIR=/path/to/DeepTutor ./desktop/target/debug/deeptutor-desktop
```

一个候选都没有通过时，外壳不会只说"退出码 1"，而是把每个候选的失败原因和三种修复方式写进日志、
splash 与原生错误弹窗；launcher 启动失败时还会附上 `launcher.log` 的最后几行。

排查入口：

```bash
./target/debug/deeptutor-desktop --self-check                  # 打印解析结果，始终 exit 0
./target/debug/deeptutor-desktop --self-check --require-python  # 没解析到可用环境就 exit 1
```

外壳传给 launcher 的参数（全部是 Phase 0 落地的可选加法）：

```bash
python -m deeptutor_cli.main start \
  --home <home> --no-browser --auto-ports \
  --runtime-info <home>/desktop/runtime.json \
  --parent-pid <shell pid>
```

`DEEPTUTOR_DESKTOP_SHELL=1` 由外壳设置，让 `detect_installation()` 返回 `desktop` 模式从而
禁用 pip 自更新（签名过的应用包不能自我改写）。

## 已实现的桌面能力（Phase 1）

- **菜单栏**：DeepTutor / 编辑（⌘C/⌘V 在 WebView 内生效）/ 视图（重新加载、全屏、调试版
  开发者工具）/ 窗口 / 帮助；含"设置 ⌘,、重新启动本地服务、打开日志目录、使用文档"。
- **托盘**：显示主窗口、重新启动本地服务、打开日志目录、退出；左键点击唤回窗口。
- **单实例**：第二次启动只聚焦已有窗口。
- **窗口状态**：尺寸/位置由 `tauri-plugin-window-state` 记忆。
- **失败可见**：启动失败写 `desktop/logs/shell.log` + splash 红字 + 原生错误弹窗，并先收摊
  子进程，绝不留下半启动的 backend/frontend。
- **崩溃自愈**：launcher 异常退出时按 2s/4s/8s 退避自动重启，最多 3 次；手动重启不会被
  计成崩溃（generation 先退休旧线程再杀进程）。

## 已实现的桌面能力（Phase 3）

- **关窗策略**：默认关闭窗口=隐藏到托盘（服务与长任务继续跑），可在菜单栏勾选项或
  `/settings/desktop` 改成"关窗即退出"。窗口只隐藏不销毁，否则托盘无法把它叫回来。
- **系统通知**：回合在**后台**完成时才发（标题=会话名，正文=回答开头，目标=`/chat/<id>`）。
  点击通知/Dock 唤醒后由外壳投递目标，一次通知只投递一次。
- **深链与文件关联**：`deeptutor://` 方案 + PDF/EPUB/MD 文件关联（需打包版才注册）；
  拖到 Dock 图标、`open -a`、"打开方式"共用一条 hand-off 队列，冷启动时也不会丢。
- **原生文件**：`pick_files` / `pick_folder` 原生对话框；文件 hand-off 由外壳读字节交给
  前端现有的上传链路；导出固定落 `~/Downloads`（重名自动加序号），可"在文件夹中显示"。
- **首启向导**：语言、数据目录、关窗行为、通知、模型/密钥交接，跑在 splash（app origin）。
- **设置页**：`/settings/desktop` 在桌面外壳里是真实开关，在浏览器里降级为说明页。
- **只读更新检查**：菜单/托盘/设置页的"检查更新"读运行时包清单并报告可用版本；外壳自更新
  通道未配置时会明说，而不是假装"已是最新"。

## 两层更新（Phase 2 收尾）

| 平面 | 装的是什么 | 谁在管 | 入口 |
| --- | --- | --- | --- |
| 运行时包 | Python、Node、前端产物 | 外壳自己（`runtime_pack.rs`） | 清单 `runtime-packs.json`；`--update-pack` / `--rollback-pack` |
| 外壳 | 这个窗口、菜单与原生插件 | `tauri-plugin-updater`（公钥在 `tauri.conf.json`） | 通道 `latest.json`；菜单/设置页 → 下载 → 验签 → 安装 → 重启 |

检查一次就会同时回答两条通道（`check_updates` / `--check-updates`）：外壳更新的签名在下载时
校验，验签失败绝不进入安装步骤。发布密钥、"缺密钥会怎样"、以及本地演练命令见
[`RELEASE_SIGNING.md`](RELEASE_SIGNING.md)。

### 信任边界：窗口是 loopback 页面

UI 由 `127.0.0.1` 上的 Next 服务提供，对 Tauri 来说属于**远程源**——窗口里任何脚本都能调用
`deeptutor:default` 里的命令。因此运行时的规矩是：

- **更新源不由窗口决定**：`update_shell_settings` 会拒绝 `pack_catalog`（"检查更新"按钮也只会
  读取快照），更新源只能写在 `desktop/shell.json` 或 `DEEPTUTOR_DESKTOP_PACK_CATALOG` 里，
  而且不接受 `http://`（明文清单 = 中间人换包）；本地路径仍然允许。
- **清单要验签**：外壳平面与运行时平面共用 `plugins.updater.pubkey` 这把 minisign 密钥。
  配了公钥（默认就有）就**必须**有合法签名，否则清单被拒；签名缺失/不匹配/清单被改都会 fail
  closed，错误信息会列出找过的 `<catalog>.sig` / `<catalog>.minisig`。密钥的生成、发布侧签名、
  以及不配公钥时的降级行为见 [`RELEASE_SIGNING.md`](RELEASE_SIGNING.md) §6。
- **检查 ≠ 安装**：`check_updates` 默认只读；`check_updates { install: true }` 也要先弹原生确认框
  （`Supervisor::confirm_and_install_runtime_update`），点"稍后"就什么都不做。菜单栏的
  "检查更新 …" 走同一条路径。
- **读本地文件要凭据**：`read_local_file` 只接受外壳移交过的路径（Dock 拖放、文件关联、"打开方式"）
  或用户在原生选择器里挑过的文件；凭据由 `handoff::OpenQueue` 发放、读一次消耗一次，不再接受
  任意绝对路径。
- **包内容是敌意输入**：`manifest.json` 的 `pack_id` 必须是单个目录名，`paths.*` 必须是包内相对
  路径（`Path::join` 遇到绝对路径会替换前缀，未校验时等于任意目录删除/替换）；`rehydrate` 不跟随
  符号链接，写入一律走"临时文件 + rename"，所以硬链接克隆体永远不会把改写带回基线包。
- **窗口只认自己的那个 loopback 端口**：`window.rs` 用 launcher 报告的端口判断"是不是我们的
  界面"，`127.0.0.1:3782` 与 `localhost:3782` 等价、其它端口（含"还不知道端口"）一律交给系统
  浏览器，不再把整个 loopback 当自己人。capability 也只授 UI 真正会调的 15 个命令
  （向导用的 `first_run_state`/`apply_first_run`/`pick_folder` 与没有调用方的 `pick_files`
  只在 app 原点的 `deeptutor:default` 里）。
- **自检不在生产路径上**：`verify_remote_ipc` 只在 `--remote-ipc-probe`/`DEEPTUTOR_DESKTOP_PROBE=1`
  时运行，而且只读——它早前会在第一轮调用 `restart_service`，等于每次启动都把本地服务弹一次。
- **外壳自己也说用户的语言**：状态行、失败原因、原生对话框、菜单栏/托盘、以及设置页原样打印的
  `detail` 行都由 `strings.rs` 的 `tr(locale, "中文", "English")` 产出；语言取自
  `shell.json` 的 `locale`（向导里选的），空值回落到系统语言。网页端启动时会把 i18n 的语言推给
  外壳（`updateShellSettings({locale})`，两边一致时**不写**），并在切换语言时重建菜单栏与托盘菜单。

## 增量运行时更新（Phase 4）

完整包 257MB 里绝大多数内容（CPython、Node、几乎全部 wheel）在两个版本之间是逐字节相同的，
所以"更新"只需要传变掉的那一点：

```bash
# 1. 对着上一版的 staged 树生成增量（CI 里对着上一个 release 的包做同样的事）
python3 desktop/pack/build_delta.py \
    --base   desktop/pack/dist/stage-1.6.10-macos-aarch64 \
    --target desktop/pack/dist/stage-1.6.11-macos-aarch64
# → 1.6.11-macos-aarch64.delta.tar.gz（实测 2.2MB）+ .delta.catalog.json

# 2. assemble_catalog.py 会把 delta 挂到对应 pack 条目上（URL/sha256/size）

# 3. 外壳侧：目录里基线匹配时自动走增量，否则回退完整包
deeptutor-desktop --update-pack --catalog <url|path>
# 也可以直接应用一个增量文件：
deeptutor-desktop --apply-delta <file> --sha256 <digest>
```

安全边界（详见 [`PHASE4_REPORT.md`](PHASE4_REPORT.md)）：

- 增量只对**一个精确基线**有效（pack_id + 文件数 + 归一化树指纹，跨"安装时被 rehydrate 改写过的
  路径"也能对上）；基线不对 → 拒绝 → 自动回退完整包；
- 每个增量文件在放入前按 **原始字节** 校验 sha256；应用后再算一次目标指纹；
- 基线用硬链接克隆，而且**只往克隆体写**：`rehydrate` 的每次写入都是"临时文件 + rename"，
  换掉目录项而不是原地改 inode（原地写会穿过硬链接改到基线包；`pack_tree` 的注释里
  有这条不变量的说明，`runtime_pack` 的测试钉住了它）。失败只影响暂存目录，活动包与
  `previous_pack` 都不动；
- **装好的包是自述的**：venv 之外的残留构建根（CPython 树、wheel 元数据、软链目标）在安装时会被
  规范化成包自己的目录（`canonicalise`），否则下一个增量的基线指纹永远对不上——`stale_roots`
  只认识"上一版的构建根"，而一份增量装出来的包会一直带着**更早那次完整包**的路径，于是每隔一版
  就被静默退回完整包。三跳链路（完整装 A → 增量到 B → 增量到 C）和
  `an_installed_pack_fingerprints_as_its_staged_self` 都钉住了这条；
- 目录里同时保留完整包：任何"增量不可用"的情况都不会让用户卡住；
- **下载是有界且会打扫的**：清单里声明的 `size` 会在流式下载时逐步核对（超过即中止），另有
  2 GiB 硬上限与超时；被拒绝的归档、失败的下载、以及崩溃留下的 `.incoming-*`/`.delta-incoming-*`
  都会被清掉，不会在 `runtimes/` 里越积越多；
- **版本比较认 SemVer 优先级**：`1.6.11-rc1` 不会盖过 `1.6.11`（早前它会被解析成多一位数字而排在
  正式版之后），`+build` 元数据不参与比较。

## 版本

`src-tauri/Cargo.toml`、`plugins/tauri-plugin-deeptutor/Cargo.toml` 与
`src-tauri/tauri.conf.json` 的 `version` 必须与 `deeptutor/__version__.py` 一致。
Phase 2 的 `desktop/scripts/sync_version.py` 会把它变成自动同步 + 发布守卫，在此之前手工同步。

## CI

`.github/workflows/desktop-ci.yml` 在 `desktop/**` 变更时跑 fmt / clippy / 单测 / 构建 /
`--self-check` 冒烟（macOS arm64）。Python 侧的桌面契约由
`tests/runtime/test_desktop_launcher_contract.py` 通过 `tests.yml` 覆盖。

`.github/workflows/desktop-release.yml` 上有四条容易踩的守卫，改的时候别绕开：

- **tag 必须等于 `__version__.py`**：资产 URL 来自 tag，而清单/包名来自版本文件；两者不一致会造出
  一个 `latest.json` 里版本号等于已安装版本的"隐身发布"。`workflow_dispatch` 在分支上跑时只告警。

- **依赖锁校验**：`uv pip compile` 会把自己的命令行（含 `-o` 路径）写进文件头，所以必须先
  `cp` 一份再**编译回同一个路径**去 `diff`——写到别处既会让头行对不上，也会因为输出文件不存在
  而重新解析整个锁。uv 钉在 0.11.15（0.11.15 之前的版本有"wheel entry point 逃出环境"的
  已公开通告，而这个版本已验证能逐字节复现提交的锁文件），改它等于同时改格式与安全性。
- **外壳产物按平台加前缀**：Tauri 在两个 macOS 架构上都产出 `DeepTutor.app.tar.gz`，而
  `gh release upload` 按 basename 命名资产，不加前缀就会互相覆盖，`latest.json` 里
  `darwin-aarch64` 的签名随即与资产对不上。`assemble_updater_manifest.py` 用 basename 生成
  URL，所以前缀会自动跟着走。
- **增量作业是尽力而为**：`deltas` 失败不应当把整条流水线标红，`catalog` 用
  `needs: [packs, packs-linux, deltas]` + `if: always() && needs.packs.result == 'success'`
  等它、容忍它，但绝不在 `packs` 失败时硬造清单。
- **上游运行时必须先验摘要**：`build_pack.py` 抓 python-build-standalone 与 nodejs.org 时
  会先取它们的 `SHA256SUMS`/`SHASUMS256.txt` 校验（缓存不匹配会重下一遍），解包前还会拒绝
  绝对路径、`..`、越界软链与设备节点；`--full-archive` 必须在 CI 里显式传给
  `build_delta.py`，否则 `--max-ratio` 守卫没有比较对象、只会打一行日志然后放行。
