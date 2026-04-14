# 本地 Conda 环境（可选）

仅当你在本机使用 **Cursor/VSCode** 且希望用**专用 conda 环境**时参考，无需所有人统一这样做。

## 1. 让终端识别 conda

若在 Cursor 终端里出现 `command not found: conda`，多半是集成终端未加载 conda。任选其一：

**方式 A：当前终端临时启用**

```bash
source scripts/activate_conda.sh
```

**方式 B：长期生效**

在 `~/.zshrc` 中保留 conda 初始化块（安装 Miniconda/Anaconda 时通常已添加），然后新开终端即可。

## 2. 创建项目专用环境

```bash
# 先让 conda 可用（若尚未可用）
source scripts/activate_conda.sh

# 一键创建环境并安装依赖（Python 3.12 + Node 20 + 前端）
bash scripts/setup_conda_env.sh
```

环境名为 `deeptutor`。

## 3. 在 Cursor 里使用该环境

- 已通过 **`.vscode/settings.json`** 指定解释器为：  
  `~/miniconda3/envs/deeptutor/bin/python`
- 若你用的是 **Anaconda**，请把该文件中的 `miniconda3` 改为 `anaconda3`。
- 打开 Python 文件时，Cursor 会使用上述解释器；终端里可执行：

  ```bash
  conda activate deeptutor
  python scripts/start_web.py
  ```

或直接：

```bash
bash scripts/run_with_conda.sh
```

## 4. 小结

| 目的           | 操作 |
|----------------|------|
| 终端里能用 conda | `source scripts/activate_conda.sh` 或配置好 `~/.zshrc` |
| 创建/重建环境   | `bash scripts/setup_conda_env.sh` |
| 用指定环境启动  | `bash scripts/run_with_conda.sh` 或 `conda activate deeptutor && python scripts/start_web.py` |
| 编辑器用该环境  | 已由 `.vscode/settings.json` 指定，无需额外操作 |
