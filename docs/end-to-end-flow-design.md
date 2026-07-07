# Birdmark 端到端流程详细设计

## 1. 设计目标

本文档描述 Birdmark 从“上传图片”到“形成个人鸟类图鉴”的完整产品流程、后端流程和客户端流程。它是后续开发前的详细设计草案，方便继续讨论、修订和拆分任务。

Birdmark 的最终形态是一个以 iOS App 为主要客户端的鸟类识别相册应用。当前 Web 前端可以继续作为原型、调试台和早期管理界面，但产品体验应逐步向移动端收敛。

核心目标：

- 所有业务内容都要求登录后访问。
- 不设计未登录浏览流程。
- 登录用户之间可以互相浏览系统内图片和鉴定结果。
- 登录用户可以上传鸟类图片。
- 登录用户可以看到其他用户上传的图片和鉴定结果。
- 系统自动检测图片中的鸟，并给出物种鉴定建议。
- 用户可以确认或修正自己上传图片中的鉴定结果。
- 确认后的观察记录进入用户自己的鸟类收集图鉴。
- 支持批量导入和后台批量鉴定。
- 保留现有 YOLO 检测和 BioCLIP 识别能力，并在其外层补齐产品系统。

## 2. 设计边界

### 2.1 本阶段重点

本阶段重点设计：

- 用户账号流程。
- 单张图片上传流程。
- 自动鉴定流程。
- 手动框选鉴定流程。
- 鉴定确认和修正流程。
- 个人图鉴生成流程。
- 登录用户之间的共享相册浏览流程。
- 批量导入流程。
- 数据状态流转。
- 后端模块边界。
- Web 原型页面结构。
- iOS App 客户端架构和页面规划。
- API 草案。

### 2.2 暂不深入设计

以下能力先保留空间，不作为第一版核心：

- 点赞和评论。
- 管理员审核后台。
- 私信和关注。
- 模型训练平台。
- 专业物种分类库维护后台。
- Android 客户端。
- 多租户组织空间。

## 3. 角色和权限

### 3.1 未登录用户

未登录用户只可以：

- 注册账号。
- 登录账号。
- 查看登录页、注册页、找回密码页。

未登录用户不可以：

- 查看相册内容。
- 查看用户主页。
- 查看图片详情。
- 查看图鉴。
- 上传图片。
- 运行鉴定。

### 3.2 登录用户

登录用户可以：

- 上传单张图片。
- 批量导入图片。
- 查看系统内用户上传的图片和鉴定结果。
- 查看自己的全部图片。
- 对自己的图片运行自动鉴定。
- 对自己的图片手动框选鸟类并识别。
- 确认或修正自己图片中的鸟类鉴定结果。
- 将确认结果写入个人图鉴。
- 删除自己的图片或观察记录。
- 查看其他用户的个人主页和图鉴。

登录用户不可以：

- 修改其他用户的图片。
- 删除其他用户的数据。
- 确认或修正其他用户图片中的鉴定结果。

### 3.3 管理员

管理员能力后续再做。第一版只预留 `role` 字段，不做复杂后台。

未来管理员可以：

- 处理异常图片。
- 合并或修正物种条目。
- 查看任务异常。
- 管理用户状态。

## 4. 核心概念

### 4.1 图片 Photo

`Photo` 表示用户上传的一张原图。

一张图片可能包含：

- 0 只鸟：检测失败或确实无鸟。
- 1 只鸟：常见场景。
- 多只鸟：一张图中产生多个观察记录。

图片归属于一个上传用户。系统内所有登录用户都可以浏览图片，但只有上传者可以编辑、删除和确认鉴定。

### 4.2 观察记录 Observation

`Observation` 表示一张图片中的一只鸟。

一个观察记录包含：

- 所属图片。
- 检测框。
- crop 图片。
- 检测置信度。
- 检测来源。
- 当前鉴定状态。

### 4.3 鉴定 Identification

`Identification` 表示对某个观察记录的物种判断。

它分为两层：

- AI 建议：由 BioCLIP 返回 Top-K 结果。
- 用户确认：上传者选择其中一个结果，或手动指定其他物种。

第一版不要把 AI Top-1 自动当作最终结果。AI 结果只作为建议显示。

### 4.4 物种 Species

`Species` 表示标准化后的鸟类物种。

第一版可以从 BioCLIP 返回值中动态生成物种记录。后续再引入中文名、分类树、外部物种编号和同物异名处理。

### 4.5 图鉴 Collection

`CollectionEntry` 表示某个用户已经确认收集到某个物种。

图鉴不是手动维护的普通列表，而是由已确认观察记录聚合而来：

- 用户确认自己上传图片中的某个观察记录为某物种。
- 系统检查该用户是否已有此物种图鉴项。
- 没有则创建，有则更新次数和最近观察时间。

## 5. 总体架构

### 5.1 服务拆分

后端应拆成两个边界清晰的服务：

- 业务 API 服务。
- AI 推理服务。

业务 API 服务负责产品和后台管理：

- 用户注册、登录和会话。
- 图片上传、存储和查询。
- 图片详情、共享相册、用户主页。
- 观察记录、鉴定确认、人工修正。
- 个人图鉴聚合。
- 批量导入任务和任务状态。
- 数据库读写。
- iOS 和 Web 客户端 API。

AI 推理服务负责模型和推理：

