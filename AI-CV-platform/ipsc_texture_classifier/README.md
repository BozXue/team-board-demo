# iPSC 克隆分割与中心定位

从 iPSC 亮场显微图中分割出主克隆区域并定位其中心，输出 mask、轮廓叠加图、量化指标 CSV，以及可追溯的 11 步中间过程图。

算法流水线：灰度化 → 局部标准差纹理 → 高斯平滑 → Otsu 阈值 → 闭运算 → 去小物体 → 填小洞 → 开运算 → 最大连通域 → 填洞成型 → 叠加轮廓与中心。

验收结论见 `测试验证报告.md`。

## 环境搭建

需要 Python 3.10+。以下两种方式任选其一，都已在 macOS arm64 上从零验证过，跨 Windows / Linux / Intel Mac 通用。

### 方式 A：conda（推荐）

```bash
conda env create -f environment.yml
conda activate ipsc
```

环境名为 `ipsc`，约 530 MB，首次创建 3–5 分钟。

### 方式 B：pip + venv

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

约 300 MB。若中途报 `THESE PACKAGES DO NOT MATCH THE HASHES`，是下载被网络截断了，加 `--no-cache-dir` 重跑一次即可。

### 验证装好了

```bash
python -c "import numpy, scipy, skimage, matplotlib, tifffile; print('ok')"
```

### 在编辑器里选解释器

VS Code / Cursor 中按 `Cmd/Ctrl + Shift + P` → `Python: Select Interpreter`，选中上面创建的 `ipsc` 环境或 `.venv`。不选的话编辑器会用系统默认的 Python，那个环境没装依赖，运行时会报 `ModuleNotFoundError: No module named 'matplotlib'`。

## 运行

处理单张图：

```bash
python colony_center.py --image "Image_20260616114812600.bmp" --out colony_results
```

批量处理一个目录（支持 `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp`）：

```bash
python colony_center.py --image ./my_images --out colony_results
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--image` | 必填 | 图片文件，或包含图片的文件夹 |
| `--out` | `colony_results` | 结果输出目录 |
| `--win` | 自动 | 局部标准差窗口（px），默认取图高的 1.5% |
| `--min-frac` | `0.01` | 小于整图这一比例的纹理团块视为杂质丢弃 |
| `--steps-dir` | `process_images` | 中间过程图输出目录 |
| `--no-steps` | 关 | 不导出过程图，大图能快数倍 |

大图（5120×5120）完整跑约 1 分 47 秒，其中大部分时间花在写几十 MB 的过程图上；加 `--no-steps` 可显著加速。

## 输出

`colony_results/`：

- `<图名>_colony_mask.png` — 克隆区域二值 mask
- `<图名>_colony_overlay.png` — 原图叠加青色轮廓与红色中心标记
- `colony_centers.csv` — 汇总表，字段为中心坐标、面积（px 与占比）、等效直径、solidity

注意 `colony_centers.csv` **按每次运行整体重写**，不是追加。批量处理时请一次性把所有图放进同一目录。

`process_images/`：每张图的 `01`–`11` 单步过程图，外加 `00_all_steps.png` 总览拼图。

## 文件说明

| 文件 | 作用 |
|---|---|
| `colony_center.py` | 主程序：分割、中心定位、结果与过程图输出 |
| `features.py` | 图像读取（`load_gray`）与特征提取（亮度直方图 + LBP） |
| `config.py` | 七分类类别定义、配色、特征与分块参数 |

`config.py` 中的七个区域类别（`single_cells`、`medium_compaction`、`full_compaction`、`dead_cells`、`differentiated_cells`、`debris`、`background`）属于纹理分类器模块，该模块尚未完成标注与训练，不影响本项目当前的分割功能。

## 常见问题

**`ModuleNotFoundError: No module named 'matplotlib'`** — 用错了 Python 解释器。检查终端提示符是不是显示着目标环境名，或按上面「在编辑器里选解释器」重新选一次。

**`[warn] <图名>: no colony found`** — 没检出克隆。可能是整图纹理过于均匀，或克隆太小被 `--min-frac` 滤掉了，可调小该值（如 `--min-frac 0.002`）重试。

**中文文件名** — 已支持，过程图标题会自动挑选系统中可用的中文字体渲染。
