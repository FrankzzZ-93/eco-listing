# Eco Listing Agent — 部署指南

本文档面向任何人（含 AI 助手）从零部署本项目。按顺序执行即可，无需额外背景知识。命令均可直接复制粘贴。

---

## 1. 这是什么

一个自动生成亚马逊 Listing 的多 Agent 系统：

- **后端**：Python + FastAPI + LangGraph 编排（竞品抓取 → 属性分析 → 人工审核 → 关键词分类 → 多轮文案生成 → ST 优化 → 导出）。
- **前端**：React + TypeScript + Vite + Ant Design。
- **LLM**：默认通过本机 **Codex CLI**（`codex exec`）调用，用 Codex 本地登录态，**不依赖 `.env` API Key**（文案环节可在配置中心改用 OpenAI 兼容 API）。
- **登录态网页抓取**：竞品评论 / Rufus（Alex）问题用**本机真实 Google Chrome**（Playwright `channel="chrome"` 驱动，免费、过反爬，替换原付费 browser-act）；复杂或兜底场景回退到 Codex 驱动的浏览器。
- **持久化**：SQLite（`checkpoints.db`，**任务列表与状态的唯一真相来源**）+ 本地文件（`artifacts/runs/`）。无需外部数据库，也无独立的任务索引文件。

> 架构要点：前端（:3000）把 `/api`、`/artifacts` 反向代理到后端（:8000）。后端进程内常驻 LangGraph 图与浏览器实例；每个任务的状态由 LangGraph 的 SQLite checkpointer 持久化。

---

## 2. 运行环境要求

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| 操作系统 | **macOS 或 Linux** | 代码使用 POSIX 进程组（`os.setsid`/`killpg`）。Windows 请用 **WSL2**。 |
| Python | **3.9+**（已在 3.9.6 验证） | 后端运行时 |
| Node.js | **18+**（已在 22.x 验证） | 前端构建 + Codex CLI 运行时 |
| npm | 9+ | 随 Node 安装 |
| Codex CLI | **codex-cli 0.13+**（已在 0.134.0 验证） | 实际的 LLM / 浏览器 Agent 后端，**必须登录** |
| **Google Chrome（真实）** | 本机安装 + `playwright install chrome` | **登录态抓取竞品评论 / Rufus 的主引擎**（真实 Chrome，免费、过反爬） |
| Playwright | 随 `pip install -r requirements.txt` | 驱动真实 Chrome；内置 Chromium 作降级 |

### 2.1 安装系统级工具

```bash
# Node.js（推荐用 nvm；任意 18+ 即可）
# macOS: brew install node   或   nvm install 22

# Codex CLI（OpenAI Codex，npm 全局安装）
npm install -g @openai/codex

# 真实 Google Chrome（登录态抓取的主引擎；免费、过反爬）
# macOS: 从官网安装 Google Chrome.app；Linux: apt install google-chrome-stable
# 让 Playwright 能用 channel="chrome" 驱动它：
playwright install chrome

# 验证
node --version          # 应 >= v18
codex --version         # 应输出 codex-cli x.y.z
```

> 登录态抓取改用**本机真实 Google Chrome**（替换原先的付费 `browser-act` 云浏览器）。
> 代码会自动探测常见 Chrome 安装路径。未找到 Chrome 时「内置引擎」
> （Playwright Chromium + Codex）仍可用作降级。

### 2.2 登录 Codex（关键步骤，否则所有生成都会失败）

LLM 调用与浏览器自动化都走 `codex exec`，使用 Codex 的本地登录态（存于 `~/.codex/auth.json`）。

```bash
codex login
# 按提示完成浏览器授权；完成后确认：
ls ~/.codex/auth.json   # 存在即表示已登录
```

> 如果跳过这一步，任务会在"竞品抓取/文案生成"阶段报 `CodexExecError`。

### 2.3 （可选）Listing 文案撰写使用其他模型

默认所有 LLM 调用都走 Codex CLI。如需让 **Listing 文案撰写** 环节改用 Opus / Claude 等模型，可在前端顶部「模型设置」中切换为「OpenAI 兼容 API」，并填写：

