# SPK Builder · 群晖 DSM 套件构建服务

一个**运行在群晖 DSM 系统上的原生套件构建服务**：封装成 `.spk` 安装到 DSM 后，用浏览器即可在群晖上打包 / 解包 / 批量处理 `.spk` 套件，无需命令行。

> **English**: [README_EN.md](README_EN.md)

## 安装到 DSM

1. **装依赖**：在套件中心安装 SynoCommunity 的 `python311`（Python 3.11 运行时）。
2. **装服务**：用下方「封装成本机 .spk」生成 `spkbuilder_<机型>.spk`（或从 Release 下载）；把套件中心「设置 → 信任级别」改为**任意发布者**，手动安装。
3. **打开**：浏览器访问 `http://<NAS的IP>:8800` 即进入构建台。

## 在 DSM 上使用

### 🚀 打包 .spk

把要安装的文件放进一个目录，目录结构直接对应安装后的 `target/`，填好信息点几下即可出包：

```
mypkg/
├── bin/myapp            # 可执行文件（打包成 0755）
├── ui/                  # 可选:DSM UI 文件
├── conf/                # 可选:配置文件
├── scripts/             # 可选:生命周期脚本（缺失会自动生成）
├── PACKAGE_ICON.PNG     # 可选:图标（缺失自动生成占位图）
└── PACKAGE_ICON_256.PNG
```

- 填**套件信息**（名称 / 版本 / 描述 / 维护者等）；
- 勾选**目标架构**（`x86_64` / `armv7` / `arm64` / `noarch`）；
- 点 **🚀 开始打包**，实时看日志，完成后下载 `.spk`。

多架构时按架构建子目录放各自二进制（`x86_64/bin/myapp`、`arm64/bin/myapp` 等）。

### 📥 解包 / 二次打包

导入现成 `.spk` 拆开分析并自动回填表单，改一下（版本号 / 描述 / 维护者等）即可重新打包；「打开」按钮、依赖声明、符号链接、`conf/privilege` 等元信息都会原样保留。

### 📦 批量处理

一次导入多个 `.spk`，逐个独立改信息、批量改单一信息、多线程并行构建、批量下载（zip 打包，按 `<软件名>-dsm7/` 分类）。

## 能力一览

| 能力 | 说明 |
| --- | --- |
| 原生运行 | 封装成本机 `.spk` 装到 DSM，非 root + File Station 共享文件夹 |
| 打包 .spk | 生成标准结构:INFO + package.tgz + scripts/ + 图标 |
| 解包二次打包 | 导入现成 .spk 分析并自动回填，保留元信息 |
| 按机型分发 | INFO 的 arch 字段自动写入完整机型代号，套件中心精确匹配 |
| 批量处理 | 批量解包 / 改信息 / 构建 / 下载 |
| 零依赖 | 打包功能只用 Python 标准库 |

## 机型分发（套件中心按机型匹配）

本工具采用与 SynoCommunity 原生一致的分发方式：**同一架构家族共享一个通用包**（而不是每机型单独编译一个包），每个 `.spk` 会在 INFO 的 `arch` 字段**自动写入该架构家族的全部机型代号**（家族代号在最前 + 具体机型代号，空格分隔），DSM 套件中心会按你的具体机型精确匹配到对应包：

| 架构 | INFO 的 arch 字段内容（节选） |
| --- | --- |
| `x86_64` | `x86_64 apollolake avoton braswell broadwell broadwellnk broadwellnkv2 broadwellntbap bromolow cedarview denverton epyc7002 epyc7003 geminilake geminilakenk grantley icelaked kvmx64 purley r1000 r1000nk v1000 v1000nk` |
| `arm64` | `armv8 arm64 aarch64 rtd1296 rtd1619b armada37xx` |
| `armv7` | `armv7 armada370 armada375 armada38x armadaxp alpine alpine4k monaco comcerto2k hi3535` |
| `noarch` | `noarch`（所有机型通用） |

> 注意 `arm64` 会同时写 `armv8` / `arm64` / `aarch64`：sspks-imnks 的机型家族用的是 `armv8`，若只写 `arm64` 会导致群晖匹配不到 ARM 机型包。

## 把本服务封装成 .spk（部署到 DSM）

本服务可把**自己**封装成群晖原生 `.spk` 装到 DSM（本机执行一次即可）：

```bash
python build_self.py
```

- **非 root 运行**：专用用户 `sc-spkbuilder` + `synocommunity` 组；
- **File Station 共享文件夹**：安装时自动创建共享文件夹作为构建产物输出目录；
- **SynoCommunity 标准结构**：`scripts/functions` + `installer` + `service-setup` + `start-stop-status` 通用框架；
- **按家族分包**：与 [sspks-imnks](https://github.com/tbc0309/sspks-imnks) 的 `conf/synology_models.yaml` 机型清单 1:1 对齐，同一家族共享一个通用包（`spkbuilder_x86_64.spk` / `spkbuilder_armv8.spk`），INFO 的 arch 字段写该家族全部机型代号。

产物在 `output/spkbuilder-1.0.1/`。

## 与 sspks 套件源配合

把生成的 `.spk` 丢进 [sspks](https://github.com/tbc0309/sspks-imnks) 服务器的 `packages` 目录，群晖**套件中心 → 套件来源**填上服务器地址即可安装。

> DSM 7 手动安装第三方未签名包时，需在套件中心设置里把「信任级别」改为**任意发布者**。

## 本机开发模式（可选，交叉编译）

在 DSM 上主要用「打包 / 解包 / 批量」。如需**从源码交叉编译**（需要编译工具链），可在本机运行 `python server.py` 后使用：

- **Go**：本机 Go 交叉编译（`CGO_ENABLED=0` 静态二进制）；
- **Docker**：在容器内执行任意编译命令（C/C++ 等）；
- **本地命令**：执行任意命令（`$OUT_BIN` / `ARCH`）；
- **spksrc**：用 SynoCommunity 的 [spksrc](https://github.com/SynoCommunity/spksrc) 框架（WSL2）编译原生程序。

## 目录结构

```
spk-builder/
├── server.py          # 后端服务（HTTP + 构建任务 + 产物下载）
├── spkpack.py         # 打包核心（生成 INFO/scripts/package.tgz/.spk）
├── builders.py        # 构建提供者与工具链检测
├── build_self.py      # 封装脚本（把本服务自身打成原生 .spk）
├── packaging/         # 封装用的框架 / 服务配置 / 安装向导
├── web/               # 前端界面（index.html / app.js / style.css）
├── 更新日志.txt        # 更新日志（Web 端「更新日志」页签数据源）
└── output/            # 构建产物（运行时生成）
```

## 常见问题

- **安装报「无法正确安装此套件」**：确认已装 `python311` 依赖，且套件中心「信任级别」为「任意发布者」。
- **非 root 运行**：本服务默认以专用用户 `sc-spkbuilder` 非 root 运行；构建产物写到安装时创建的共享文件夹。
- **产物下载路径**：下载链接指向 `output/` 下相对路径，文件名按 `<名称>_<架构>-<版本>.spk` 命名。

## License

[MIT](LICENSE)