- 加载 YOLO 检测模型。
- 加载 BioCLIP 识别模型。
- 执行鸟类检测。
- 执行 crop 物种识别。
- 管理 GPU、批处理队列和模型预热。
- 返回结构化推理结果。

两个服务的边界原则：

- 业务 API 服务不直接 import `birdcut.py` 或 `bird_recognition.py`。
- 业务 API 服务不直接加载大模型。
- AI 推理服务不管理用户、图鉴、权限和业务数据库。
- AI 推理服务不决定鉴定是否最终确认。
- AI 推理服务可以是无状态服务，必要时只保留模型缓存和推理队列。
- 图片文件由业务 API 服务统一存储和管理。

当前已有的 `service.py` 更接近“AI 推理服务 + Web 演示页”的混合体。后续产品化时，应逐步拆分为：

- `app` 或 `backend`：业务 API 服务。
- `inference_service` 或 `ai_service`：AI 推理服务。

第一阶段也可以暂时运行在同一仓库、同一机器上，但进程和模块边界要先设计清楚。

### 5.2 服务通信方式

MVP 阶段建议使用内部 HTTP API：

```text
iOS/Web Client -> Business API -> AI Inference API
```

业务 API 服务把待识别图片或 crop 发送给 AI 推理服务，AI 推理服务返回检测框、crop 识别结果和耗时信息。

中后期批量任务建议引入队列：

```text
Business API -> Task Queue -> AI Worker / Inference Service
```

推荐演进路径：

1. 先用内部 HTTP 调用，便于开发和调试。
2. 批量任务变重后，引入 Redis + RQ/Celery/Dramatiq。
3. GPU 推理压力变大后，把 AI 推理服务部署到专用 GPU 机器。

内部 HTTP 接口只在内网或本机开放，不直接暴露给 iOS/Web 客户端。

### 5.3 逻辑模块

后端建议逐步拆成以下模块：

业务 API 服务模块：

- `api`：客户端 HTTP 路由层。
- `auth`：注册、登录、当前用户、密码哈希、会话。
- `db`：数据库连接、模型、迁移。
- `storage`：原图、crop、缩略图的保存和 URL 生成。
- `photos`：图片上传、查询、删除。
- `observations`：检测框、crop、观察记录。
- `identifications`：AI 建议、用户确认、人工修正。
- `collections`：个人图鉴聚合。
- `imports`：批量导入任务和任务项。
- `inference_client`：调用 AI 推理服务的内部客户端。

AI 推理服务模块：

- `inference_api`：内部推理 HTTP 接口。
- `detector`：封装现有 `birdcut.py`。
- `recognizer`：封装现有 `bird_recognition.py`。
- `batching`：检测和识别批处理队列。
- `model_lifecycle`：模型加载、预热、设备信息和关闭。

当前代码可以先不大拆，但新功能应按这些边界生长。

### 5.4 请求链路

典型单图链路：

1. 客户端上传图片。
2. 业务 API 服务校验登录态。
3. 业务 API 服务保存原图。
4. 业务 API 服务创建 `photos` 记录，状态为 `processing`。
5. 业务 API 服务调用 AI 推理服务的分析接口。
6. AI 推理服务读取请求图片，执行 YOLO 检测。
7. AI 推理服务对检测到的 crop 执行 BioCLIP 识别。
8. AI 推理服务返回检测框、AI Top-K 结果、耗时和设备信息。
9. 业务 API 服务保存 crop 文件。
10. 业务 API 服务创建 `bird_observations` 记录。
11. 业务 API 服务创建 `identifications` 记录。
12. 业务 API 服务把 `photos.status` 更新为 `ready`。
13. 客户端展示结果。
14. 上传者确认或修正物种。
15. 业务 API 服务更新确认结果。
16. 业务 API 服务更新上传者的个人图鉴。

### 5.5 存储层

本地开发目录建议：

```text
storage/
  originals/
    2026/
      07/
        user_{user_id}/
          {photo_id}_{hash_prefix}.jpg
  crops/
    2026/
      07/
        user_{user_id}/
          {observation_id}.png
  thumbs/
    2026/
      07/
        user_{user_id}/
          {photo_id}.jpg
  imports/
    {job_id}/
      raw/
      extracted/
```

数据库只保存相对路径，例如：

```text
originals/2026/07/user_1/42_a1b2c3.jpg
```

对外访问时由后端生成 URL：

```text
/media/originals/2026/07/user_1/42_a1b2c3.jpg
```

后续迁移到对象存储时，只需要替换 `storage` 模块。

### 5.6 AI 推理服务接口草案

AI 推理服务提供内部接口，不直接面向客户端。

```text
GET  /internal/health
GET  /internal/models
POST /internal/analyze-image
POST /internal/recognize-crops
POST /internal/detect
POST /internal/recognize-box
```

`POST /internal/analyze-image`：

- 输入：一张图片文件，检测参数，识别 Top-K。
- 输出：图片尺寸、检测结果、每个 crop 的 Top-K 识别结果、耗时、设备信息。
- 适用：业务 API 服务上传单图后一次性完成检测和识别。

`POST /internal/recognize-crops`：

- 输入：一个或多个 crop 图片。
- 输出：每个 crop 的 Top-K 识别结果。
- 适用：业务 API 服务已有 crop，需要单独重新识别。

`POST /internal/detect`：

- 输入：一张图片。
- 输出：检测框和检测置信度，不做物种识别。
- 适用：未来需要分阶段处理或调试检测质量。

