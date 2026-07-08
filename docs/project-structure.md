# Birdmark 项目结构

## 当前定位

当前仓库是 Birdmark 业务应用仓库，负责业务 API、Web 页面、数据持久化和后续 iOS 客户端规划。

AI 推理服务、ML 核心代码、模型文件、训练/评估脚本已经拆分到独立仓库：

```text
C:\Users\hg\project\birdmark-ai
```

## 当前结构

```text
birdmark/
  AGENTS.md
  README.md
  .gitignore
  start-api.bat

  apps/
    api/
      app/
        auth.py
        collections.py
        config.py
        database.py
        imports.py
        inference_client.py
        main.py
        observations.py
        photos.py
        species.py
        storage.py
      requirements.txt

    web/
      index.html
      app.js
      styles.css

    ios/

  docs/
    development-roadmap.md
    end-to-end-flow-design.md
    ios-app-v1-design.md
    project-structure.md
    task-checklist.md

  datasets/
  storage/
  res/
  logs/
  runs/
```

## 已迁移到 AI 仓库的内容

以下内容不再保留在当前业务仓库：

- `apps/inference/`
- `apps/inference_web/`
- `packages/birdmark_ml/`
- `packages/birdmark_common/`
- `scripts/`
- `models/`
- `birds/`
- `start.bat`

对应内容位于：

```text
C:\Users\hg\project\birdmark-ai
```

## 边界原则

- 当前仓库不直接加载模型。
- 当前仓库不直接 import YOLO、BioCLIP、torch 或 TensorRT 相关模块。
- 当前仓库通过 `apps/api/app/inference_client.py` 调用外部 AI 推理服务。
- AI 服务地址通过 `BIRDMARK_INFERENCE_URL` 配置，默认是 `http://127.0.0.1:8000`。
- `datasets/` 暂时仍留在当前工作区，不移动、不清理、不递归处理。
- `storage/`、`res/`、`logs/`、`runs/` 是本地运行产物，不做无关清理。
