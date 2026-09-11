# 密封袋谷物视觉分类

样品在透明袋里，先认**种类**（玉米 / 稻谷 / 小麦…），不要一上来做国标等级。水分和容重视觉做不到。

## 拍照

- 哑光白底，袋子展平，字样折到侧面
- 两侧柔光或环形灯，**关掉闪光灯**
- 垂直俯拍，距离固定在 35–45 cm
- 粮面占画面 70% 以上，袋旁放一枚硬币当尺子
- 每袋两张：整袋 + 贴袋近景

## 使用

```bash
cd "/Users/henrybz/分类"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/app.py
```

浏览器里上传照片即可初判种类。人工确认后点「保存到数据集」。

每类攒到大约 20 张以上后训练。默认用 **EfficientNet-B0**（BSD，自有权重）；YOLO 仍可选用。

```bash
python src/train_effnet.py
# 仍可用 YOLO：python src/train.py
```

单张离线识别（默认优先 `models/grain_effnet.pt`）：

```bash
python src/infer.py 照片.jpg
python src/infer.py 照片.jpg --weights models/grain_effnet.pt
python src/export.py
```

## 目录

把确认过的照片放进对应文件夹：

```
data/train/玉米/
data/train/稻谷/
data/train/小麦/
```