- **Base URL（request path）**：中转站/服务的接口地址，填到根地址或 `/v1` 即可（会自动补全为 `/v1/chat/completions`）。
- **Model**：模型 ID（由服务商决定，如 `claude-opus-4-20250514`）。
- **API Key**：中转站或服务商提供的密钥。

保存前可点「测试连接」校验配置。该设置仅作用于文案撰写环节，其他步骤仍使用 codex-cli；配置持久化在项目根目录 `llm_settings.json`（含密钥，已在 `.gitignore` 中忽略，请勿入库）。不配置则保持默认 codex-cli 行为。

### 2.4 账号登录与抓取设置（统一配置入口）

前端顶部「配置中心」是账号登录、抓取参数、文案模型的统一入口：

- **账号与登录（手动登录，系统不碰你的密码）**：点「打开浏览器登录」会弹出一个**真实 Chrome 窗口**，你在窗口里**自行登录** Amazon（含验证码 / 二次验证），完成后点「我已登录」。系统只检测登录是否成功——Amazon 会拦截脚本化的登录表单，手动登录既最稳又无需后端保存密码。登录态持久化在本机 Chrome 配置目录（`chrome_profile_dir`，默认 `artifacts/_chrome_profile`），后续抓取自动复用；登录态会**跨后端重启记住**（持久化标记），且**刷新页面不会再弹浏览器**（状态轮询只读、不碰浏览器，只有你主动点「打开浏览器登录」才开窗口）。点登录时前端会先弹窗提醒**确认已开美国 VPN**。
- **出口 IP / 地区**：真实 Chrome 走**系统网络出口**。若本机 IP 被 Amazon 按地理位置跳到错误站点（例如澳洲 IP 访问 `amazon.com` 会被跳到 `amazon.com.au`，美国站账号无法识别），请在**系统层挂对应地区的 VPN**（如美国）。配置中心的「出口 IP / 地区」字段暂作记录，不直接驱动代理。
- **遇到验证码**：登录时直接在那个真实 Chrome 窗口里完成即可（你看得见）。抓取过程中若被拦，系统会截图并暂停，你在窗口里处理后重试。
- **抓取设置**：可选「评论抓取引擎」（**真实 Chrome 登录态** / 内置 Playwright+Codex 降级），以及评论页数、并发数、Codex 超时等。

> 说明 1：Amazon **评论深度页（`/product-reviews/`）强制登录**；商品页的 **Rufus AI 助手（「Looking for specific info?」组件，项目内沿用旧称 Alex）建议问题**通常需登录态才稳定出现。系统抓取的是该组件里 AI 生成的「建议提问」列表（用于反推优化 listing）。
>
> 说明 2：**Amazon 近期大幅收紧评论抓取**——`/product-reviews/` 现常只返回 ~8 条、且忽略星级筛选与翻页参数，商品详情页约 13 条。因此单个 ASIN 实际可抓评论上限约 **10–15 条**（与登录与否、账号 cohort 有关），这是平台限制，与抓取工具无关。
>
> 说明 3：**抓取证据截图自动留存**——抓评论/Alex 时引擎会把评论页、Rufus 组件截图存到 `artifacts/runs/{run_id}/`（`reviews_*.png` / `alex_*.png`），经 `/artifacts/...` 静态服务。可在任务详情**点左侧「竞品评论」/「Alex 问答」**打开数据抽屉，顶部即按 ASIN 展示对应截图（点击放大）供查验；「运行状态」tab 底部也有全部截图的总画廊。仅**新引擎跑的任务**有截图。

该配置持久化在项目根目录 `app_settings.json`（已在 `.gitignore` 中忽略，请勿入库）。

### 2.5 Windows 部署（真实 Chrome 引擎）

后端用到 POSIX 进程组（**仅 `app/tools/codex_exec.py` 一处**），所以 Windows 上**经 WSL2** 运行。**记录登录态有两种方式，推荐方式 A**（无需在 WSL2 里装 Chrome、也无需显示）。

#### 方式 A（推荐）：连接 Windows 侧的 Chrome（CDP）