`POST /internal/recognize-box`：

- 输入：原图和框选坐标，或业务 API 服务裁好的 crop。
- 输出：Top-K 识别结果。
- 适用：手动框选观察记录。

AI 推理服务返回值中不包含：

- 用户 ID。
- 鉴定确认状态。
- 图鉴更新结果。
- 图片访问权限。
- 数据库主键决策。

这些都由业务 API 服务负责。

## 6. 数据状态设计

### 6.1 Photo 状态

`photos.status`：

- `uploaded`：原图已保存，尚未进入识别。
- `processing`：检测或识别中。
- `ready`：检测和识别流程完成。
- `failed`：处理失败。
- `deleted`：用户删除，逻辑删除。

状态流转：

```text
uploaded -> processing -> ready
uploaded -> processing -> failed
ready -> deleted
failed -> deleted
failed -> processing
```

说明：

- 单图同步识别时，可以创建后立即进入 `processing`。
- 批量任务中，图片可能先停留在 `uploaded`，再由 worker 处理。
- 删除建议先做逻辑删除，避免误删文件。

### 6.2 Observation 状态

`bird_observations.status`：

- `detected`：检测到鸟并保存 crop。
- `recognized`：已有 AI 鉴定建议。
- `confirmed`：上传者已确认物种。
- `rejected`：上传者认为不是鸟或不需要保留。
- `failed`：该观察记录处理失败。

状态流转：

```text
detected -> recognized -> confirmed
detected -> recognized -> rejected
detected -> failed
recognized -> failed
confirmed -> rejected
rejected -> confirmed
```

说明：

- `rejected` 用于处理误检。
- 已确认记录允许重新修正，但需要记录更新时间。

### 6.3 Identification 状态

`identifications.status`：

- `suggested`：AI 已给出建议。
- `confirmed`：上传者接受某个建议。
- `corrected`：上传者手动改成另一个物种。
- `unknown`：上传者标记为未知鸟类。

说明：

- `suggested` 保存完整 Top-K。
- `confirmed` 通常来自 Top-K 之一。
- `corrected` 可能来自手动搜索物种。
- `unknown` 用于暂时无法确定但仍想保留观察记录。

### 6.4 Import Job 状态

`import_jobs.status`：

- `pending`：任务已创建，尚未开始。
- `running`：任务处理中。
- `completed`：所有任务项处理结束，且无失败。
- `completed_with_errors`：处理结束，但存在失败项。
- `failed`：任务整体失败。
- `cancelled`：用户取消。

状态流转：

```text
pending -> running -> completed
pending -> running -> completed_with_errors
pending -> running -> failed
pending -> cancelled
running -> cancelled
completed_with_errors -> running
failed -> running
```

## 7. 单张图片自动鉴定流程

### 7.1 用户流程

1. 用户登录。
2. 进入上传页面。
3. 选择一张图片。
4. 点击“上传并鉴定”。
5. 页面显示上传和鉴定进度。
6. 识别完成后，页面显示：
   - 原图。
   - 检测框。
   - 每只鸟的 crop。
   - 每只鸟的 Top-K AI 建议。
   - 检测置信度。
7. 上传者逐个确认：
   - 接受某个 AI 建议。
   - 搜索并选择其他物种。
   - 标记为未知。
   - 标记为误检。
8. 用户确认后，系统更新个人图鉴。
9. 图片进入共享相册，其他登录用户可以浏览结果。

### 7.2 业务 API 流程

1. 校验用户登录态。
2. 接收 `multipart/form-data`。
3. 校验文件类型和大小。
4. 读取图片，执行 EXIF 方向修正。
5. 计算图片 hash。
6. 保存原图。
7. 生成缩略图。
8. 创建 `photos`：
   - `status = processing`
   - `user_id = current_user.id`
9. 调用 AI 推理服务 `POST /internal/analyze-image`。
10. 接收 AI 推理服务返回的检测框、crop 图像或 crop 编码、Top-K 识别结果和耗时信息。
11. 如果没有检测到鸟：
    - 业务 API 服务仍将图片保存为 `ready`。
    - 前端提示“未检测到鸟”。
    - 上传者可以后续手动框选添加 observation。
12. 为每个 AI 返回的 crop：
    - 保存 crop 文件。
    - 创建 `bird_observations`。
13. 为每个 observation 创建 `identifications`，状态为 `suggested`。
14. 保存 AI 推理元数据：
    - 模型名称。
    - 模型版本。
    - 设备信息。
    - 检测耗时。
    - 识别耗时。
15. 更新 `photos.status = ready`。
16. 返回图片详情聚合结构。

### 7.3 AI 推理服务流程

1. 接收业务 API 服务传入的图片。
2. 读取图片并标准化方向和颜色格式。
3. 调用 YOLO 检测鸟类区域。
4. 如有需要，按推理服务内部策略执行低阈值重试或 full image fallback。
5. 生成 crop。
6. 批量调用 BioCLIP 识别 crop。
7. 返回结构化结果：
   - 图片尺寸。
   - crop 列表。
   - 检测框。
   - 检测置信度。
   - 检测来源。
   - 每个 crop 的 Top-K 识别结果。
   - 设备信息。
   - 耗时信息。

AI 推理服务不写业务数据库，也不更新用户图鉴。

### 7.4 失败处理

可能失败点：

