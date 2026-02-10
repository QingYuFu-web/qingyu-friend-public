# 第二阶段配置教程：语音交互

> ⚠️ **前置条件**：已完成第一阶段，AI 大脑正常运行

---

## 📦 硬件准备

确认已购买并收到：
- ✅ ReSpeaker 2-Mic HAT v2.0
- ✅ 3W 扬声器（3.5mm 或 USB）

---

## 🔧 硬件安装

### 1. 安装 ReSpeaker 麦克风板

**步骤**：
1. **断电**：拔掉树莓派电源
2. **对齐 GPIO**：将 ReSpeaker 的 40 针接口对准树莓派的 GPIO 针脚
3. **插入**：垂直向下压，确保完全插紧
4. **检查**：所有针脚都应插入，不能有悬空

**注意**：
- 方向别插反（有标注"40-pin"的一面朝上）
- 用力要均匀，避免弯针

### 2. 连接扬声器

**方案 A：3.5mm 音频接口**
1. 插入树莓派的 3.5mm 音频孔（靠近 HDMI 的那个）

**方案 B：USB 扬声器**
1. 插入树莓派的 USB 口

---

## 💿 软件配置

### 1. SSH 连接到树莓派

```bash
ssh pi@qingyu.local
```

### 2. 安装 ReSpeaker 驱动

```bash
# 更新系统
sudo apt update

# 安装驱动依赖
sudo apt install git -y

# 克隆驱动仓库
cd ~
git clone https://github.com/respeaker/seeed-voicecard.git
cd seeed-voicecard

# 安装驱动
sudo ./install.sh

# 重启
sudo reboot
```

**预计时间**：5-10 分钟

### 3. 验证驱动安装

重启后重新 SSH 连接，运行：

```bash
# 查看音频设备
arecord -l
```

**预期输出**：应该看到 `seeed-2mic-voicecard` 设备

```bash
# 测试录音
arecord -D plughw:1,0 -f cd -d 5 test.wav
# 说话5秒，然后播放
aplay test.wav
```

如果能听到自己的录音，说明麦克风工作正常！✅

### 4. 安装语音识别引擎（Sherpa-ONNX）

```bash
# 激活虚拟环境
cd ~/robot_project
source venv/bin/activate

# 安装 sherpa-onnx
pip install sherpa-onnx portaudio

# 下载中文识别模型（约 40MB）
mkdir -p models/asr
cd models/asr
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2
tar -xf sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2
```

### 5. 安装语音合成引擎（Sherpa-ONNX TTS）

```bash
# 下载中文 TTS 模型（约 20MB）
mkdir -p ../tts
cd ../tts
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-zh_CN-huayan-medium.tar.bz2
tar -xf vits-piper-zh_CN-huayan-medium.tar.bz2
```

---

## 🧪 测试语音功能

### 测试 1：语音识别

创建测试脚本 `~/robot_project/test_asr.py`：

```python
import sherpa_onnx

# 配置识别器
recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens="models/asr/sherpa-onnx-streaming-paraformer-bilingual-zh-en/tokens.txt",
    encoder="models/asr/sherpa-onnx-streaming-paraformer-bilingual-zh-en/encoder.onnx",
    decoder="models/asr/sherpa-onnx-streaming-paraformer-bilingual-zh-en/decoder.onnx",
    joiner="models/asr/sherpa-onnx-streaming-paraformer-bilingual-zh-en/joiner.onnx",
)

print("请说话...")
# 实时识别代码（待完善）
```

### 测试 2：语音合成

创建测试脚本 `~/robot_project/test_tts.py`：

```python
import sherpa_onnx

# 配置合成器
tts = sherpa_onnx.OfflineTts.from_piper(
    model="models/tts/vits-piper-zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
    tokens="models/tts/vits-piper-zh_CN-huayan-medium/tokens.txt",
)

# 合成语音
audio = tts.generate("你好，我是小可爱")
# 播放音频（待完善）
```

---

## 📝 下一步实施

1. 完善语音模块代码（`src/voice/`）
2. 集成到 `brain.py`
3. 实现语音唤醒（VAD）
4. 外放回声消除（AEC）：参考 `docs/aec_ec_setup.md`

详见：`implementation_plan.md`

---

## ❓ 常见问题

**Q: 驱动安装失败怎么办？**  
A: 确认是 v2.0 版本，运行 `sudo ./install.sh --compat-kernel` 重试

**Q: 录音没声音？**  
A: 检查 `alsamixer`，按 F6 选择 seeed-2mic，将麦克风音量调到最大

**Q: 模型下载慢？**  
A: 可以在本地电脑下载后用 Xftp 上传
