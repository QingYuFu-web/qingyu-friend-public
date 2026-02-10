# 环境部署指南 v2.1

> 树莓派5 + Sherpa-ONNX + Ollama 环境搭建

---

## 前置条件

- [ ] 树莓派5 8GB + 散热器
- [ ] 64GB+ NVMe SSD（推荐）或 microSD
- [ ] 5V 5A USB-C电源
- [ ] 网络连接

---

## 步骤1：系统安装

### 1.1 烧录系统

1. 下载 [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. 选择 **Raspberry Pi OS (64-bit)** - Bookworm
3. 配置：主机名、SSH、WiFi、时区(Asia/Shanghai)
4. 烧录到存储设备

### 1.2 验证

```bash
ssh pi@robot.local
uname -m  # 应显示 aarch64
```

---

## 步骤2：系统配置

### 2.1 换清华源

```bash
sudo nano /etc/apt/sources.list
```
替换为：
```
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware
```

```bash
sudo nano /etc/apt/sources.list.d/raspi.list
```
替换为：
```
deb https://mirrors.tuna.tsinghua.edu.cn/raspberrypi/ bookworm main
```

### 2.2 更新系统

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.3 安装基础依赖

```bash
sudo apt install -y python3-pip python3-venv python3-dev git cmake build-essential
sudo apt install -y portaudio19-dev libffi-dev libssl-dev libjpeg-dev
sudo apt install -y libopenblas-dev liblapack-dev
```

### 2.4 增加Swap

```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup && sudo dphys-swapfile swapon
free -h  # 验证 Swap: 2.0Gi
```

---

## 步骤3：Ollama + Qwen2

```bash
# 安装Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 下载模型
ollama pull qwen2:0.5b

# 验证
ollama run qwen2:0.5b "你好"
```

---

## 步骤4：Python环境 + 依赖

### 4.1 创建环境

```bash
mkdir -p ~/robot_project && cd ~/robot_project
python3 -m venv venv
source venv/bin/activate
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install --upgrade pip
```

### 4.2 安装依赖

```bash
# 语音（Sherpa-ONNX）
pip install sherpa-onnx

# 视觉
pip install opencv-python-headless mediapipe

# 人脸识别（编译需1-2小时）
pip install dlib face_recognition

# AI + 记忆
pip install ollama chromadb

# 硬件控制
pip install RPi.GPIO gpiozero
```

### 4.3 下载Sherpa-ONNX模型

从 [Sherpa-ONNX Releases](https://github.com/k2-fsa/sherpa-onnx/releases) 下载：
- 中文ASR模型
- 中文TTS模型

---

## 步骤5：硬件验证

```bash
# 摄像头
python3 -c "import cv2; cap=cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL')"

# 麦克风
arecord -d 3 test.wav && aplay test.wav

# Ollama
python3 -c "import ollama; print(ollama.chat('qwen2:0.5b', messages=[{'role':'user','content':'你好'}])['message']['content'])"
```

---

## ✅ 完成

环境就绪后，开始代码开发阶段。