- 文件不是图片。
- 图片过大。
- 图片损坏。
- 原图保存失败。
- AI 推理服务不可用。
- YOLO 推理失败。
- BioCLIP 推理失败。
- 数据库写入失败。

处理原则：

- 图片无法读取：不创建 photo，直接返回 400。
- 原图保存失败：不创建 photo 或创建后立即标记 failed。
- AI 推理服务超时或返回错误：`photos.status = failed`，保存错误信息，允许后续重试。
- 单个 crop 识别失败：photo 可进入 `ready`，对应 observation 标记 failed。
- 数据库写入失败：不要留下无法追踪的孤儿文件；至少写入错误日志。

## 8. 手动框选鉴定流程

### 8.1 使用场景

手动框选用于：

- 自动检测漏掉了鸟。
- 上传者想指定图中某只鸟。
- 检测框太大或太小。
- 一张图中有多个鸟，上传者想补充观察记录。

### 8.2 用户流程

1. 上传者打开图片详情页。
2. 点击“手动添加观察”。
3. 在原图上框选一只鸟。
4. 点击“识别选区”。
5. 系统生成 crop 并返回 Top-K。
6. 上传者确认或修正。
7. 该观察记录加入图片详情和个人图鉴。

### 8.3 业务 API 流程

1. 校验用户是图片所有者。
2. 接收 `photo_id` 和框选坐标。
3. 校验坐标不越界且区域足够大。
4. 从已保存原图读取图片。
5. 裁剪选区并保存 crop。
6. 创建 `bird_observations`：
   - `detection_source = manual`
   - `status = detected`
7. 调用 AI 推理服务 `POST /internal/recognize-crops` 或 `POST /internal/recognize-box`。
8. 接收 Top-K 识别结果。
9. 创建 `identifications`。
10. 将 observation 状态更新为 `recognized`。
11. 保存 AI 推理元数据。
12. 返回新的 observation 详情。

### 8.4 AI 推理服务流程

1. 接收业务 API 服务传入的 crop，或接收原图和框选坐标。
2. 如果收到原图和坐标，由 AI 推理服务裁剪选区。
3. 对 crop 执行 BioCLIP 识别。
4. 返回 Top-K 识别结果、设备信息和耗时。

AI 推理服务不判断该 observation 是否应进入图鉴。

## 9. 鉴定确认和修正流程

### 9.1 接受 AI 建议

上传者点击某个 Top-K 建议的“确认”。

业务 API 服务：

1. 校验 observation 所属图片归当前用户。
2. 查找或创建对应 `species`。
3. 更新 `identifications`：
   - `confirmed_species_id`
   - `confirmed_by_user_id`
   - `confirmed_at`
   - `status = confirmed`
4. 更新 `bird_observations.status = confirmed`。
5. 调用图鉴更新逻辑。
6. 返回更新后的 observation 和 collection entry。

### 9.2 人工修正物种

上传者可以通过物种搜索框选择一个不在 Top-K 中的物种。

业务 API 服务：

1. 校验权限。
2. 查找或创建 `species`。
3. 保留原始 AI Top-K。
4. 更新确认物种，并设置 `status = corrected`。
5. 更新图鉴。

### 9.3 标记未知

上传者不确定物种时，可以标记为“未知鸟类”。

业务 API 服务：

1. 更新 `identifications.status = unknown`。
2. `bird_observations.status` 可以保持 `recognized`。
3. 不写入 `collection_entries`。

### 9.4 标记误检

上传者认为该 crop 不是鸟。

业务 API 服务：

1. 更新 `bird_observations.status = rejected`。
2. 不写入图鉴。
3. 如果此前已经写入图鉴，需要重新计算该物种的 collection entry。

### 9.5 重新修正后的图鉴一致性

如果上传者把已确认的观察记录从物种 A 改为物种 B：

1. 更新 identification。
2. 重新计算用户的物种 A collection entry。
3. 更新或创建物种 B collection entry。

第一版实现可以采用简单策略：

- 每次确认或修正后，基于该用户全部 confirmed observations 重新计算相关物种的计数。
- 数据量变大后再做增量更新。

## 10. 个人图鉴流程

### 10.1 图鉴生成规则

图鉴项由用户已确认观察记录生成。

一个物种进入图鉴的条件：

- observation 属于该用户上传的图片。
- observation 状态为 `confirmed`。
- identification 有 `confirmed_species_id`。
- observation 没有被删除或 rejected。

### 10.2 图鉴项内容

图鉴页每个物种建议展示：

- 中文名，若无则显示英文 common name。
- 学名。
- 首次观察时间。
- 最近观察时间。
- 观察次数。
- 代表图片。
- 最近一次照片。

### 10.3 代表图片选择

第一版规则：

- 如果用户手动设置过代表图，优先使用手动设置。
- 否则使用首次确认该物种的观察记录 crop。

后续可优化：

- 使用最高置信度图片。
- 使用用户收藏图片。
- 使用画质评分最高图片。

## 11. 共享相册和图片详情流程

### 11.1 共享图片流

共享图片流展示系统内 `status = ready` 且未删除的图片。所有登录用户都可以访问。

排序默认：

- 按上传时间倒序。

可选筛选：

- 物种。
- 用户。
- 时间。
- 地点。
- 是否已确认。

列表卡片展示：

- 缩略图。
- 上传用户。
- 上传时间。
- 已识别鸟类数量。
- 已确认物种标签。

### 11.2 图片详情页

图片详情页展示：

