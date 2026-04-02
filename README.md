# ffsubsync-web

`ffsubsync-web` 是一个基于 `FastAPI` 的 `ffsubsync` Web 界面，用来在浏览器中完成视频与字幕的自动同步和手动时间轴调整。

## 项目介绍

这个项目主要面向想要用 `ffsubsync`，但更希望通过网页完成操作的场景。它把原本的命令行流程封装成了一个更直观的 Web 工作台，支持在页面中选择视频、选择或上传字幕、提交后台同步任务、查看任务日志和进度，以及对字幕做简单的手动时间偏移处理。

项目特点：

- 从媒体目录中选择视频
- 从媒体目录中选择字幕，或上传本地字幕
- 创建后台同步任务并查看进度、日志
- 手动整体调整字幕时间轴并下载结果

整个项目以 Docker 部署为主要使用方式，镜像启动后即可通过浏览器访问。

Docker image:

```text
bluebluekitty/ffsubsync-web:latest
```

应用固定监听端口：

```text
1314
```

容器内使用的固定路径：

- `/media`
- `/work`

需要的环境变量：

- `APP_PASSWORD`
- `SECRET_KEY`
- `PORT=1314`
- `MEDIA_ROOT=/media`
- `WORK_ROOT=/work`
- `MAX_CONCURRENT_TASKS=1`

## Docker Run

```bash
docker run -d \
  --name ffsubsync-web \
  -p 1314:1314 \
  -e APP_PASSWORD=test \
  -e SECRET_KEY=test-secret-key-for-local-docker-run \
  -e PORT=1314 \
  -e MEDIA_ROOT=/media \
  -e WORK_ROOT=/work \
  -e MAX_CONCURRENT_TASKS=1 \
  -v /path/to/media:/media \
  -v /path/to/work:/work \
  bluebluekitty/ffsubsync-web:latest
```

访问：

```text
http://127.0.0.1:1314/
```

## Docker Compose

`docker-compose.yml`

```yaml
services:
  ffsubsync-web:
    image: bluebluekitty/ffsubsync-web:latest
    container_name: ffsubsync-web
    ports:
      - "1314:1314"
    environment:
      APP_PASSWORD: test
      SECRET_KEY: test-secret-key-for-local-docker-run
      PORT: "1314"
      MEDIA_ROOT: /media
      WORK_ROOT: /work
      MAX_CONCURRENT_TASKS: "1"
    volumes:
      - /path/to/media:/media
      - /path/to/work:/work
    restart: unless-stopped
```

启动：

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```