Chrome 跑在 **Windows**（原生、可见，你在里面登录），WSL2 后端通过 CDP 连上去驱动；登录态记在 Windows 那个 Chrome 的 profile 里。

1. 在 **Windows** 起一个带调试端口的专用 Chrome（建议做成快捷方式）：
   ```bat
   "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
     --remote-debugging-port=9222 --user-data-dir=C:\eco-chrome-profile ^
     https://www.amazon.com/
   ```
2. 在该窗口里**手动登录 Amazon**（开着美国 VPN）。
3. 让 WSL2 能连到它（Chrome 默认只绑 `127.0.0.1`，做个端口转发）。Windows 管理员 PowerShell：
   ```powershell
   netsh interface portproxy add v4tov4 listenport=9223 listenaddress=0.0.0.0 connectport=9222 connectaddress=127.0.0.1
   ```
4. WSL2 后端设 CDP 地址（写进 `.env`）：
   ```bash
   # 宿主 IP = /etc/resolv.conf 里的 nameserver
   echo "CHROME_CDP_URL=http://$(grep nameserver /etc/resolv.conf | awk '{print $2}'):9223" >> .env
   ```
   设了它，引擎就**连接**已运行的 Chrome 而不是自己启动。**WSL2 侧无需装 Chrome**，`playwright`（已随 `requirements.txt` 安装）即可。

#### 方式 B：在 WSL2 里直接起 Linux Chrome（需要可显示窗口）

1. **装 Linux 版 Chrome**（WSL2 后端启动的是它，不是 Windows 那个）：
   ```bash
   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   sudo apt install ./google-chrome-stable_current_amd64.deb
   playwright install chrome          # 让 channel="chrome" 找到它
   playwright install-deps chromium   # 补齐 Chrome 依赖的系统库
   ```
2. **可见窗口**：**Win11 自带 WSLg**（零配置，窗口直接显示在桌面）✅；**Win10** 需装 X server（VcXsrv）并 `export DISPLAY=:0`。

> 引擎按平台自适应：**Linux/WSL2 自动加 `--no-sandbox` / `--disable-dev-shm-usage`**（WSL2 起 Chrome 必需），**macOS 保留沙箱**——同一份代码两边都能跑，无需手动配置。

#### 通用说明

- **VPN**：WSL2 走 Windows 宿主网络。在 **Windows 上挂全局美国 VPN** 即可覆盖出口；否则会被 Amazon 跳到错误站点。**前端「打开浏览器登录」时会弹窗提醒先开美国 VPN。**
- `chrome_session.chrome_available()` 已内置 Windows / WSL2 的 Chrome 路径探测。

> **更干净的选择：原生 Windows（不用 WSL2）。** 唯一的 POSIX 依赖是 `codex_exec.py` 里对子进程组的 SIGKILL。改成跨平台写法（Windows 用 `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F`）后，后端可直接在 Windows 跑，Playwright 直接驱动 Windows 版 Chrome——有头窗口原生可用、不依赖 WSLg/CDP 转发。改动集中在一个文件。

---

## 3. 部署后端

在项目根目录（含 `requirements.txt` 的目录）执行：

```bash
# 1) 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate        # Windows(WSL) 同样用这条

# 2) 安装 Python 依赖
pip install --upgrade pip
pip install -r requirements.txt

# 3) 安装 Playwright 浏览器：真实 Chrome（登录态主引擎）+ Chromium（降级）
playwright install chrome
playwright install chromium

# 4) 准备配置文件
cp .env.example .env
# 按需编辑 .env（见第 5 节；默认值即可直接跑）
```

启动后端：

```bash
# 开发模式（带热重载，推荐）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 或不带热重载
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动成功标志：日志出现 `Application startup complete.` 与 `Uvicorn running on http://0.0.0.0:8000`。

验证后端：

```bash
curl -s http://localhost:8000/api/runs    # 应返回 JSON 数组（初始为 [] 或已有任务）
```

---

## 4. 部署前端

新开一个终端，进入 `web/` 目录：

```bash
cd web
npm install              # 首次安装依赖
npm run dev              # 启动 Vite 开发服务器（端口 3000）
```

