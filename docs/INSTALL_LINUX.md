# Linux 安装

CPU 使用 `./install/install-linux.sh`。NVIDIA 环境先核对驱动、CUDA 和官方 wheel，
再运行：

```text
./install/install-linux.sh --paddle-install-command "官方给出的当前命令"
./start-linux.sh
```

服务默认只监听 `127.0.0.1:8765`。不要在未添加认证和网络边界的情况下暴露到公网。
