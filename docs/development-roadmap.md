# Birdmark 自有鸟类识别相册 App 开发路线

## 1. 产品目标

Birdmark 的目标是从当前的单机鸟类识别工具，逐步升级为一个支持多用户的鸟类识别相册应用。

核心能力包括：

- 多用户注册、登录和个人空间。
- 用户上传自己的鸟类图片。
- 系统自动检测图片中的鸟，并给出物种鉴定建议。
- 用户可以确认或修正鉴定结果。
- 鉴定后的记录可以保存到用户自己的鸟类收集图鉴中。
- 登录用户可以浏览其他用户上传的图片和鉴定结果。
- 支持批量导入图片和批量鉴定。

## 2. 当前已有基础

当前项目已经具备较完整的 AI 识别原型能力，可以作为后续产品化的核心识别引擎。

### 2.1 后端服务

已有 `FastAPI` 服务：

- `service.py`
  - `GET /`：返回当前 Web 页面。
  - `GET /health`：服务健康检查。
  - `POST /analyze`：上传一张图片，自动检测鸟类区域，并进行物种识别。
  - `POST /recognize-box`：用户手动框选一只鸟后，对选区进行物种识别。

服务中已经包含：

- 检测模型预加载。
- 识别模型预加载。
- 识别请求批处理队列 `RecognitionBatcher`。
- 检测耗时、识别耗时、总耗时返回。
- 裁剪结果保存到 `res/service_runs/`。

### 2.2 鸟类检测

已有 `birdcut.py`：

- 基于 Ultralytics YOLO 检测鸟类目标。
- 支持普通整图检测。
- 支持大图切片检测。
- 支持批量检测。
- 支持 `.pt` 和 `.engine` 模型。
- 当前模型文件包括：
  - `models/yolo26m.pt`
  - `models/yolo26m.engine`
  - `models/yolo26m.onnx`
  - `models/yolo26m.fp16.onnx`

### 2.3 物种识别

已有 `bird_recognition.py`：

- 基于 BioCLIP 的 `TreeOfLifeClassifier`。
- 支持单图和多图预测。
- 默认按 species 层级返回 Top-K 结果。
- 自动选择 CUDA 或 CPU。

### 2.4 批处理脚本

已有 `main.py`：

- 从 `birds/` 目录读取图片。
- 批量检测鸟类 crop。
- 批量调用 BioCLIP 识别。
- 输出日志到 `logs/`。
- 输出 crop 到 `res/`。

这个脚本可以作为后续批量导入任务的参考实现。

### 2.5 前端页面

已有轻量 Web 前端：

- `web/index.html`
- `web/app.js`
- `web/styles.css`

当前能力：

- 单图上传。
- 自动检测识别。
- 手动框选识别。
- 显示检测框、裁剪图、Top-K 识别结果和耗时。

当前前端更接近“识别演示工作台”，还不是完整的多用户相册产品。

### 2.6 数据集和工具

已有数据集目录：

- `datasets/BIRDS-525-SPECIES-IMAGE-CLASSIFICATION-main`
- `datasets/CUB_200_2011`
- `datasets/HIFSOD`

已有下载和模型导出工具：

- `download_tpdc_birds.py`
- `export_tensorrt.py`

## 3. 当前缺失的产品层能力

当前项目还缺少这些关键模块：

- 用户系统。
- 数据库。
- 图片、crop、识别结果的持久化。
- 图片和用户之间的归属关系。
- 用户个人图鉴。
- 共享图片流。
- 图片详情页。
- 鉴定结果确认和人工修正。
- 批量导入任务管理。
- 登录访问控制和上传者编辑权限。
- 上传图片去重、删除和管理能力。

后续开发重点不是重做 AI 识别，而是把已有识别能力包进一个正式的相册和图鉴系统中。

## 4. 推荐技术架构

### 4.1 后端服务拆分

后端应拆成两个服务边界：

- 业务 API 服务。
- AI 推理服务。

业务 API 服务负责：

- 用户注册、登录和会话。
- 图片上传、存储、查询和删除。
- 共享相册、图片详情、用户主页。
- 鉴定确认、人工修正和个人图鉴。
- 批量导入任务管理。
- 数据库读写。
- iOS 和 Web 客户端 API。

AI 推理服务负责：

- YOLO 鸟类检测。
- BioCLIP 物种识别。
- 模型加载和预热。
- GPU 设备管理。
- 检测和识别批处理队列。
- 返回结构化推理结果。

两个服务都可以继续使用 `FastAPI`。当前 `service.py` 更接近“AI 推理服务 + Web 演示页”的混合体，后续产品化时应逐步拆出业务 API 服务。

建议逐步增加：

- `SQLAlchemy`：数据库 ORM。
- `Alembic`：数据库迁移。
- `Pydantic` schema：请求和响应结构。
- 认证模块：JWT 或 cookie session。
- 图片存储服务：封装本地文件系统，后续可替换为对象存储。
- `inference_client`：业务 API 服务调用 AI 推理服务的内部客户端。