- 原图。
- 上传者。
- 上传时间。
- 检测框叠加层。
- observation 列表。
- 每个 observation 的 crop。
- AI Top-K 建议。
- 上传者确认结果。

权限规则：

- 所有登录用户可看。
- 只有上传者可编辑。

### 11.3 用户主页

用户主页展示：

- 用户昵称和头像。
- 用户上传图片。
- 用户图鉴统计。
- 最近确认物种。

所有登录用户都可以查看其他用户主页。

## 12. 批量导入流程

### 12.1 用户流程

1. 用户进入批量导入页。
2. 选择多个图片或上传 zip。
3. 点击开始导入。
4. 系统创建导入任务。
5. 页面显示任务进度：
   - 总数。
   - 已处理。
   - 成功。
   - 失败。
   - 当前处理文件。
6. 用户可以进入任务详情查看每张图片状态。
7. 任务完成后，成功图片进入“我的上传”和共享相册。
8. 失败项可以单独重试。

### 12.2 业务 API 流程

1. 校验用户登录态。
2. 接收多个文件或 zip。
3. 创建 `import_jobs`：
   - `status = pending`
   - `total_count`
4. 为每个文件创建 `import_items`：
   - `status = pending`
5. 后台 worker 取任务。
6. 更新 job 为 `running`。
7. 逐个处理 item：
   - 保存原图。
   - 创建 photo。
   - 调用 AI 推理服务分析图片。
   - 保存 AI 返回的 crops。
   - 创建 observations。
   - 保存 identifications。
   - item 标记 success 或 failed。
8. 更新 job 计数。
9. 全部结束后：
   - 无失败：`completed`
   - 有失败：`completed_with_errors`

业务 API 服务负责：

- 接收导入文件。
- 创建任务和任务项。
- 管理任务状态。
- 持久化图片、crop 和识别结果。
- 处理失败重试。

业务 API 服务不负责：

- 加载模型。
- 持有 GPU。
- 执行 YOLO 或 BioCLIP 推理。

### 12.3 AI 推理服务流程

1. 接收业务 API 服务发送的待分析图片。
2. 使用内部模型队列调度检测和识别。
3. 返回检测框、crop、Top-K 识别结果、设备信息和耗时。
4. 如果单张图片推理失败，返回结构化错误，业务 API 服务将对应 import item 标记为 failed。

AI 推理服务负责控制 GPU 并发，避免多个进程重复加载模型。

### 12.4 批量任务并发策略

第一版建议：

- 业务 API worker 可以有多个，但它们都通过同一个 AI 推理服务发起推理。
- AI 推理服务内部只维护受控数量的检测和识别队列。
- 批量任务可以逐图提交给 AI 推理服务。
- AI 推理服务可以复用现有 recognition batcher。
- 避免每个业务 worker 都加载一份大模型。

后续扩展：

- 业务 API 服务和 AI 推理服务部署到不同机器。
- Redis 队列负责业务任务调度。
- GPU worker 数量按显存配置。
- AI 推理服务可以横向扩展为多个实例，并由业务 API 服务或队列分发任务。

### 12.5 Zip 导入规则

支持：

- `.zip`
- 内部图片格式：jpg、jpeg、png、webp、bmp。

忽略：

- 隐藏文件。
- 非图片文件。
- 目录结构本身。

安全规则：

- 解压时防止路径穿越。
- 限制总文件数。
- 限制总解压大小。
- 限制单张图片大小。

## 13. iOS App 客户端设计

### 13.1 客户端定位

iOS App 是最终主要客户端，Web 前端保留为：

- 开发调试台。
- 桌面端临时入口。
- 后续轻量管理界面。

iOS App 应优先服务移动端自然流程：

- 从系统相册选择鸟图。
- 拍摄后立即上传。
- 查看识别进度。
- 快速确认鉴定结果。
- 浏览共享相册。
- 查看自己的鸟类图鉴。

### 13.2 技术选型

推荐使用原生 iOS：

- Swift。
- SwiftUI 作为主要 UI 框架。
- PhotosUI 的 `PhotosPicker` 作为系统相册选择入口。
- URLSession 负责 API 请求、图片上传和图片下载。
- Keychain 保存登录凭证或 refresh token。
- Core Location 仅在用户明确需要记录地点时启用。

选择原生 iOS 的原因：

- 图片选择、相册权限、上传任务、缓存和系统体验更自然。
- 未来可更好支持拍摄、后台上传、通知和本地缓存。
- SwiftUI 可以覆盖当前阶段大部分界面需求。

### 13.3 App 信息架构

第一版建议使用 Tab 结构：

```text
共享相册
上传
我的图鉴
我的
```

各 Tab 职责：

- 共享相册：浏览所有登录用户上传的图片。
- 上传：选择图片、拍摄图片、上传并查看处理进度。
- 我的图鉴：按物种聚合展示个人确认记录。
- 我的：账号资料、我的上传、批量导入、设置、退出登录。

未登录状态：

- 启动 App 后进入登录/注册流程。
- 登录成功后进入主 Tab。

### 13.4 iOS 页面规划

第一版页面：