启动成功标志：输出 `VITE vX ready` 与 `Local: http://localhost:3000/`。

打开浏览器访问：**http://localhost:3000/**

> 前端已通过 `web/vite.config.ts` 把 `/api` 和 `/artifacts` 代理到 `http://localhost:8000`，因此**前端无需配置后端地址**，只要后端在 :8000 上即可。

### 4.1（可选）生产构建

```bash
cd web
npm run build            # 产物在 web/dist
npm run preview          # 本地预览生产包
```

> 注意：`npm run preview` 默认也依赖 :8000 的代理。若要纯静态部署（如 Nginx），需自行把 `/api`、`/artifacts` 反代到后端，本项目默认按"前后端同机 + Vite 代理"运行。

---

## 5. 配置参考（`.env`）

所有配置项均有合理默认值，**不改也能跑**。通过环境变量或 `.env` 覆盖（见 `app/config.py`）。

| 变量 | 默认值 | 含义 |
|---|---|---|
| `CODEX_TIMEOUT` | `600` | 单次 `codex exec` 子进程超时（秒）。关键词分类等长任务需要较大值。 |
| `ST_MAX_BYTES` | `249` | Search Terms 字节上限（亚马逊后台限制）。 |
| `ARTIFACTS_DIR` | `artifacts/runs` | 产物输出目录。 |
| `CHROME_PROFILE_DIR` | `artifacts/_chrome_profile` | 真实 Chrome 登录态持久化目录（启动模式用）。 |
| `CHROME_CDP_URL` | 空 | 设了则**连接**外部已运行的 Chrome（如 WSL2 连 Windows 侧，见 §2.5 方式 A）；留空则本地启动 Chrome。 |
| `CHECKPOINT_DB` | `checkpoints.db` | LangGraph SQLite 持久化文件。 |
| `HOST` | `0.0.0.0` | 后端监听地址。 |
| `PORT` | `8000` | 后端端口。 |
| `GEMINI_API_KEY` / `CLAUDE_API_KEY` / `OPENAI_API_KEY` | 空 | **当前运行时不使用**（LLM 走 Codex CLI 登录态）。保留为兼容字段，可留空。 |
| `LLM_RETRY_MAX` | `3` | LLM 重试次数。 |

### 5.1 Listing 字数限制（代码内默认，可在 `app/config.py` 调整）

这些是按 run 注入的硬上限/软下限，由文案生成的合规循环强制执行：

| 项 | 硬上限 | 软下限 |
|---|---|---|
| 标题 Title | 200 字符 | 120 字符 |
| 五点 Bullets（合计） | 1000 字节 | 700 字节 |
| 描述 Description | 2000 字符 | 1500 字符 |
| Search Terms | 249 字节 | — |

> 软下限不会阻塞任务（重试 `COPYWRITER_MAX_RETRIES=5` 次后仍输出最后稿），只用于"鼓励内容更饱满"。

---

## 6. 验证部署成功

1. 后端 :8000 与前端 :3000 均已启动。
2. 浏览器打开 http://localhost:3000/，能看到"Eco Listing 生成器"输入页。
3. 填入 1 个竞品 ASIN（如 `B099DW9MYJ`）、上传关键词词库（`.xlsx`/`.json`），点击"开始生成"。
4. 任务进入"竞品数据采集"阶段说明 Codex/Playwright 链路正常。

---

## 7. 公网访问（可选）

用 Cloudflare Tunnel 把本地前端临时暴露到公网：

```bash
# 安装 cloudflared（macOS: brew install cloudflared）
# 前端以隧道模式启动（修正 HMR websocket）：
cd web
PUBLIC_TUNNEL=1 npm run dev

# 另开终端起隧道，指向前端端口
cloudflared tunnel --url http://localhost:3000
# 输出的 https://xxxx.trycloudflare.com 即为公网地址
```

> `vite.config.ts` 已设置 `allowedHosts: true` 接受任意 Host，并在 `PUBLIC_TUNNEL=1` 时把 HMR 指向 `wss://...:443`。

---

## 8. 目录结构速览

