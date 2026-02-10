# 外放回声消除（AEC）接入指南：voice-engine/ec

本项目的语音对话在“外放”场景会出现 **TTS 回灌 → ASR 误识别**。为解决该问题，支持接入开源 AEC 工具 `voice-engine/ec`（SpeexDSP AEC + ALSA），通过 FIFO 管道在系统层完成回声消除。

## 适用环境

- Raspberry Pi（Linux）
- ReSpeaker 2-Mic HAT v2.0（声卡名通常为 `seeed2micvoicec`）
- 系统可能启用 PipeWire，但本方案直接使用 ALSA 设备（`plughw:*`），不依赖 `pactl`

## 1. 安装依赖并编译 ec

在树莓派上执行：

```bash
sudo apt-get update
sudo apt-get -y install git build-essential libasound2-dev libspeexdsp-dev

git clone https://github.com/voice-engine/ec.git
cd ec
make

# 可选：安装到 /usr/local/bin
sudo install -m 0755 ec /usr/local/bin/ec
```

## 2. 选择 ALSA 设备名

查看可用设备：

```bash
arecord -L
aplay -L
cat /proc/asound/cards
```

一般可用：
- 录音：`plughw:CARD=seeed2micvoicec,DEV=0`
- 播放：`plughw:CARD=seeed2micvoicec,DEV=0`

## 3. 启动 ec（FIFO 模式）

建议先按经验值设置回声路径延迟（ReSpeaker 常见约 200ms）：

```bash
/usr/local/bin/ec \
  -i plughw:CARD=seeed2micvoicec,DEV=0 \
  -o plughw:CARD=seeed2micvoicec,DEV=0 \
  -r 16000 \
  -c 2 \
  -d 200 \
  -f 4096
```

说明：
- `ec` 会创建并使用：
  - `/tmp/ec.input`：播放参考信号（**必须 mono / 16k / s16le**）
  - `/tmp/ec.output`：消回声后的录音输出（通常为 2ch，项目侧会下混为 mono 给 ASR）
- `ec` 在检测到 `/tmp/ec.input` 有播放数据后会自动启用 AEC（控制台会打印 `Enable AEC`）

## 4. 配置本项目启用 AEC

编辑 `robot_project/config/speech.json`：

- 将 `aec.enabled` 设为 `true`
- 确认 `aec.ec_binary` 指向 ec 路径（例如 `/usr/local/bin/ec`）
- `capture_device` / `playback_device` 与上面 ec 启动命令保持一致

启用后：
- 播放不再使用“暂停监听 + 等待回声消散”规避逻辑
- 录音会从 `/tmp/ec.output` 读取（已消回声），再送入 VAD/ASR

## 5. 运行

```bash
cd ~/robot_project
source venv/bin/activate
python main_voice.py
```

## 6. 快速验证（建议）

1. **确认 AEC 已启用**
   - 启动 `ec` 后，当你第一次播放 TTS，`ec` 控制台应出现 `Enable AEC`。
2. **确认不会自问自答**
   - 打开外放，机器人说话时，你保持安静，ASR 不应再把 TTS 当成你的话触发对话。
3. **确认插话有效**
   - 机器人播报时，你用正常音量插话（例如说“等一下”），应能触发“停止播报”的提示与行为。

## 调参建议

- `aec.delay_ms`：最关键参数。回声仍明显时可在 `150~300` 之间调整。
- 外放音量过大或麦克风过近会显著降低 AEC 效果，建议先做物理隔离。
