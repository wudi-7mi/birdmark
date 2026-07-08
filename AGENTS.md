# AGENTS.md

## 项目概览

Birdmark 是一个自有鸟类识别相册应用。当前仓库是业务应用仓库，负责 FastAPI 业务 API、轻量 React/Ant Design Web 页面、用户、图片、观察记录、鉴定确认、个人图鉴和批量导入任务。

AI 推理服务、模型文件、训练/评估脚本和 ML 封装已经拆分到独立仓库：

```text
C:\Users\hg\project\birdmark-ai
```

当前仓库不再保存 YOLO、BioCLIP、TensorRT engine、模型导出脚本或数据集处理脚本。业务 API 通过 HTTP 调用外部 AI 推理服务。

## 仓库结构

- `apps/api/`：业务 API 服务，负责用户、图片、图鉴、批量任务、数据库和客户端 API。
- `apps/web/`：业务 Web 页面，由业务 API 挂载。
- `apps/ios/`：未来 iOS App。
- `docs/`：产品规划、架构设计和开发路线文档。
- `storage/`：本地 SQLite、上传图片和生成媒体，通常不提交。
- `datasets/`：本地数据集。按大型外部资产处理，不要做无关扫描、改写或清理。

已迁移到 `birdmark-ai` 的内容：

- `apps/inference/`
- `apps/inference_web/`
- `packages/birdmark_ml/`
- `scripts/`
- `models/`
- `birds/`
- `start.bat`

## 工作原则

- 默认使用中文和用户沟通。
- 当前仓库聚焦业务产品化：数据持久化、多用户、相册、图鉴、批量任务、Web/iOS 客户端。
- AI 鉴定结果默认是“建议”，不要直接等同于用户确认的最终鉴定。
- 原图、裁剪图、检测框、AI Top-K 结果和用户确认结果需要能互相追溯。
- 数据库中保存图片路径和元数据，不直接保存图片二进制。
- 避免无关的大重构；改动应贴近当前任务。
- 工作区可能已有用户改动，不要回滚或覆盖无关修改。

## 后端约定

- 业务 API 服务负责用户、图片、相册、图鉴、批量任务、数据库和客户端 API。
- AI 推理服务在 `birdmark-ai` 仓库维护。
- 当前仓库不要直接 import AI/ML 模块，也不要重新引入模型加载逻辑。
- 当前仓库通过 `apps/api/app/inference_client.py` 调用外部 AI 推理服务。
- 外部 AI 服务地址由 `BIRDMARK_INFERENCE_URL` 配置，默认是 `http://127.0.0.1:8000`。
- 随着产品层增长，用户、图片、图鉴、批量任务等业务逻辑应继续拆到独立模块。
- 引入持久化迁移时，优先考虑 SQLAlchemy 和 Alembic。
- 开发期可以使用 SQLite，但模型设计应方便后续迁移到 PostgreSQL。
- 批量导入正式化时，应考虑任务表和后台队列，不要长期依赖单次 HTTP 请求完成大批量处理。

## 前端约定

- 当前前端使用 React CDN 和 Ant Design CDN。
- 未明确要求迁移前端工程时，保持现有前端技术栈和视觉风格。
- 不要把应用首页改成营销落地页；第一屏应优先是可用的上传、识别、浏览或管理界面。
- 页面设计应服务核心流程：上传、鉴定、确认、浏览、个人图鉴、批量导入。
- 修改前端后，应尽量人工验证登录、上传、识别、确认和图鉴主流程。

## 外部 AI 服务说明

- AI 推理服务负责 YOLO 检测、BioCLIP 识别、模型加载、GPU 管理和推理批处理。
- 当前仓库只依赖 AI 服务返回的检测框、crop 图、Top-K 识别结果和推理元数据。
- 如果本地没有启动 `birdmark-ai`，上传识别接口可能返回 502。
- 调整识别质量、模型参数、TensorRT、训练/评估脚本时，应在 `birdmark-ai` 仓库处理。

## 常用命令

启动业务 API：

```powershell
.\start-api.bat
```

直接启动业务 API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8100
```

启动外部 AI 服务：

```powershell
cd C:\Users\hg\project\birdmark-ai
.\start.bat
```

## 验证要求

- 修改后端接口后，优先做服务导入检查或启动检查。
- 修改前端后，尽量在浏览器中验证登录、上传、识别、确认和结果展示。
- 修改调用 AI 服务的协议后，需要同时检查 `birdmark-ai` 的接口兼容性。
- 如果本机未启动外部 AI 服务，要明确说明上传识别验证受限。
- 不要声称测试通过，除非确实运行过对应命令。

## 文档约定

- 产品规划和阶段路线放在 `docs/`。
- 当产品方向、架构选择或阶段计划发生变化时，更新 `docs/development-roadmap.md` 或相关设计文档。
- README 类使用说明、内部规划文档和 Codex 工作约定应保持分离。

## 文件和数据安全

- 不要删除用户上传图片、数据集、生成结果或日志，除非用户明确要求。
- 不要对 `datasets/`、`storage/`、`res/`、`runs/` 做批量清理操作，除非任务明确要求。
- 处理大文件目录时，优先读取目录摘要，不要无目的递归读取全部内容。
- 新增依赖前，应确认它对项目阶段确实必要。
