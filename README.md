# Birdmark

Birdmark 是自有鸟类识别相册应用的业务应用仓库，负责用户、图片、观察记录、鉴定确认、图鉴、批量导入、业务 Web 页面和后续 iOS 客户端规划。

AI 推理、模型、训练/评估脚本已经拆分到独立仓库：

```text
C:\Users\hg\project\birdmark-ai
```

当前仓库不再保存 AI 推理服务代码、模型文件、训练脚本和数据集处理脚本。业务 API 通过 HTTP 调用外部 AI 推理服务。

## 当前能力

- 用户注册、登录、登出和 token 鉴权。
- 登录用户上传鸟类图片，并调用外部 AI 服务自动鉴定。
- 保存原图、缩略图、裁剪图、检测框和 Top-K 鉴定建议。
- 上传者可以确认物种、手动修正、标记未知或标记误检。
- 确认后的观察记录会进入个人鸟类图鉴。
- 登录用户可以浏览共享相册中的其他用户图片和鉴定结果。
- 用户可以查看、管理和软删除自己的上传。
- 支持批量导入图片，并查看任务进度、成功数和失败原因。
- 提供业务 Web 页面。

## 仓库结构

```text
apps/
  api/      业务 API 服务
  web/      业务 Web 页面
  ios/      未来 iOS App
docs/       产品设计、路线图和任务文档
storage/    本地数据库、上传图片和生成媒体
datasets/   本地数据集，暂时保留在当前工作区，不要清理
```

本仓库已移除：

- `apps/inference/`
- `apps/inference_web/`
- `packages/birdmark_ml/`
- `scripts/`
- `models/`
- `birds/`
- `start.bat`

这些内容已经复制到 `birdmark-ai`。

## 环境准备

推荐在 Windows PowerShell 中运行。

项目使用本地虚拟环境：

```powershell
.\.venv\Scripts\python.exe
```

业务 API 依赖位于：

```text
apps/api/requirements.txt
```

## 启动服务

### 1. 启动外部 AI 推理服务

先进入 AI 仓库：

```powershell
cd C:\Users\hg\project\birdmark-ai
.\start.bat
```

AI 推理服务默认地址：

```text
http://127.0.0.1:8000
```

业务 API 默认通过以下环境变量读取 AI 服务地址：

```powershell
$env:BIRDMARK_INFERENCE_URL="http://127.0.0.1:8000"
```

不设置时也默认使用 `http://127.0.0.1:8000`。

### 2. 启动业务 API 服务

回到当前仓库：

```powershell
cd C:\Users\hg\project\birdmark
.\start-api.bat
```

或直接运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8100
```

业务 API 默认地址：

```text
http://127.0.0.1:8100
```

业务 Web 页面：

```text
http://127.0.0.1:8100/
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8100/health -UseBasicParsing
```

## Web 使用指南

打开：

```text
http://127.0.0.1:8100/
```

首次使用：

1. 注册一个用户。
2. 登录后进入主界面。
3. 在“上传”页选择鸟类图片。
4. 点击“上传并识别”。
5. 在图片详情中查看 AI 建议。
6. 选择 Top-K 建议进行确认，或手动填写物种信息。
7. 到“图鉴”页查看已确认物种。

主要页面：

- 共享：浏览所有登录用户上传的图片和鉴定结果。
- 上传：单图上传并触发 AI 鉴定。
- 图鉴：查看当前用户确认过的鸟类集合。
- 我的：查看个人资料、我的上传和删除自己的照片。
- 批量：一次提交多张图片，查看批量任务状态。

注意：

- Web 页面由业务 API 提供。
- 单图识别和批量识别需要 `birdmark-ai` 推理服务同时运行。
- 如果 AI 推理服务没有启动，上传可能会返回 502，并在照片记录中保留失败状态。

## 主要 API

### Auth

- `POST /auth/register`：注册。
- `POST /auth/login`：登录。
- `POST /auth/logout`：登出。
- `GET /auth/me`：读取当前用户。

业务接口使用：

```text
Authorization: Bearer <access_token>
```

### Photos

- `GET /photos`：共享相册列表。
- `POST /photos`：上传单张图片并识别。
- `GET /photos/{photo_id}`：图片详情。
- `DELETE /photos/{photo_id}`：上传者软删除图片。
- `GET /me/photos`：我的上传。

### Observations

- `POST /observations/{observation_id}/confirm`：确认或修正物种。
- `POST /observations/{observation_id}/mark-unknown`：标记未知。
- `POST /observations/{observation_id}/reject`：标记误检。

### Collections

- `GET /me/collection`：我的鸟类图鉴。

### Imports

- `POST /import-batches`：创建批量导入任务。
- `GET /me/import-batches`：我的批量任务列表。
- `GET /import-batches/{batch_id}`：批量任务详情。

## 数据和存储

开发期默认使用 SQLite：

```text
storage/birdmark.sqlite3
```

上传和生成的媒体文件保存在：

```text
storage/
```

数据库只保存图片路径和元数据，不直接保存图片二进制。

## 开发指南

### 后端边界

业务 API 和 AI 推理服务保持分离：

- 当前仓库只保留业务 API。
- 当前仓库不直接加载 YOLO、BioCLIP、torch 或 TensorRT。
- `apps/api/app/inference_client.py` 通过 HTTP 调用 `birdmark-ai`。
- AI 模型、推理队列、GPU 管理、训练和评估都在 `birdmark-ai` 仓库维护。

新增业务功能时，优先放在 `apps/api/app/` 下对应模块中：

- 用户和会话：`auth.py`
- 图片和上传：`photos.py`
- 观察记录确认：`observations.py`
- 图鉴：`collections.py`
- 批量任务：`imports.py`
- 数据库：`database.py`
- 存储：`storage.py`

### 前端边界

- 业务 Web 页面位于 `apps/web/`。
- 当前前端使用 React CDN 和 Ant Design CDN，没有独立构建流程。
- 修改 `apps/web/` 后，刷新 `http://127.0.0.1:8100/` 即可查看。

## 常用验证命令

后端语法和导入检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q apps/api/app
```

前端 JavaScript 语法检查，如果本机安装了 Node.js：

```powershell
node --check apps/web/app.js
```

业务 API 健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8100/health -UseBasicParsing
```

AI 推理服务健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/internal/health -UseBasicParsing
```

## 开发流程建议

1. 在 `birdmark-ai` 启动 AI 推理服务。
2. 在当前仓库启动业务 API 服务。
3. 打开业务 Web 页面。
4. 注册或登录用户。
5. 用一张小图片验证上传识别。
6. 确认物种后检查我的图鉴。
7. 修改代码后运行 compileall 或相关烟测。
8. 提交前检查 `git status` 和 diff。

## 文档

更多设计和规划见：

- `docs/development-roadmap.md`
- `docs/end-to-end-flow-design.md`
- `docs/task-checklist.md`
- `docs/project-structure.md`
- `docs/ios-app-v1-design.md`

## 后续方向

- 引入 Alembic 管理数据库迁移。
- 将批量导入从 FastAPI BackgroundTasks 迁移到 Redis + RQ/Celery/Dramatiq 等队列。
- 完善 Web 的图片详情体验和批量任务轮询。
- 建立 iOS 工程和 API Client。
- 增加自动化测试和示例数据。