### 4.2 数据库

开发期可以先用：

- SQLite

正式部署建议使用：

- PostgreSQL

原因：

- 更适合多用户和并发访问。
- 后续可以更好支持检索、统计和审核。
- JSON 字段可以保存 Top-K 鉴定结果。

### 4.3 图片存储

本地开发建议目录：

- `storage/originals/`：用户上传原图。
- `storage/crops/`：检测出的鸟类 crop。
- `storage/thumbs/`：缩略图。

后续部署可替换为：

- MinIO
- Amazon S3
- 阿里云 OSS
- 腾讯云 COS

### 4.4 异步任务

MVP 阶段：

- 业务 API 服务可以先使用 FastAPI `BackgroundTasks` 或进程内任务队列管理任务状态。
- AI 推理仍应通过独立推理服务边界调用，不在业务 API 服务中直接加载模型。

正式批量导入阶段：

- 建议引入 Redis 和任务队列。
- 可选方案：
  - RQ
  - Celery
  - Dramatiq

批量鉴定需要任务持久化，不建议只依赖一次 HTTP 请求完成所有工作。业务任务调度和 AI 推理并发控制应分开设计。

### 4.5 前端

短期：

- 继续使用当前 `React CDN + Ant Design` 方案，快速补页面。

中期：

- 迁移到 `Vite + React + TypeScript + Ant Design`。

原因：

- 更容易管理路由、状态、API 类型和复杂页面。
- 更适合多页面产品：登录、共享相册、图片详情、我的图鉴、批量导入等。

## 5. 核心数据模型建议

### 5.1 users

保存用户信息。

字段建议：

- `id`
- `email`
- `username`
- `display_name`
- `password_hash`
- `avatar_url`
- `created_at`
- `updated_at`

### 5.2 photos

保存用户上传的原图。

字段建议：

- `id`
- `user_id`
- `original_path`
- `thumb_path`
- `filename`
- `content_hash`
- `width`
- `height`
- `status`
- `taken_at`
- `location_name`
- `latitude`
- `longitude`
- `created_at`
- `updated_at`

`status` 可选：

- `uploaded`
- `processing`
- `ready`
- `failed`

### 5.3 bird_observations

保存一张图片中检测到的每一只鸟。

字段建议：

- `id`
- `photo_id`
- `crop_path`
- `bbox_x1`
- `bbox_y1`
- `bbox_x2`
- `bbox_y2`
- `detection_confidence`
- `detection_source`
- `created_at`

`detection_source` 可选：

- `detector`
- `detector_retry`
- `manual`
- `full_image`

### 5.4 identifications

保存 AI 鉴定建议和最终确认结果。

字段建议：

- `id`
- `observation_id`
- `model_name`
- `model_version`
- `top_k_results`
- `suggested_species_id`
- `confirmed_species_id`
- `confirmed_by_user_id`
- `confirmed_at`
- `is_confirmed`
- `created_at`

说明：

- `top_k_results` 建议使用 JSON 保存 BioCLIP 返回的 Top-K。
- AI 结果应视为“建议”，不应默认等同于最终鉴定。
- 用户确认后再写入个人图鉴。

### 5.5 species

保存物种基础信息。

字段建议：

- `id`
- `scientific_name`
- `common_name`
- `chinese_name`
- `genus`
- `family`
- `order_name`
- `source`
- `created_at`
- `updated_at`

初期可以先从 BioCLIP 返回结果中动态生成物种记录，后续再清洗成标准物种库。

### 5.6 collection_entries

保存用户个人鸟类图鉴。

字段建议：

- `id`
- `user_id`
- `species_id`
- `first_observation_id`
- `representative_photo_id`
- `observation_count`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

当某个 `bird_observation` 的物种被确认后，系统更新对应用户的 `collection_entries`。

### 5.7 import_jobs

保存批量导入任务。

字段建议：

- `id`
- `user_id`
- `status`
- `total_count`
- `processed_count`
- `success_count`
- `failed_count`
- `created_at`
- `started_at`
- `finished_at`

`status` 可选：

- `pending`
- `running`
- `completed`
- `failed`
- `cancelled`

### 5.8 import_items

保存批量导入中的单张图片处理状态。

字段建议：

- `id`
- `job_id`
- `photo_id`
- `filename`
- `status`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

## 6. 开发路线

### 阶段 1：识别结果持久化

目标：

把当前“上传后即时识别”的流程，改造成“上传、识别、保存、可回看”的流程。

主要任务：

- 引入数据库。
- 创建基础表结构。
- 增加本地图片存储目录。
- 保存用户上传原图。
- 保存检测 crop。
- 保存 Top-K 识别结果。
- 改造 `POST /analyze`，返回持久化后的 `photo_id` 和 `observation_id`。
- 新增图片详情接口。
- 前端增加保存结果和查看历史结果的入口。

