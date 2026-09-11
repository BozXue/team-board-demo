# 戴纳 AI 引导式视觉平台 · 全栈 MVP

一个「AI 帮你搭视觉方案」的平台：用一句话描述检测需求，平台自动诊断成像质量、推荐算法路线、生成可视化流程图，工程师在节点画布上微调参数，批量测试量化漏检/误报，发布后操作员只看到几个业务参数和 OK/NG 结果。

原型来源是 `ipsc_texture_classifier/`（局部纹理标准差 + Otsu + 形态学定位 iPSC 克隆的 Python 脚本），其算法已拆成平台内的可复用算子，脚本本身保持原样未改动。

```
需求描述 ──▶ AI 助手（意图识别 + 成像诊断 + 方案规划）
                    │
                    ▼
数据集/标注 ──▶ 节点流程（66 个算子，DAG 执行 + 结果缓存 + 逐节点预览）
                    │
                    ├─▶ 批量测试（良率 / 准确率 / 漏检 / 误报 / 误判回流）
                    ├─▶ 分类模型训练（LBP + SVM，小样本可用）
                    └─▶ 发布版本 ──▶ 运行页（操作员模式：仅业务参数 + 判定结果）
                                        │
                                        └─▶ 监控页（设备在线 / 推理量 / 置信度 / 耗时 / 逐次预测）
```

## 快速开始

```bash
cd /opt/AI-CV-platform

# 1) 后端依赖
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

# 2) 前端依赖
cd frontend && npm install && cd ..

# 3) 造两个演示项目（iPSC 克隆 + 合成布面污渍）
scripts/seed.sh

# 3b) 可选：再造一个跑 AI 分类器的项目，并生成推理流量喂给「监控」页
cd backend && ../.venv/bin/python -m scripts.seed_monitoring && cd ..

# 3c) 把 sample_projects/ 下的示例（如密封袋谷物分类）导入为平台项目
scripts/seed_samples.sh
#   默认每类 40 张；全量导入加 --all

# 4) 同时启动后端 + 前端
scripts/dev.sh
#   前端 http://127.0.0.1:5173
#   API 文档 http://127.0.0.1:8000/docs
```

可选：把 `backend/.env.example` 复制到仓库根目录改名 `.env`，填 `AICV_LLM_API_KEY` 后 AI 助手会调用大模型；**不填也能用**，此时走内置规则引擎，方案质量略降但结论可用、可离线部署。

自检：

```bash
scripts/check.sh          # 接口契约 + 端到端冒烟 + 前端类型检查 + 首屏渲染 + jsdom 挂载
```

> 注：本机 npm 在批量安装带跨平台可选依赖的包时会卡在 reify 阶段，`frontend/.npmrc` 里固定了 `os/cpu/libc`，这样 `npm install` 才能正常结束。

## 演示路径（5 分钟）

1. **项目页** → 打开「白布污渍检测（示例）」。
2. **数据页** → 左侧缩略图浏览、框选标注、右侧看直方图与成像诊断（曝光/对比度/清晰度/噪声/均匀性）。
3. **AI 助手页** → 输入「检查布面上的深色污渍，超过 500 像素算 NG」→ 生成方案 → 「应用到流程」。
4. **流程页** → 画布上逐节点看中间图像、耗时、日志；改参数自动重跑（结果缓存只重算下游）。ROI 节点可以「在图上框选」直接回填坐标。
5. **批量测试页** → 跑 20 张：当前演示数据可达 accuracy 1.0（TP 8 / TN 12），并给出调参建议；误判样本可一键回流训练集。
6. **发布** → **运行页** → 单次触发或连续检测（数据集回放 / 模拟相机），只暴露业务参数、显示良率与报警。
7. **模型页** → 用已标注的 20 张训练 LBP+SVM 分类器（交叉验证 0.95），可在流程里通过 AI 分类节点调用。
8. **监控页** → 顶部导航「监控」：全平台已部署模型的运行情况——设备在线/离线与各自推理量、每个模型的平均置信度与分布、平均/P95 耗时、良率趋势，以及逐次预测明细（点行看原图、测量值与判定原因）。点设备/模型/项目行即可筛选明细。
9. **设备页** → 模拟相机可连接/采图入库；工业相机、PLC、MES、机器人为**接口预留**，调用返回 501 并在界面标注「接口预留」。

## 目录结构

```
backend/
  app/
    core/            配置、SQLite/SQLAlchemy、统一错误 → HTTP 映射
    models.py        Project / ImageAsset / Annotation / PipelineVersion /
                     BatchRun+BatchResult / RuntimeSession+Record / ModelAsset / CopilotMessage
    engine/          流程引擎
      types.py       端口类型（image/mask/roi/regions/value/result/any）、参数规格与分级
      base.py        Node SDK（声明 inputs/outputs/params + 实现 process）
      registry.py    算子注册表（白名单，AI 只能生成表内节点）
      graph.py       DAG 解析、类型兼容校验、拓扑排序、环检测
      executor.py    执行器：缓存命中、逐节点计时、预览产物落盘、错误定位
      render.py      端口数据 → 预览图（掩膜叠色、区域轮廓、判定标注）
      algorithms/    纹理（局部标准差/LBP）、几何（轮廓/区域属性）等底层实现
      nodes/         66 个算子：输入/ROI/增强/滤波/分割/形态学/特征/测量/判定/AI/领域(iPSC)/输出
    services/        项目、数据集、标注(COCO/YOLO)、流程执行、批量、运行时、监控聚合、
                     成像诊断、模型训练推理、copilot/（意图·规划·顾问·LLM）、devices/（适配器）
    api/routes/      REST 路由：meta / projects / datasets / annotations /
                     batch / copilot / runtime / models / devices / monitoring
  scripts/           seed_demo.py（演示数据）· seed_monitoring.py（监控流量）·
                     smoke_api.py（端到端）· check_contracts.py（契约）
frontend/src/
  api/               client.ts（全部接口）+ types.ts（与后端字段一一对应）
  store/             app.ts（元数据/项目/模式/提示）· pipeline.ts（图编辑/执行/自动保存）
  components/        ImageViewer（缩放·平移·像素探针·ROI 绘制）· Histogram · DiagnosisPanel ·
                     pipeline/（NodeCard · NodeLibrary · ParamControl · PropertiesPanel · ResultsPanel）
  pages/             Projects · Data · Copilot · Pipeline · Batch · Models · Runtime ·
                     Monitor（模型监控）· Devices
data/                运行期数据（SQLite + 项目图片 + 预览缓存 + 模型文件），已 gitignore
```

