# 贡献指南

感谢你对知域 RAG Agent 的关注。提交改动前，请先确认改动属于当前项目范围，并避免引入真实企业文档、账号密码或 API Key。

## 本地开发

1. 复制 `.env.example` 为 `.env`，填写本地配置。
2. 使用 `docker compose up --build` 启动服务。
3. 使用 `docker compose exec api python -m scripts.load_demo` 导入演示文档。
4. 提交前运行核心测试与 Compose 配置检查。

```powershell
docker compose exec api pytest -q tests/test_core.py tests/test_enhancements.py
docker compose config --quiet
docker compose -f docker-compose.nginx.yml config --quiet
```

## 提交要求

- 一个提交只解决一个明确问题。
- 新增行为应包含最小可复现测试。
- 不提交 `.env`、模型缓存、上传文件或真实敏感资料。
- 不把本地验证描述为生产部署或高并发验证。
- Pull Request 需要说明改动目的、影响范围和验证命令。

## 项目边界

当前项目定位为单组织、固定部门的工程化 MVP。OCR、多租户、企业 SSO、Kubernetes 和复杂 Reranker 应在存在明确需求和评测依据时再引入。
