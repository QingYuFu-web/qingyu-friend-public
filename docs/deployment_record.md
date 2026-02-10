# AI成长机器人 - 完整部署记录

> 记录日期：2025-12-11 ~ 2025-12-12
> 当前硬件：树莓派5 8GB + 32GB SD卡

---

## 第一步：烧录系统

### 1.1 下载工具
- 下载 [Raspberry Pi Imager](https://www.raspberrypi.com/software/)

### 1.2 烧录配置
1. **选择设备**：Raspberry Pi 5
2. **选择系统**：Raspberry Pi OS (64-bit) Bookworm
3. **选择存储**：32GB SD卡
4. **编辑设置**（点击齿轮图标）：
   - 主机名：`qingyu`
   - 用户名：`pi`
   - 密码：（你设置的密码）
   - WiFi：（你家的WiFi）
   - 时区：Asia/Shanghai
   - 启用SSH：✅ 使用密码登录

### 1.3 烧录
点击"写入"，等待完成（约5-10分钟）

---

## 第二步：首次连接

### 2.1 启动树莓派
1. SD卡插入树莓派
2. 接通电源，等待1-2分钟

### 2.2 SSH连接
使用 Xshell 或 PowerShell：
```bash
ssh pi@qingyu.local
# 或使用IP地址
ssh pi@192.168.x.x
```

---

## 第三步：换清华镜像源

### 3.1 备份原文件
```bash
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
```
> ⚠️ raspi.list 文件可能不存在，可跳过备份

### 3.2 替换主源
```bash
echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware' | sudo tee /etc/apt/sources.list
```
> **作用**：将系统软件源从国外服务器切换到清华镜像，加速下载

### 3.3 创建树莓派专用源
```bash
echo 'deb https://mirrors.tuna.tsinghua.edu.cn/raspberrypi/ bookworm main' | sudo tee /etc/apt/sources.list.d/raspi.list
```
> **作用**：添加树莓派官方软件包的清华镜像源

### 3.4 更新系统
```bash
sudo apt update && sudo apt upgrade -y
```
> **作用**：更新软件包列表并升级所有已安装软件

---

## 第四步：安装基础依赖

```bash
sudo apt install -y python3-pip python3-venv python3-dev git cmake build-essential portaudio19-dev libffi-dev libssl-dev
```

| 包名 | 作用 |
|------|------|
| python3-pip | Python包管理器 |
| python3-venv | Python虚拟环境支持 |
| python3-dev | Python开发头文件 |
| git | 版本控制 |
| cmake, build-essential | C/C++编译工具 |
| portaudio19-dev | 音频库（为后续语音功能准备） |
| libffi-dev, libssl-dev | 加密/FFI库 |

---

## 第五步：检查 Swap 空间

```bash
free -h
```

> **结果**：系统已自动配置 2GB Swap，无需手动设置
> 如果 Swap 显示 0，需要手动创建（参考 phase1_minimal_setup.md）

---

## 第六步：安装 Ollama

### 方法A：在线安装（网络好时使用）
```bash
curl -fsSL https://ollama.com/install.sh | sh
```
> ⚠️ 如遇 503 错误，等几分钟重试或使用方法B

### 方法B：离线安装（实际使用的方法）

由于网络问题，采用本地下载后上传安装：

1. **在电脑上下载安装包**
   - 访问：https://github.com/ollama/ollama/releases
   - 下载：`ollama-linux-arm64.tgz`

2. **用 Xftp 上传到树莓派**
   - 上传到：`/home/pi/`

3. **解压安装**
   ```bash
   cd ~
   sudo tar -C /usr -xzf ollama-linux-arm64.tgz
   ```
   > **作用**：将 Ollama 解压到系统目录 `/usr`

4. **启动 Ollama 服务**
   ```bash
   ollama serve &
   ```
   > **作用**：在后台启动 Ollama 服务

### 6.2 验证安装
```bash
ollama --version
```
> 应显示：`ollama version is 0.13.2`（或更新版本）

### 6.3 下载模型
```bash
# 基础模型（约350MB）
ollama pull qwen2:0.5b

# 升级模型（约1GB，可选）
ollama pull qwen2:1.5b
```

### 6.4 测试模型
```bash
ollama run qwen2:0.5b "你好"
```

### 6.5 设置开机自启动（手动安装必须）

如果使用离线安装（方法B），需要手动创建 systemd 服务：

```bash
# 创建 ollama 用户
sudo useradd -r -s /bin/false -m -d /usr/share/ollama ollama

# 创建服务文件
sudo tee /etc/systemd/system/ollama.service << 'EOF'
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
```
> **作用**：创建 systemd 服务配置文件

```bash
# 重新加载 systemd
sudo systemctl daemon-reload

# 启用开机自启动
sudo systemctl enable ollama

# 启动服务
sudo systemctl start ollama

# 检查状态
sudo systemctl status ollama
```
> **作用**：启用并启动 Ollama 服务，开机自动运行

---

## 第七步：创建 Python 虚拟环境

### 7.1 创建项目目录
```bash
mkdir -p ~/robot_project
cd ~/robot_project
```
> **作用**：创建项目根目录

### 7.2 创建虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate
```
> **作用**：创建并激活 Python 虚拟环境，隔离项目依赖
> 激活后命令行前会显示 `(venv)`

### 7.3 配置 pip 镜像
```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install --upgrade pip
```
> **作用**：使用清华 pip 镜像加速下载

---

## 第八步：安装 Python 依赖

```bash
pip install ollama chromadb
```

| 包名 | 作用 |
|------|------|
| ollama | Ollama Python 客户端 |
| chromadb | 向量数据库，用于长期记忆 |

### 验证安装
```bash
python -c "import ollama; print(ollama.chat('qwen2:0.5b', messages=[{'role':'user','content':'你好'}])['message']['content'])"
```
> 应输出 AI 的回复，如："您好！有什么我可以帮助您吗？"

---

## 第九步：创建项目结构

```bash
mkdir -p src/brain config data
```

最终结构：
```
~/robot_project/
├── venv/           # Python虚拟环境
├── src/
│   └── brain/      # AI大脑模块
├── config/         # 配置文件
└── data/           # 数据存储
```

---

## 第十步：部署代码

### 10.1 上传代码
使用 Xftp 将本地 `e:\qingyu-friend\robot_project\` 同步到树莓派 `~/robot_project/`

主要文件：
- `src/brain/brain.py` - AI大脑核心代码
- `config/persona.json` - 人格配置（首次运行自动生成）

### 10.2 运行测试
```bash
cd ~/robot_project
source venv/bin/activate
python src/brain/brain.py
```

---

## 当前完成状态

- [x] 系统烧录 + SSH配置
- [x] 换清华镜像源
- [x] 安装系统依赖
- [x] Swap 确认（2GB）
- [x] Ollama 安装
- [x] qwen2:0.5b 模型
- [x] Python 虚拟环境
- [x] Python 依赖（ollama, chromadb）
- [x] 项目目录结构
- [x] AI大脑代码部署
- [x] 基本对话测试通过
- [ ] qwen2:1.5b 模型（下载中）

---

## 常用命令速查

```bash
# 激活虚拟环境
cd ~/robot_project && source venv/bin/activate

# 运行机器人
python src/brain/brain.py

# 查看已下载的模型
ollama list

# 测试模型
ollama run qwen2:0.5b "你好"

# 查看磁盘空间
df -h

# 查看内存/Swap
free -h
```

---

## 后续升级 SD 卡

### 克隆方法（推荐）
1. 使用 Win32DiskImager 读取旧卡为 .img 文件
2. 将 .img 写入新的大卡
3. 插入树莓派后扩展分区：
   ```bash
   sudo raspi-config
   # Advanced Options → Expand Filesystem
   sudo reboot
   ```

---

## 待补充说明

> 如果有丢失的步骤或遇到的问题，请在此处补充：

1. ___
2. ___
3. ___