```
eco_listing/
├── app/                    # 后端
│   ├── main.py             # FastAPI 入口（lifespan 装配图/工具/恢复任务）
│   ├── config.py           # 配置（Settings）
│   ├── api/routes.py       # REST API（创建/启动任务、上传、审核、产出）
│   ├── agents/             # 各 Agent + orchestrator（LangGraph 图）
│   ├── tools/              # codex_exec / llm / browser / keyword / compliance ...
│   └── memory/             # ListingState 与共享内存
├── prompts/                # 各 Agent 的提示词（可热改，支持 override）
├── web/                    # 前端（Vite + React）
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板
├── checkpoints.db          # 运行后生成：LangGraph 持久化（任务列表的唯一来源）
└── artifacts/runs/         # 运行后生成：各任务产物
```

---

## 9. 常见问题（Troubleshooting）

| 现象 | 原因 / 解决 |
|---|---|
| 生成阶段报 `CodexExecError` / `CodexExecTimeout` | 未 `codex login`，或任务过长。先确认 `~/.codex/auth.json` 存在；必要时调大 `CODEX_TIMEOUT`。 |
| 抓取竞品失败 / 找不到浏览器 | 未执行 `playwright install chromium`。 |
| 前端能打开但接口 404/502 | 后端没在 :8000 运行，或端口被占用。确认后端日志，或 `lsof -ti:8000` 查占用。 |
| `python: command not found` | 用 `python3`；并确认已 `source .venv/bin/activate`。 |
| Windows 下进程无法终止/报错 | 代码依赖 POSIX 进程组，请在 **WSL2** 内部署。 |
| 端口 3000/8000 被占用 | 改端口：后端 `--port`，前端在 `vite.config.ts` 改 `server.port`（同时改代理 target）。 |
| 任务上传多个文件后丢失 | 已修复（前端顺序上传 + 后端按 run 加锁）；如自定义客户端，请勿并发上传同一 run。 |

---

## 10. 一键启动清单（已装好依赖后）

```bash
# 终端 A —— 后端
cd /path/to/eco_listing
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 B —— 前端
cd /path/to/eco_listing/web
npm run dev

# 浏览器打开 http://localhost:3000/
```

---

## 11. Windows 部署（必须走 WSL2）

### 11.1 为什么不能在原生 Windows 直接跑

后端在调用 Codex CLI 时依赖 **POSIX 进程组**来可靠地终止子进程树（`app/tools/codex_exec.py`）：

- `start_new_session=True`（= `os.setsid`）—— Windows 无此语义；
- 超时清理调用 `os.killpg(pid, signal.SIGKILL)` —— **Windows 上 `os.killpg` 与 `SIGKILL` 都不存在**，会抛 `AttributeError`。

因此原生 Windows（PowerShell/CMD + Windows 版 Python）在任意 `codex exec` 超时时都会崩溃，且无法干净杀掉 codex 的 node→Rust 子进程。**正确做法是用 WSL2**（Windows 内的真 Linux 环境），下文步骤即在 WSL2 中完成，与第 3、4 节的 Linux 流程一致。

> 不想改代码就用 WSL2（推荐）。若确实要原生 Windows，需要改写 `_kill_process_tree` 与子进程创建逻辑为 Windows 版（`CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F`），属于代码改造，不在本指南范围。

### 11.2 安装并启用 WSL2

以**管理员身份**打开 PowerShell：

```powershell
# 一键安装 WSL2 + Ubuntu（Windows 10 2004+ / Windows 11）
wsl --install -d Ubuntu

# 安装后按提示重启电脑；重启后 Ubuntu 会自动启动并要求创建 Linux 用户名/密码
```

重启后验证（PowerShell）：

```powershell
wsl --status            # 应显示 默认版本: 2
wsl -l -v               # 应看到 Ubuntu 且 VERSION = 2
```

后续所有命令都在 **Ubuntu (WSL) 终端**里执行（开始菜单搜索 "Ubuntu"，或 PowerShell 里输入 `wsl`）。

### 11.3 在 WSL2 (Ubuntu) 内安装依赖