## 核心设计

**节点即函数 + 元数据。** 算子声明端口与参数，执行、校验、缓存、可视化由引擎统一负责，所以新增算法不需要碰 UI：

```python
@register
class LocalStdTexture(Node):
    type = "local_std_texture"
    label = "Local Std Texture"
    category = "Filter"
    description = "局部标准差纹理图：iPSC 克隆等“靠纹理密度区分”的目标用它做前处理。"
    inputs = (PortSpec("image", PortType.IMAGE, "图像"),)
    outputs = (PortSpec("image", PortType.IMAGE, "纹理图"),)
    params = (ParamSpec("window", "int", 0, label="窗口", min=0, max=999, unit="px"),)

    def process(self, inputs, params, ctx):
        gray = self.as_gray(self.require_image(inputs))
        ...
        ctx.log(f"window={window}")
        return {"image": to_uint8(texture)}
```

**参数分级决定谁能改。** 每个参数标记 `engineer` / `business` / `locked`：工程师模式显示全部；发布时只把 `business` 参数暴露给运行页，并在服务端按声明的范围夹紧，操作员改不坏方案。

**缓存按“节点类型+参数+上游结果+图片”做键。** 调后段参数时前段直接命中缓存，画布上会标 `cache`，配合「只执行到此节点」可以快速试参。

**AI 助手是可校验的生成器。** 意图识别（任务类型、目标明暗、尺寸/数量约束）+ 成像诊断（曝光、对比度、清晰度、噪声、均匀性、纹理能量）→ 规划流程；LLM 输出必须通过注册表白名单、端口类型和参数范围校验，任何不合法的图直接退回规则引擎生成的方案，因此界面上永远拿到能跑的流程。

**数据采集只留接口。** `DeviceAdapter` 定义 `connect/disconnect/configure/grab/write_signal`，未实现的能力抛 `NotImplementedFeature`（HTTP 501），界面显示「接口预留」。接真实相机只需实现 `grab`：

```python
class MyCamera(DeviceAdapter):
    def __init__(self):
        super().__init__(DeviceInfo(id="my_cam", name="我的相机", implemented=True,
                                    capabilities=[DeviceCapability.SOFTWARE_TRIGGER]))

    def connect(self, **kw):  self.state = DeviceState.CONNECTED; return self.state
    def grab(self, **kw) -> np.ndarray:  return frame_bgr_or_gray_ndarray

device_manager.register(MyCamera())   # app/services/devices/adapters.py
```

## 对照功能规划文档

| 规划项 | MVP 状态 |
| --- | --- |
| 项目管理、版本与发布回滚 | 已实现（版本列表 / 回滚 / 发布锁定） |
| 数据管理：导入、分组、统计 | 已实现（上传、服务器目录导入、train/val/test 自动划分、统计） |
| 标注：分类 / 矩形 / 多边形 / 点，COCO·YOLO 导出 | 已实现 |
| 图像查看器：缩放、像素值、直方图、ROI 绘制 | 已实现 |
| 节点式流程编辑器 + 逐节点调试 | 已实现（66 算子、类型校验、缓存、中间图像） |
| AI 引导：意图识别、成像诊断、方案生成、参数解释、调试建议 | 已实现（LLM 可选，规则引擎兜底） |
| 批量测试与指标、误判回流 | 已实现（accuracy/precision/recall/F1/漏检/误报、CSV 导出） |
| 传统算法 + AI 模型混合 | 已实现（LBP+SVM 训练与推理节点） |
| 操作员运行界面（业务参数 + OK/NG + 良率） | 已实现（数据集回放 / 模拟相机） |
| 模型监控：设备在线、推理量、置信度、耗时、预测明细 | 已实现（按会话保留最近 200 条推理） |
| 相机与外设采集 | **接口预留**（模拟相机可用，工业相机/PLC/MES/机器人返回 501） |
| 深度学习检测/分割训练、多工位编排、权限与审计 | 未做，属于后续阶段 |

## 已知限制

- 采集为模拟实现，硬件触发、多相机同步、实时节拍未验证。
- 批量测试/运行时为进程内线程池，单机单实例；多机部署需要换成任务队列。
- SQLite + 本地文件存储，适合单工位现场；并发写入多时需迁移 PostgreSQL + 对象存储。
- 监控数据直接查运行记录表，每个会话只留最近 200 条推理（预览图按同样长度的环形槽位复用），因此「7 天」窗口看到的是这 200 条里落在窗口内的部分；长留存需要接时序库。
- 设备在线状态是 API 进程内的适配器状态，重启后回到「离线」，需要在设备页重新连接。
- AI 模型部分只含经典机器学习（LBP+SVM），深度学习训练未纳入 MVP。