- `LoginView`：登录。
- `RegisterView`：注册。
- `AlbumFeedView`：共享相册流。
- `PhotoDetailView`：图片详情、检测框、鉴定结果。
- `UploadView`：图片选择、预览、上传。
- `UploadProgressView`：上传和识别进度。
- `ObservationReviewView`：逐个确认或修正识别结果。
- `ManualCropView`：手动框选观察记录。
- `CollectionView`：我的图鉴。
- `SpeciesDetailView`：某个物种的观察记录列表。
- `MyPhotosView`：我的上传。
- `ImportJobsView`：批量导入任务。
- `ImportJobDetailView`：批量导入详情。
- `ProfileView`：用户资料和设置。

### 13.5 iOS 上传流程

iOS 单图上传流程：

1. 用户进入上传 Tab。
2. 使用 `PhotosPicker` 选择一张或多张图片。
3. App 在本地生成预览。
4. App 可在本地做基础压缩或尺寸限制。
5. App 调用 `POST /photos` 上传。
6. 服务端返回 `photo_id` 和初始状态。
7. App 进入进度页。
8. App 轮询 `GET /photos/{photo_id}` 或订阅后续实时通道。
9. 状态变为 `ready` 后进入结果确认页。
10. 用户确认或修正结果。

第一版建议使用轮询，后续再考虑 WebSocket 或 Server-Sent Events。

### 13.6 iOS 批量导入流程

iOS 批量导入流程：

1. 用户在上传 Tab 中切换到“批量”。
2. 使用系统相册多选图片。
3. App 创建本地待上传队列。
4. App 逐个上传文件或一次提交多文件。
5. 后端创建 `import_job`。
6. App 展示 job 进度。
7. 任务完成后提供入口查看成功图片和失败项。

第一版建议：

- iOS 端先支持多图选择。
- zip 导入可以先留给 Web 或后续版本。
- 批量上传需要支持暂停、失败重试和断点状态展示。

### 13.7 iOS 鉴定确认体验

移动端确认应尽量轻：

- 每个 observation 用卡片展示 crop。
- Top-K 结果用可点选列表展示。
- 默认突出 Top-1，但不自动确认。
- 提供“不是鸟”“不确定”“搜索物种”。
- 确认后卡片进入已完成状态。
- 所有 observation 确认完成后，提示图鉴已更新。

图片详情中，非上传者看到只读结果；上传者看到确认、修正、手动框选入口。

### 13.8 iOS 本地缓存

第一版缓存目标：

- 缩略图列表滚动流畅。
- 图片详情打开后可短期复用。
- 离线时能看到最近浏览的列表缓存，但不承诺完整离线编辑。

建议缓存：

- 用户信息。
- 最近的共享相册分页结果。
- 我的图鉴摘要。
- 图片缩略图。
- 待上传任务状态。

本地缓存可以先用：

- URLCache。
- 文件缓存目录。
- 后续如需要复杂离线状态，再引入 SQLite/Core Data。

### 13.9 iOS 网络和会话

建议：

- API 使用 HTTPS。
- 登录后服务端返回短期 access token 和长期 refresh token，或使用安全 cookie 方案。
- iOS 端凭证存 Keychain。
- 上传接口需要返回可恢复的任务状态。
- 所有写操作应处理 401、网络失败、超时和服务端错误。

客户端网络层建议封装：

- `APIClient`：统一请求。
- `AuthService`：登录、刷新、退出。
- `PhotoService`：上传、详情、列表。
- `ObservationService`：确认、修正、手动框选。
- `CollectionService`：图鉴。
- `ImportService`：批量任务。

### 13.10 iOS 和业务 API 的配合要求

为了让 iOS 体验顺，业务 API 服务需要提供：

- 分页列表接口。
- 图片缩略图 URL。
- 原图和 crop 的稳定 URL。
- 上传后可查询的处理状态。
- 统一错误结构。
- 幂等确认接口。
- 批量任务进度接口。
- 当前用户接口。

建议所有列表接口都支持：

- `limit`
- `cursor` 或 `page`
- 稳定排序字段

图片详情接口应一次返回移动端所需聚合数据：

- photo。
- uploader。
- observations。
- identifications。
- confirmed species。
- 当前用户是否为上传者。

### 13.11 iOS 版本路线

#### iOS M0：Web 原型配合阶段

目标：

- 业务 API、AI 推理服务和 Web 原型先跑通。
- iOS 只做接口验证或简单壳。

#### iOS M1：单图闭环

目标：

- 登录。
- 相册选图。
- 单图上传。
- 查看处理进度。
- 查看识别结果。
- 确认鉴定。
- 查看我的图鉴。

#### iOS M2：共享浏览

目标：

- 共享相册流。
- 图片详情。
- 用户主页。
- 我的上传。
- 图鉴物种详情。

#### iOS M3：批量导入

目标：

- 多图选择。
- 批量上传队列。
- 任务进度。
- 失败重试。

#### iOS M4：体验增强

目标：

- 拍照上传。
- 本地缓存增强。
- 推送通知。
- 地点记录。
- 更完整的图鉴筛选。

## 14. API 设计草案

本节分为两类 API：

- 客户端 API：由业务 API 服务提供，面向 iOS 和 Web。
- 内部推理 API：由 AI 推理服务提供，只面向业务 API 服务或后台 worker。

