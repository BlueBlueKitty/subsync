# subsync

`subsync` 是一个基于 `FastAPI` 的字幕同步与编辑 Web 工具，统一调用 `ffsubsync`、`alass`、`autosubsync` 三种引擎，并提供批量处理、自动扫描和手动时间轴调整能力。

GitHub 仓库：

https://github.com/BlueBlueKitty/subsync

## 项目介绍

项目面向本地媒体库场景，支持：

- 从媒体目录选择视频和字幕
- 上传本地字幕后与媒体目录中的视频同步
- 批量处理目录中的视频/字幕
- 在浏览器中查看任务状态、日志和输出下载
- 通过设置页在每天指定时间自动扫描媒体目录，为缺失的引擎输出补齐同步结果

运行时统一使用 `DATA_ROOT` 存放配置和运行数据：

- `DATA_ROOT/config`
- `DATA_ROOT/uploads`
- `DATA_ROOT/runtime`
- `DATA_ROOT/tmp`

## 功能介绍

- 支持 `ffsubsync`、`alass`、`autosubsync`
- 自动同步单任务、批量处理、自动扫描三种入口统一命名
- 自动同步输出统一为引擎后缀命名：
  - `movie.zh.ffsubsync.srt`
  - `movie.zh.alass.srt`
  - `movie.zh.autosubsync.srt`
- 自动扫描会跳过以下派生字幕，避免重复处理：
  - `.ffsubsync.`
  - `.alass.`
  - `.autosubsync.`
  - `.shifted.`
- 手动调整仍输出 `.shifted` 文件，不参与自动扫描判定

如果你之前已经生成过“视频同名”的旧字幕结果，它们不会自动被识别为“已处理”。  
如果希望自动扫描跳过这些旧结果，需要手动重命名为新的引擎后缀格式。

## Docker 部署

镜像：

```text
bluebluekitty/subsync:latest
```

容器固定端口：

```text
1314
```

容器内固定目录：

- `/media`
- `/data`

### docker run

```bash
docker run -d \
  --name subsync \
  -p 1314:1314 \
  -e TZ=Asia/Shanghai \
  -e APP_PASSWORD=test \
  -e SECRET_KEY=test-secret-key-for-local-docker-run \
  -e PORT=1314 \
  -e MEDIA_ROOT=/media \
  -e DATA_ROOT=/data \
  -e MAX_CONCURRENT_TASKS=1 \
  -v /path/to/media:/media \
  -v /path/to/data:/data \
  bluebluekitty/subsync:latest
```

参数说明：

- `-p 1314:1314`
  把容器内 Web 服务端口 `1314` 映射到宿主机 `1314`
- `-e TZ=Asia/Shanghai`
  容器时区，自动扫描按这个时区的“每天运行时间”触发
- `-e APP_PASSWORD=test`
  Web 登录密码，必填
- `-e SECRET_KEY=test-secret-key-for-local-docker-run`
  会话签名密钥，必填，建议替换成随机长字符串
- `-e PORT=1314`
  容器内服务端口，当前固定使用 `1314`
- `-e MEDIA_ROOT=/media`
  容器内媒体根目录，页面浏览、自动同步、自动扫描都会基于这个目录
- `-e DATA_ROOT=/data`
  容器内数据目录，用于保存配置、上传文件、运行状态和临时文件
- `-e MAX_CONCURRENT_TASKS=1`
  同时运行的后台任务数量；机器性能更高时可以适当调大
- `-e QUIET_POLLING_ACCESS_LOGS=true`
  默认静默前端轮询产生的 access log，避免后台被 `/api/tasks`、`/log` 等请求刷屏
- `-v /path/to/media:/media`
  把宿主机媒体目录挂载到容器内的 `/media`
- `-v /path/to/data:/data`
  把宿主机数据目录挂载到容器内的 `/data`

访问：

```text
http://127.0.0.1:1314/
```

首次进入后：

- 首页可提交单任务和批量任务
- `/settings` 页面可配置自动扫描时间、扫描目录、排除目录、启用引擎和各引擎参数

### docker compose

```yaml
services:
  subsync:
    image: bluebluekitty/subsync:latest
    container_name: subsync
    ports:
      - "1314:1314"
    environment:
      TZ: Asia/Shanghai
      APP_PASSWORD: test
      SECRET_KEY: test-secret-key-for-local-docker-run
      PORT: "1314"
      MEDIA_ROOT: /media
      DATA_ROOT: /data
      MAX_CONCURRENT_TASKS: "1"
    volumes:
      - /path/to/media:/media
      - /path/to/data:/data
    restart: unless-stopped
```

启动：

```bash
docker compose up -d
```

compose 环境变量说明：

- `TZ`
  容器时区，影响自动扫描的每日触发时间
- `APP_PASSWORD`
  登录密码，必填
- `SECRET_KEY`
  会话签名密钥，必填
- `MEDIA_HOST_PATH`
  宿主机上的媒体目录，会挂载到容器内 `/media`
- `DATA_HOST_PATH`
  宿主机上的数据目录，会挂载到容器内 `/data`
- `QUIET_POLLING_ACCESS_LOGS`
  是否静默轮询接口的访问日志，默认 `true`；如需完整 `uvicorn` access log，可改成 `false`

`DATA_ROOT` 目录结构：

- `config`
  持久化配置，例如自动扫描设置
- `uploads`
  上传字幕时的暂存文件
- `runtime`
  扫描器状态等运行时信息
- `tmp`
  任务执行过程中的临时文件

## Build 步骤

先登录 Docker Hub：

```bash
docker login
```

使用项目内脚本直接构建并推送：

```bash
sh scripts/build_and_push.sh
```

默认会构建并推送：

- `bluebluekitty/subsync:v0.1.0`
- `bluebluekitty/subsync:latest`

自定义镜像名或版本号：

```bash
IMAGE_NAME=yourname/subsync VERSION=v0.1.0 sh scripts/build_and_push.sh
```

只想本地 build：

```bash
docker build \
  --build-arg APP_VERSION=0.1.0 \
  -t bluebluekitty/subsync:v0.1.0 \
  -t bluebluekitty/subsync:latest \
  .
```

## 本地运行

安装依赖：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

准备环境变量：

```bash
export APP_PASSWORD=test
export SECRET_KEY=test-secret-key-for-local-run
export TZ=Asia/Shanghai
export MEDIA_ROOT=/path/to/media
export DATA_ROOT=/path/to/data
export PORT=1314
export MAX_CONCURRENT_TASKS=1
```

启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 1314
```

Windows PowerShell 示例：

```powershell
$env:APP_PASSWORD="test"
$env:SECRET_KEY="test-secret-key-for-local-run"
$env:TZ="Asia/Shanghai"
$env:MEDIA_ROOT="D:\media"
$env:DATA_ROOT="D:\subsync-data"
$env:PORT="1314"
$env:MAX_CONCURRENT_TASKS="1"
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 1314
```

## 参考项目

- `ffsubsync`
  https://github.com/smacke/ffsubsync
- `alass`
  https://github.com/kaegi/alass
- `AutoSubSync`
  https://github.com/denizsafak/AutoSubSync
