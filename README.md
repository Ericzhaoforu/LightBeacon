# LightBeacon

LightBeacon 是一套运行在专用局域网内的 ESP32 灯光控制系统。控制主机通过 UDP 控制 10–50 个 ESP32-WROOM-32UE 节点；每个节点把 288 颗侧边灯带和 64 颗顶部点阵作为一个同步的逻辑颜色点。

仓库主要目录：

- `host/`：FastAPI、SQLite、UDP 控制器、鉴权、OTA 协调和节点模拟器；
- `web/`：React/TypeScript 现场控制台；
- `firmware/`：ESP-IDF 节点固件；
- `protocol/`：通信协议和跨语言 golden vectors；
- `docs/`：开发、硬件、部署和现场操作文档。

现场接线、ESP32 配网、控制台操作和故障排查请优先阅读 [中文用户手册](docs/OPERATOR_GUIDE_ZH.md)。

## 在一台新控制电脑上安装

### 1. 前置软件

只运行控制主机时需要：

- Git；
- Python 3.12；
- Node.js 24.x（推荐）和 npm，用于首次构建网页。

Windows 安装完成后可先确认：

```powershell
git --version
py -3.12 --version
node --version
npm.cmd --version
```

如果 `py -3.12` 找不到解释器，请安装 Python 3.12 后重新打开 PowerShell。当前网页工具链要求 Node.js `^20.19.0`、`^22.12.0` 或 `>=24.0.0`，直接使用 Node.js 24.x 最省事。

正常控制不需要 ESP-IDF，也不需要重新编译或烧录 ESP32。首次下载依赖需要互联网；依赖装好、网页构建完成后，现场运行只需要 LightBeacon 局域网。

### 2. 克隆公开仓库

```powershell
git clone https://github.com/Ericzhaoforu/LightBeacon.git
cd LightBeacon
```

仓库虽然是公开的，但不包含系统授权信息和现场数据：`.env`、`data/`、`.venv/`、日志、网页构建结果及固件密钥均由 `.gitignore` 排除。

### 3. Windows：安装 Python 依赖并构建网页

在项目根目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

cd web
npm.cmd ci
npm.cmd run build
cd ..
```

这里特意使用 `npm.cmd`：部分 Windows PowerShell 会因执行策略拦截 `npm.ps1`，`npm.cmd` 不需要修改系统执行策略。网页构建结果位于 `web/dist/`，该目录不会提交到 GitHub，所以每台新控制电脑都要构建一次。

### 4. Linux：安装 Python 依赖并构建网页

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

cd web
npm ci
npm run build
cd ..
```

如需运行自动化测试，把 Python 安装命令改为 `.venv/bin/python -m pip install -e ".[dev]"`；Windows 对应为 `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`。现场运行只需 `pip install -e .`。

## 配置 `.env`

### 已有系统迁移到新主机

通过密码管理器、加密文件或加密 U 盘，把旧主机项目根目录中的 `.env` 安全复制到新主机的项目根目录。不要通过 GitHub、公开网盘或普通聊天发送该文件。

迁移时：

- `LIGHTBEACON_HMAC_KEY` 必须保持原值；它是主机获得现有 ESP32 控制权限的凭证；
- `LIGHTBEACON_BIND_HOST` 保持 `0.0.0.0`；
- HTTP/UDP 端口保持 `8080`/`40404`；
- 将 `LIGHTBEACON_PUBLIC_BASE_URL` 改为新主机在现场局域网中的 IPv4 地址，例如 `http://192.168.50.30:8080`；
- `LIGHTBEACON_SESSION_SECRET` 和管理员密码哈希可以更换，但普通迁移无需更换。

Windows 可用 `ipconfig` 查找连接现场 AP 的网卡 IPv4 地址。仅迁移控制电脑、现场 Wi-Fi 没变且 HMAC 密钥相同时，ESP32 不需要重新配网。

`data/` 不会通过 GitHub 迁移。新主机仍能自动发现和控制节点，但需要重新建立二维布局。若确实要保留布局和历史，应在旧服务停止后，通过安全方式单独复制 `data/`，不要提交到仓库。

### 建立一套全新的系统

如果不是迁移已有节点，而是首次部署：

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m lightbeacon.cli generate-secrets
.\.venv\Scripts\python.exe -m lightbeacon.cli hash-password
```

把命令输出分别写入 `.env` 对应字段，把 `LIGHTBEACON_PUBLIC_BASE_URL` 改为主机现场局域网地址，并把 `LIGHTBEACON_PROVISIONING_PASSWORD` 改为部署使用的 8 位以上密码。确认 `.env` 中不再有任何 `CHANGE_ME` 后，使用同一个 `LIGHTBEACON_HMAC_KEY` 给所有 ESP32 配网。不要把命令输出或完成后的 `.env` 提交到 GitHub。

## 启动控制台

启动前，控制电脑应与 ESP32 连接同一个 2.4 GHz 局域网，AP 必须关闭客户端隔离。Windows 防火墙应仅在专用网络允许 TCP 8080 和 UDP 40404。

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-host.ps1
```

Linux：

```sh
./scripts/run-host.sh
```

然后打开 <http://127.0.0.1:8080/>。停止服务时在终端按 `Ctrl+C`。

同一局域网内只能运行一个 LightBeacon 主机服务。两个主机会使用不同会话 ID，使节点反复进入新会话并保持熄灭。

## 在另一台电脑上验证主机迁移

建议按以下顺序测试：

1. 在旧主机点击“紧急全灭”，确认节点为 `OFF`，然后按 `Ctrl+C` 停止旧服务。
2. 新电脑连接到 ESP32 当前使用的同一个现场局域网。
3. 按上文完成克隆、Python 依赖安装、网页构建和 `.env` 迁移。
4. 修改新主机的 `LIGHTBEACON_PUBLIC_BASE_URL`，检查防火墙，然后启动服务。
5. 打开控制台并登录；节点应在约 5 秒内自动出现。因为 `data/` 不在 GitHub 中，需要重新建立布局。
6. 只选择一个节点，以 5% 亮度测试 `SOLID_BLUE`，随后发送 `OFF`。
7. 再测试一种闪烁灯效和“紧急全灭”，并确认逐节点 ACK 正常。

如果验证失败，先停止新主机，再重新启动旧主机即可回退；不要让两台主机同时运行。新主机完全看不到节点时，依次检查同一局域网、AP 客户端隔离、UDP 40404 防火墙，以及两端 HMAC 密钥是否完全一致。

## 模拟节点（可选）

主机启动后，在第二个终端运行：

```powershell
.\.venv\Scripts\python.exe -m lightbeacon.simulator --count 10
```

控制台会显示 10 个虚拟节点，可在不连接硬件时验证布局和基本灯效命令。

## 更多文档

- [中文用户手册](docs/OPERATOR_GUIDE_ZH.md)
- [开发环境](docs/DEVELOPMENT.md)
- [硬件与接线](docs/HARDWARE.md)
- [部署说明](docs/DEPLOYMENT.md)
- [协议规范](protocol/SPEC.md)

## 供电安全

禁止从开发板或电脑 USB 给 352 颗 WS2812B 供电。应使用带保护的独立 5 V 电源、正确的线径和电源注入、可靠共地，以及 5 V AHCT 数据电平转换。固件亮度上限不能替代正确的电气设计。
