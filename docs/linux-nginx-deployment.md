# Linux / Nginx 部署演示

该配置用于验证“Nginx + 两个 API 副本 + Worker + PostgreSQL/pgvector”的容器通信和负载均衡。它是可本地复现的部署演示，不代表已在 Linux 生产环境上线。

## 架构

```text
浏览器 :8080
      ↓
    Nginx
   ↙     ↘
 api1     api2
   ↘       ↙
 PostgreSQL/pgvector ← Worker
```

Nginx 使用默认轮询在两个 FastAPI 实例间分配请求。`/api/chat/stream` 关闭代理缓冲，避免 SSE 回答被缓存后一次性返回。Worker 不接收浏览器流量，因此不放在 Nginx 后面。

## 启动

Ubuntu/CentOS 与 Docker Desktop 均可使用同一组 Compose 命令：

```bash
cp .env.example .env
# 填写 DEEPSEEK_API_KEY，替换 SESSION_SECRET 和数据库密码
docker compose -f docker-compose.nginx.yml up --build -d
docker compose -f docker-compose.nginx.yml ps
```

访问 <http://127.0.0.1:8080>。首次导入演示文档：

```bash
docker compose -f docker-compose.nginx.yml exec api1 python -m scripts.load_demo
```

使用持久 HTTP 连接验证 Nginx 轮询：

```bash
docker compose -f docker-compose.nginx.yml exec api1 python -c \
  "import httpx; c=httpx.Client(); print([c.get('http://nginx/api/health').headers.get('x-upstream-addr') for _ in range(6)])"
```

响应头 `X-Upstream-Addr` 显示实际处理请求的 API 容器地址，结果应在两个地址之间轮换。

## 生产环境仍需补充

- 使用 HTTPS 证书，并设置 `COOKIE_SECURE=true`。
- 删除固定演示账号，接入 SSO 或企业身份系统。
- 将 `.env` 替换为密钥管理服务。
- 增加数据库备份、集中日志、告警和真实压测。
- 文档量增大后，评估对象存储、独立任务队列和 Embedding 服务化。

停止并保留 Volume 数据：

```bash
docker compose -f docker-compose.nginx.yml down
```
