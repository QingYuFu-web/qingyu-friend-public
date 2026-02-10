# 远程 Ollama 服务器配置指南

将你的 **RTX 2060 台式机** 变成 AI 推理服务器，让树莓派享受 **1秒级响应**！

---

## 📋 前置条件

- ✅ Windows 电脑（你的台式机：i5-14600KF + RTX 2060 12GB）
- ✅ 电脑和树莓派在同一局域网
- ✅ 电脑大部分时间保持开机

---

## 第一步：在 Windows 上安装 Ollama

### 1.1 下载并安装
访问：https://ollama.com/download/windows

下载 `OllamaSetup.exe` 并安装（会自动安装为Windows服务）。

### 1.2 验证安装
打开 **PowerShell**（普通模式即可），运行：
```powershell
ollama --version
```

看到版本号说明安装成功。

---

## 第二步：配置网络访问

默认 Ollama 只允许本机访问，需要配置监听所有网卡。

### 2.1 设置环境变量
**以管理员身份**运行 PowerShell：
```powershell
# 设置 Ollama 监听所有IP
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "Machine")
```

### 2.2 重启 Ollama 服务
```powershell
# 停止服务
Stop-Service Ollama

# 启动服务
Start-Service Ollama
```

### 2.3 验证网络监听
```powershell
# 查看 11434 端口是否在监听
netstat -an | findstr 11434
```

应该看到类似：
```
TCP    0.0.0.0:11434          0.0.0.0:0              LISTENING
```

### 2.4 防火墙放行（重要！）
**以管理员身份**运行 PowerShell：
```powershell
# 添加防火墙入站规则
New-NetFirewallRule -DisplayName "Ollama Server" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
```

---

## 第三步：下载模型

推荐使用 **Qwen2.5:7b**（速度快+够聪明）：

```powershell
ollama pull qwen2.5:7b
```

下载需要约 **4.7GB**，请耐心等待。

**可选**：如果想体验更聪明的模型（稍慢一点）：
```powershell
ollama pull qwen2.5:14b  # 需要约 9GB，推理稍慢但更聪明
```

---

## 第四步：测试服务器

### 4.1 本机测试
在 Windows PowerShell 里运行：
```powershell
ollama run qwen2.5:7b "你好，介绍一下你自己"
```

看到回复说明服务正常。

### 4.2 获取电脑IP
```powershell
ipconfig
```

找到 **IPv4 地址**，比如 `192.168.1.100`（记住这个IP）。

### 4.3 远程测试（可选）
在树莓派上测试能否访问：
```bash
curl http://192.168.1.100:11434/api/version
```

应该返回版本信息，比如：
```json
{"version":"0.x.x"}
```

---

## 第五步：修改树莓派代码

修改 `~/robot_project/src/brain/brain.py`：

### 5.1 修改模型初始化
找到 `Brain` 类的 `__init__` 方法，修改为：

```python
def __init__(self, model="qwen2.5:7b", server_host="http://QingYu.local:11434"):
    self.model = model
    self.server_host = server_host
    
    # 创建远程客户端
    try:
        import ollama
        self.client = ollama.Client(host=server_host)
        print(f"🌐 已连接到远程服务器: {server_host}")
    except Exception as e:
        print(f"⚠️  远程连接失败: {e}")
        self.client = ollama  # 回退到本地
        
    self.memory = Memory()
    self.persona = Persona()
    
    print(f"🧠 AI大脑初始化完成")
    print(f"   模型: {model}")
    print(f"   人格: {self.persona.persona['name']}")
```

### 5.2 修改 chat 方法
找到 `response = ollama.chat(...)` 这一行，改成：
```python
response = self.client.chat(model=self.model, messages=messages)
```

---

## 常见问题

### Q1: 电脑关机后怎么办？
A: 树莓派会连接失败。可以在代码里加容错逻辑（下一步优化）。

### Q2: 用主机名 vs IP 哪个好？
A: **推荐用主机名** (`QingYu.local`)，这样即使IP变了也不用改代码。

### Q3: 速度会有多快？
A: RTX 2060 跑 qwen2.5:7b，预计 **1-2秒** 每次回复（比树莓派快5-10倍）。

### Q4: 会影响电脑性能吗？
A: 推理时会占用GPU，但日常使用（浏览网页、办公）几乎无影响。玩3D游戏时可能略有影响。

---

## 下一步优化（可选）

1. **离线降级**：当服务器不可用时，自动切换回树莓派本地的 0.5B 模型
2. **自动唤醒**：配置 Wake-on-LAN，让树莓派能远程唤醒电脑
3. **HTTPS加密**：如果担心局域网安全，可以配置SSL证书

---

🎉 配置完成后，你的机器人就拥有了**本地化的云端大脑**！