```bash
# 1) 系统更新 + 基础工具
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git build-essential python3 python3-venv python3-pip

# 2) Node.js 18+（用 nvm 装，避免 apt 版本过旧）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install 22
node --version          # 应 >= v18

# 3) Codex CLI
npm install -g @openai/codex
codex --version

# 4) 登录 Codex（会打印一个授权 URL）
codex login
#   - WSL 通常会自动用 Windows 默认浏览器打开该 URL；
#   - 若没自动打开，手动复制终端里的 URL 到 Windows 浏览器完成授权。
ls ~/.codex/auth.json   # 存在即登录成功
```

### 11.4 放置代码并部署（与 Linux 相同）

> **重要**：把项目放在 **WSL 自己的文件系统**（如 `~/eco_listing`），不要放在 `/mnt/c/...`（Windows 盘），否则文件 IO 极慢且可能有权限问题。

```bash
# 克隆或拷贝项目到 WSL home 目录
cd ~
# git clone <repo-url> eco_listing   # 或从 Windows 拷贝：cp -r /mnt/c/路径/eco_listing ~/
cd ~/eco_listing

# 后端依赖
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Playwright：WSL 需要先装系统依赖库，再装浏览器
playwright install-deps chromium     # 需要 sudo 权限时会自动提示
playwright install chromium          # 内置降级引擎

# 登录态抓取主引擎 = 真实 Chrome。在 WSL2 里装 Linux 版 Chrome：
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
playwright install chrome
# 登录窗口怎么显示、或连接 Windows 侧 Chrome 的细节见 §2.5
# （Win11 用 WSLg 直接显示；或用连接模式 CHROME_CDP_URL 连 Windows 上的 Chrome）

# 配置
cp .env.example .env
```

### 11.5 启动（两个 Ubuntu 终端）

```bash
# 终端 A —— 后端
cd ~/eco_listing && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 B —— 前端
cd ~/eco_listing/web && npm install && npm run dev
```

### 11.6 从 Windows 访问

WSL2 会把端口转发到 Windows 的 `localhost`，因此直接在 **Windows 浏览器**打开：

- 前端：**http://localhost:3000/**
- 后端健康检查：http://localhost:8000/api/runs

> 若偶发无法访问 localhost：在 PowerShell 执行 `wsl --shutdown` 后重启 WSL；或用 `wsl hostname -I` 拿到 WSL 的 IP 直接访问 `http://<那个IP>:3000`。

### 11.7 Windows/WSL 专属排错

| 现象 | 解决 |
|---|---|
| `wsl --install` 提示需要更新 | 升级到 Windows 10 2004+ 或 Windows 11；或手动启用"虚拟机平台"和"适用于 Linux 的 Windows 子系统"功能后重试。 |
| Playwright 启动报缺少 `.so` 库 | 在 WSL 内执行 `playwright install-deps chromium`（或 `sudo apt install -y libnss3 libatk1.0-0 libgbm1 libasound2`）。 |
| 文件操作很慢 / 权限错乱 | 项目放在 `~/`（WSL 文件系统），不要放 `/mnt/c`。 |
| `codex login` 打不开浏览器 | 手动复制终端 URL 到 Windows 浏览器；授权后回到终端即可。 |
| Windows 浏览器打不开 localhost:3000 | `wsl --shutdown` 重启 WSL；或改用 `wsl hostname -I` 得到的 IP 访问。 |
| 端口被 Windows 进程占用 | 改端口（后端 `--port`，前端 `vite.config.ts` 的 `server.port` + 代理 target）。 |
| 真实 Chrome 在 WSL2 起不来 | 确认已 `apt install google-chrome-stable` + `playwright install-deps chromium`；引擎已自动加 `--no-sandbox`；仍不行就改用**连接模式**（Windows 跑 Chrome + `CHROME_CDP_URL`，见 §2.5 方式 A）。 |
| 登录窗口在 WSL2 弹不出来 | Win11 确认 WSLg 可用；Win10 装 X server（VcXsrv）并 `export DISPLAY=:0`；或用连接模式（§2.5 方式 A），让登录窗口跑在 Windows 上。 |