建议接口：

- `POST /photos/analyze`
- `GET /photos/{photo_id}`
- `GET /photos/{photo_id}/observations`

验收标准：

- 上传一张图片后，刷新页面不会丢失结果。
- 能通过图片详情接口重新看到原图、crop 和识别结果。
- 所有原图和 crop 都有数据库记录。

### 阶段 2：多用户系统

目标：

让每张图片都有明确的上传用户，并支持个人空间。

主要任务：

- 增加用户注册。
- 增加登录和登出。
- 增加密码哈希。
- 增加认证中间件或依赖。
- 上传图片时绑定 `user_id`。
- 增加“我的上传”接口和页面。

建议接口：

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /me`
- `GET /me/photos`

验收标准：

- 不同用户只能管理自己的图片。
- 图片记录中能看到上传者。
- 用户登录后可以看到自己的上传历史。

### 阶段 3：共享相册和个人图鉴

目标：

支持登录用户互相查看上传的图片和鉴定结果，并形成个人鸟类图鉴。

主要任务：

- 增加共享图片流。
- 增加图片详情页。
- 增加 AI 鉴定确认功能。
- 支持用户手动修正物种。
- 用户确认鉴定后，更新个人 `collection_entries`。
- 增加“我的图鉴”页面。
- 增加用户主页。

建议接口：

- `GET /feed/photos`
- `GET /users/{user_id}/photos`
- `GET /users/{user_id}/collection`
- `POST /observations/{observation_id}/confirm`
- `PATCH /observations/{observation_id}/identification`

验收标准：

- 用户可以浏览其他用户上传的图片。
- 图片详情页能展示上传者、原图、检测 crop 和鉴定结果。
- 用户确认某个物种后，该物种出现在自己的图鉴中。
- 同一物种多次出现时，图鉴中计数更新。

### 阶段 4：批量导入和批量鉴定

目标：

支持一次上传多张图片或一个压缩包，由后台逐张处理。

主要任务：

- 增加多文件上传。
- 增加 zip 导入。
- 创建 `import_jobs` 和 `import_items`。
- 后台逐张保存、检测、识别、入库。
- 前端展示导入进度。
- 支持失败重试。
- 支持取消任务。

建议接口：

- `POST /imports`
- `GET /imports/{job_id}`
- `GET /imports/{job_id}/items`
- `POST /imports/{job_id}/retry`
- `POST /imports/{job_id}/cancel`

验收标准：

- 用户可以一次导入多张图片。
- 任务处理过程中能看到进度。
- 单张图片失败不会导致整个任务不可用。
- 导入完成后，成功图片进入用户相册。

### 阶段 5：产品增强

目标：

提升可用性、准确性和社区属性。

可选任务：

- 图片点赞。
- 评论。
- 收藏。
- 按物种筛选。
- 按用户筛选。
- 按时间筛选。
- 按地点筛选。
- 地图视图。
- EXIF 读取。
- 上传图片去重。
- 管理员审核。
- 物种中文名库。
- 模型误识反馈。
- 用户修正数据导出。
- 识别准确率评估面板。

## 7. 推荐近期任务清单

近期优先级建议：

1. 整理 AI 推理服务边界，保留检测和识别内部 API。
2. 新增业务 API 服务骨架。
3. 新增业务 API 到 AI 推理服务的 `inference_client`。
4. 新增数据库依赖和初始化配置。
5. 设计并创建第一版数据模型。
6. 增加图片存储服务。
7. 新增业务 API `POST /photos`，调用 AI 推理服务并让识别结果入库。
8. 增加图片详情接口。
9. 前端增加历史记录或图片详情页面。
10. 增加用户注册和登录。
11. 增加“我的上传”和“我的图鉴”页面。

第一阶段应尽量少改 AI 识别逻辑，重点把当前可靠的识别流程沉淀成可保存、可查询、可扩展的数据。

## 8. 关键设计原则

- AI 鉴定结果默认是建议，不是最终结论。
- 用户确认或人工修正后，才进入正式个人图鉴。
- 原图、crop、识别结果必须能互相追溯。
- 批量任务必须可恢复、可查看失败原因。
- 数据库只存路径和元数据，不直接存图片二进制。
- AI 推理服务和产品业务 API 必须解耦，方便后续扩展队列和 GPU worker。
- 先做可用闭环，再做社区和高级检索。

## 9. MVP 闭环定义

第一版 MVP 可以定义为：

- 用户可以注册登录。
- 用户可以上传单张图片。
- 系统自动识别图片中的鸟。
- 用户可以确认一个鉴定结果。
- 确认后的鸟出现在用户自己的图鉴中。
- 其他登录用户可以看到这张图片和鉴定结果。

完成这个闭环后，Birdmark 就从识别工具进入了真正的相册产品阶段。
