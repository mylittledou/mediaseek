# MediaSeek - 极速 M3U8 视频下载器

![License](https://img.shields.io/badge/license-MIT-blue)
![Architecture](https://img.shields.io/badge/Architecture-x86__64%2Famd64-orange)
![Docker](https://img.shields.io/badge/Docker-GHCR-blue)
![Build](https://img.shields.io/badge/GitHub%20Actions-Automated-green)

MediaSeek 是一款基于 **FastAPI + WebSockets + 异步并发 + Playwright Stealth** 开发的高性能 M3U8 视频下载管理系统。具备暗黑玻璃拟态高颜值 Web UI，支持管理员鉴权登录、网页视频智能解析提取、伪装 PNG 图片解包、实时进度监控及 GitHub Actions 自动构建 GHCR 容器部署。

GitHub 仓库地址：[https://github.com/mylittledou/mediaseek](https://github.com/mylittledou/mediaseek)

---

## 🌟 核心特性

- **🔒 管理员安全鉴权**：
  - 新设备首次打开需身份认证。默认账号 `admin` / 密码 `admin`。
  - 支持在 Docker / 部署环境中通过 `ADMIN_USER` 和 `ADMIN_PASSWORD` 环境变量任意自定义账号与密码。
- **🔍 网页视频智能解析 (Playwright Stealth)**：
  - 支持输入 M3U8 直链或普通视频网页 URL。
  - 集成 **Playwright Stealth** 隐身无头浏览器，可全自动绕过 Cloudflare 403 / Turnstile 防护，精准提取播放流与网页标题。
- **三大功能标签页**：
  1. **添加下载**：输入/解析视频链接、自定义文件名、并发切片数设置及存储路径选择（默认 `/downloads`）。
  2. **正在下载**：实时展示视频大小、切片计数（如 `185/450 片`）、当前网速、剩余时间 (ETA) 及控制按钮（暂停/恢复/取消）。
  3. **历史下载**：记录完成时间、最终文件大小、保存目录，支持一键重试或清理。最新下载的文件**始终置顶**。
- **伪装 PNG 智能剥离**：自动检测防盗链伪造图片头（如 turboviplay/jable 伪造 PNG），精确定位并剥离 941 字节图片数据，确保生成的视频文件 100% 可被播放器正常打开。
- **⚙️ GitHub Actions x86 自动构建**：每次提交代码或发布 Release，GitHub Actions 自动构建 **`linux/amd64 (x86_64)`** 镜像并推送到 GHCR。

---

## ⚙️ 环境变量与持久化目录映射

### 1. 环境变量配置 (Environment Variables)

| 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `ADMIN_USER` | `admin` | 管理员登录用户名 |
| `ADMIN_PASSWORD` | `admin` | 管理员登录密码 |
| `DOWNLOAD_DIR` | `/downloads` | 视频下载文件的默认保存目录 |
| `DATA_DIR` | `/app/data` | SQLite 数据库文件的默认保存目录 |
| `TZ` | `Asia/Shanghai` | 容器运行时区设置 |

---

### 2. 持久化映射目录 (Volume Mounts)

必须映射以下宿主机目录，以保证下载的视频文件与历史记录数据库在重启或更新镜像时不丢失：

| 宿主机路径 | 容器内路径 | 作用与说明 |
| :--- | :--- | :--- |
| `./downloads` | `/downloads` | **视频文件存储目录**：所有已完成和下载中的 MP4 视频媒体文件 |
| `./data` | `/app/data` | **数据库持久化目录**：包含 `mediaseek.db` 文件，保存任务状态与历史记录 |

---

## 🐳 Docker & GHCR 一键拉取与部署

项目每次提交代码，GitHub Actions 会自动编译 **x86_64 (amd64)** 架构镜像发布至 GHCR。

### 1. 从 GHCR 拉取映像并启动 (Docker Run)

```bash
docker run -d \
  --name mediaseek \
  --restart unless-stopped \
  -p 8000:8000 \
  -e ADMIN_USER=admin \
  -e ADMIN_PASSWORD=your_secure_password \
  -e TZ=Asia/Shanghai \
  -v $(pwd)/downloads:/downloads \
  -v $(pwd)/data:/app/data \
  ghcr.io/mylittledou/mediaseek:latest
```

---

### 2. 使用 Docker Compose 一键部署

在服务器创建 `docker-compose.yml` 文件：

```yaml
version: '3.8'

services:
  mediaseek:
    image: ghcr.io/mylittledou/mediaseek:latest
    container_name: mediaseek
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./downloads:/downloads
      - ./data:/app/data
    environment:
      - ADMIN_USER=admin
      - ADMIN_PASSWORD=your_secure_password
      - DOWNLOAD_DIR=/downloads
      - DATA_DIR=/app/data
      - TZ=Asia/Shanghai
```

运行启动命令：
```bash
docker-compose up -d
```

打开浏览器访问 [http://你的服务器IP:8000](http://你的服务器IP:8000) 即可开始使用！

---

## 🛠️ 本地开发与调试

```bash
# 1. 克隆代码
git clone https://github.com/mylittledou/mediaseek.git
cd mediaseek

# 2. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r backend/requirements.txt
python -m playwright install chromium

# 4. 启动本地服务
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📄 开源协议
MIT License
