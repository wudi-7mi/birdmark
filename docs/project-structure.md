# Birdmark 项目结构规划

## 目标

项目将逐步从单目录脚本结构，整理为适合长期开发的多模块结构：

- `apps/api/`：业务 API 服务，负责用户、图片、图鉴、批量任务和数据库。
- `apps/inference/`：AI 推理服务，负责 YOLO 检测、BioCLIP 识别、模型加载和推理队列。
- `apps/web/`：当前 Web 原型。
- `apps/ios/`：未来 iOS App。
- `packages/birdmark_ml/`：可复用 ML 核心代码。
- `packages/birdmark_common/`：未来业务 API 和推理服务共享工具。
- `scripts/`：下载、导出、评估、批处理等命令行脚本。

`datasets/` 正在下载数据，整理项目结构时不要移动、清理或递归处理该目录。

## 规划结构

```text
birdmark/
  AGENTS.md
  README.md
  .gitignore

  docs/
    development-roadmap.md
    end-to-end-flow-design.md
    project-structure.md
    task-checklist.md

  apps/
    api/
      app/

    inference/
      app/
        main.py
      requirements.txt
      requirements-tensorrt.txt

    web/
      index.html
      app.js
      styles.css

    ios/

  packages/
    birdmark_ml/
      birdcut.py
      bird_recognition.py

    birdmark_common/

  scripts/
    run_batch.py
    download_tpdc_birds.py
    export_tensorrt.py
    evaluate_classification.py
    yolotest.py

  models/
  datasets/
  storage/
  res/
  logs/
  runs/
  birds/
```

## 迁移原则

- 不移动 `datasets/`。
- 不移动 `models/`。
- 不清理 `res/`、`logs/`、`runs/`、`birds/`。
- 根目录保留 `start.bat` 作为本地启动入口。
- 业务 API 与 AI 推理服务分开生长。
- 当前优先保证 AI 推理服务和 Web 原型迁移后仍可启动。