### 14.1 客户端 API：Auth

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /me
PATCH /me
```

### 14.2 客户端 API：Photos

```text
POST /photos
GET  /photos/{photo_id}
GET  /me/photos
GET  /feed/photos
DELETE /photos/{photo_id}
```

`POST /photos` 建议支持参数：

- `file`
- `auto_analyze`

如果 `auto_analyze = true`，上传后立即进入鉴定流程。

### 14.3 客户端 API：Observations

```text
GET  /photos/{photo_id}/observations
POST /photos/{photo_id}/observations/manual
GET  /observations/{observation_id}
PATCH /observations/{observation_id}
DELETE /observations/{observation_id}
```

### 14.4 客户端 API：Identification

```text
POST /observations/{observation_id}/identify
POST /observations/{observation_id}/confirm
POST /observations/{observation_id}/correct
POST /observations/{observation_id}/mark-unknown
POST /observations/{observation_id}/reject
```

### 14.5 客户端 API：Collections

```text
GET /me/collection
GET /users/{user_id}/collection
GET /me/collection/{species_id}
PATCH /me/collection/{species_id}
```

### 14.6 客户端 API：Imports

```text
POST /imports
GET  /imports
GET  /imports/{job_id}
GET  /imports/{job_id}/items
POST /imports/{job_id}/retry
POST /imports/{job_id}/cancel
```

### 14.7 客户端 API：Species

```text
GET /species
GET /species/{species_id}
GET /species/search
```

### 14.8 客户端 API：Users

```text
GET /users/{user_id}
GET /users/{user_id}/photos
GET /users/{user_id}/collection
```

### 14.9 内部推理 API

```text
GET  /internal/health
GET  /internal/models
POST /internal/analyze-image
POST /internal/detect
POST /internal/recognize-crops
POST /internal/recognize-box
```

内部推理 API 的约束：

- 不接受客户端直接访问。
- 不处理用户登录态。
- 不读写业务数据库。
- 不更新图鉴。
- 不决定最终鉴定结果。
- 只返回检测、识别、耗时、设备和模型信息。

## 15. 数据库表设计草案

### 15.1 users

```text
id
email
username
display_name
password_hash
avatar_path
role
status
created_at
updated_at
```

### 15.2 photos

```text
id
user_id
filename
original_path
thumb_path
content_hash
width
height
status
error_message
taken_at
location_name
latitude
longitude
created_at
updated_at
deleted_at
```

### 15.3 bird_observations

```text
id
photo_id
crop_path
bbox_x1
bbox_y1
bbox_x2
bbox_y2
detection_confidence
detection_source
status
created_at
updated_at
deleted_at
```

### 15.4 identifications

```text
id
observation_id
model_name
model_version
top_k_results
suggested_species_id
confirmed_species_id
confirmed_by_user_id
status
confirmed_at
created_at
updated_at
```

### 15.5 species

```text
id
scientific_name
common_name
chinese_name
genus
family
order_name
source
external_id
created_at
updated_at
```

### 15.6 collection_entries

```text
id
user_id
species_id
first_observation_id
representative_observation_id
representative_photo_id
observation_count
first_seen_at
last_seen_at
created_at
updated_at
```

### 15.7 import_jobs

```text
id
user_id
status
source_type
total_count
processed_count
success_count
failed_count
error_message
created_at
started_at
finished_at
```

`source_type`：

- `multi_file`
- `zip`

### 15.8 import_items

```text
id
job_id
photo_id
filename
status
error_message
created_at
started_at
finished_at
```

## 16. Web 原型页面设计

Web 前端短期继续承担原型和调试作用。

建议第一版 Web 页面包括：

- 登录页。
- 注册页。
- 上传识别页。
- 图片详情页。
- 我的上传页。
- 我的图鉴页。
- 共享相册页。
- 批量导入页。
- 批量任务详情页。

### 16.1 上传识别页

主要区域：

- 图片上传区。
- 识别按钮。
- 原图预览。
- 识别结果列表。

结果列表中每个 observation 展示：

- crop。
- AI Top-K。
- 确认按钮。
- 修正入口。
- 标记未知。
- 标记误检。

### 16.2 图片详情页

主要区域：

- 原图大图预览。
- 检测框叠加。
- observation 侧栏。
- 鉴定状态。
- 手动添加观察按钮。

### 16.3 我的图鉴页

主要区域：

- 物种卡片网格。
- 搜索和筛选。
- 统计信息。
- 物种详情抽屉或页面。

### 16.4 共享相册页

主要区域：

- 图片流。
- 物种筛选。
- 用户筛选。
- 时间排序。
- 图片卡片。

### 16.5 批量导入页

主要区域：

- 多文件上传或 zip 上传。
- 开始导入按钮。
- 最近导入任务列表。

任务详情展示：

- 总进度。
- 成功和失败数量。
- 单项列表。
- 失败原因。
- 重试按钮。

## 17. 鉴权和访问控制设计

### 17.1 登录态

第一版建议：

- Web 场景使用 HttpOnly cookie session 或 JWT cookie。
- iOS 场景使用 token，并保存在 Keychain。
- API 内部通过 `get_current_user` 依赖获取当前用户。

### 17.2 内容访问

访问规则：

- 所有内容接口都要求登录。
- 登录用户可以读取系统内未删除图片、观察记录、鉴定结果、用户主页和图鉴。
- 只有上传者可以修改自己的图片和观察记录。
- 只有上传者可以确认、修正、标记未知或标记误检。

### 17.3 编辑权限

只有上传者可以：

- 删除图片。
- 添加手动 observation。
- 确认或修正鉴定。
- 标记误检。

## 18. 错误和边界场景

### 18.1 无鸟图片

处理方式：

- 允许保存图片。
- `photo.status = ready`。
- observations 为空。
- 前端显示“未检测到鸟”。
- 上传者可以手动框选添加 observation。

### 18.2 多鸟图片

处理方式：

- 每个检测框生成一个 observation。
- 上传者逐个确认。
- 一张图片可以贡献多个物种到图鉴。

### 18.3 重复上传

第一版：

- 计算 `content_hash`。
- 同一用户重复上传同 hash 图片时给出提示。
- 允许继续上传，避免误伤裁剪或元数据不同的情况。

后续：

- 可提供“跳转到已有图片”。
- 可在批量导入中自动跳过重复项。

### 18.4 模型低置信度

处理方式：

- 仍展示 Top-K，但用“低置信度”提示。
- 不自动确认。
- 鼓励上传者手动修正或标记未知。

### 18.5 图片删除

第一版建议逻辑删除：

- `photos.deleted_at` 设置时间。
- 列表中不再展示。
- 文件清理可以后续做异步回收。

## 19. 近期实现顺序建议

### 19.1 第一小步：持久化单图识别

目标：

- 可以先用临时默认用户或简单登录。
- 把上传、识别、保存、详情查询跑通。
- 同时建立业务 API 服务与 AI 推理服务的调用边界。

任务：

1. 将现有识别接口整理成 AI 推理服务内部 API。
2. 增加业务 API 服务骨架。
3. 增加业务 API 到 AI 推理服务的 `inference_client`。
4. 增加数据库初始化。
5. 增加 `users`、`photos`、`bird_observations`、`identifications`、`species`。
6. 增加 storage 模块。
7. 新增业务 API `POST /photos`。
8. 新增业务 API `GET /photos/{photo_id}`。
9. 前端可以展示已保存的 photo 详情。

### 19.2 第二小步：确认结果和图鉴

目标：

- 让上传者确认 AI 结果。
- 确认后形成个人图鉴。

任务：

1. 新增确认接口。
2. 新增人工修正接口。
3. 新增 `collection_entries`。
4. 新增我的图鉴接口。
5. 前端增加确认和图鉴页。

### 19.3 第三小步：正式多用户

目标：

- 不同用户的数据可追溯。
- 所有内容登录后可见。
- 编辑权限限定在上传者。

任务：

1. 注册。
2. 登录。
3. 当前用户。
4. 图片归属。
5. 访问控制。

### 19.4 第四小步：共享相册

目标：

- 登录用户可以浏览系统内图片和鉴定结果。

任务：

1. 共享图片流。
2. 用户主页。
3. 图片详情权限控制。

### 19.5 第五小步：iOS M1 单图闭环

目标：

- iOS App 跑通登录、选图、上传、鉴定、确认、图鉴。

任务：

1. 建立 iOS 项目。
2. 登录和会话。
3. PhotosPicker 选图。
4. 单图上传。
5. 图片处理状态查询。
6. 鉴定结果确认。
7. 我的图鉴。

### 19.6 第六小步：批量导入

目标：

- 支持多图导入和后台处理。

任务：

1. `import_jobs`。
2. `import_items`。
3. 多文件上传。
4. 后台处理。
5. 进度查询。
6. 失败重试。

## 20. 需要进一步确认的问题

后续需要你指导确认的问题：

1. 第一版是否必须支持完整注册登录，还是可以先用本地默认用户把持久化跑通？
2. 鉴定结果是否必须人工确认后才进入图鉴？
3. 是否需要中文物种名作为第一版硬需求？
4. 批量导入第一版是多文件上传即可，还是必须支持 zip？
5. 是否要允许其他用户对非自己上传的图片提出鉴定建议？
6. 是否需要保留完整 AI 历史记录，还是每个 observation 只保留最新一次 AI 建议？
7. 删除图片时，是否需要立即删除磁盘文件？
8. iOS 第一版是否要支持拍照，还是先只支持系统相册选择？
9. iOS 第一版是否需要离线浏览最近缓存？
10. 是否要把 Web 前端迁移到 Vite + React + TypeScript 后再继续产品化？

## 21. 当前推荐取舍

为了尽快形成可用闭环，当前推荐：

- 先不重写 ML 识别部分。
- 先明确业务 API 服务和 AI 推理服务边界。
- 先做数据库和文件持久化。
- 先实现单图上传、保存和详情。
- 再做确认结果和个人图鉴。
- 所有内容先统一要求登录。
- 图片不提供单独的展示范围开关。
- 登录用户之间默认可以互相浏览图片和鉴定结果。
- iOS 先做 M1 单图闭环，不急着一开始做批量和拍照。
- 批量导入放在基础数据模型稳定之后。
- Web 前端继续作为原型和调试入口，iOS 逐步成为主客户端。

最小可用闭环：

```text
登录用户 -> 上传图片 -> 自动检测识别 -> 保存结果 -> 上传者确认物种 -> 写入个人图鉴 -> 其他登录用户可浏览
```

这个闭环跑通后，Birdmark 就具备了从识别工具升级为鸟类相册产品的核心骨架。

## 22. iOS 设计参考

本节仅记录客户端规划时参考的 Apple 官方文档入口：

- SwiftUI：<https://developer.apple.com/documentation/swiftui>
- PhotosPicker：<https://developer.apple.com/documentation/PhotosUI/PhotosPicker>
- URLSession：<https://developer.apple.com/documentation/foundation/urlsession>
- Core Location：<https://developer.apple.com/documentation/corelocation>
