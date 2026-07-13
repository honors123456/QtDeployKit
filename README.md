# QtDeployKit

Qt (MSVC) 项目一键打包工具:`windeployqt` 收集 DLL → 依赖闭包扫描自动补齐 →
生成 Inno Setup 脚本 → 编译出安装包。零第三方依赖,只需 Python ≥ 3.11。

把手动部署踩过的坑固化进脚本:

- **0xc000012f / 缺 DLL 防坑**:打包前校验 exe 与 Qt kit 位数一致;递归解析
  所有 PE 文件的导入表(含 delay-load),缺什么、谁引用的,打包前就报出来。
- **第三方 DLL 全量携带**:`search_dirs` 指向第三方库/应用的 bin 目录,其中
  所有 DLL 全量拷入包内(cudnn、ffmpeg 等动态加载件不会漏);依赖闭包检查
  只校验 exe 引用链实际用到的部分,富余 DLL 仅随包携带不报错。
- **QML 工程**:`[qt].qml_dirs` 指向 QML 源码目录即可部署 QML 模块;链接了
  QML 却没配会在打包时报错拦截,不让白屏的包流出去。
- **VC 运行时两种方式**:`vc_redist` 指向 vc_redist.x64.exe 则安装时静默安装
  (已装跳过);指向运行时 DLL 目录则直拷进包(app-local)。
- **写权限**:安装包默认装到 Program Files 且可选用户目录;程序数据应写
  `AppData`,注意事项生成在 `DEPLOY_NOTES.md`。
- **杀软误报**:生成白名单提交指引;支持可选 signtool 签名步骤。

## 使用

最简方式(双击):把 `deploy.toml` 按注释填好(可连同 `start.bat` 一起复制到
项目目录),双击 `start.bat` 即可——优先找同目录的 `deploy.toml`,也支持
`*.deploy.toml` 或把配置文件直接拖到 `start.bat` 图标上。

命令行方式:

```powershell
python deploy.py deploy.toml

# 只收集 DLL 不出安装包(调试用)
python deploy.py deploy.toml --skip-installer

# 打包前对主程序做启动冒烟测试
python deploy.py deploy.toml --smoke
```

产物在配置的 `output.dir` 下:

```
<output.dir>/
├── MyApp/               # 完整的绿色可运行目录，名称来自 [app].name
├── MyApp-setup.exe      # 安装包(命名不带版本号)
├── installer.iss        # 生成的 Inno Setup 脚本
└── DEPLOY_NOTES.md      # 扫描报告 + 杀软/写权限注意事项
```

## 前提

- Python ≥ 3.11(用到标准库 `tomllib`)
- Qt MSVC kit(配置里指定或在 PATH 里能找到 `windeployqt`)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)(自动从注册表定位,或配置里指定 ISCC 路径)
- 版本号自动从 exe 的 FileVersion 读取(qmake `VERSION = 1.2.3` 会生成),
  读不到用默认 1.0,只影响安装包元数据,不影响文件名。

## 限制

- 仅支持 MSVC 构建的 x64/x86 程序,MinGW 未支持。
- 运行时动态加载的 DLL 在导入表里不可见:在 `search_dirs` 覆盖的目录里会随
  全量拷贝带上;不在的(以及模型等数据文件)需在 `deps.extra_files` 手工声明。
  `extra_files` 支持文件、通配符和目录；目录会保留自身名称并递归复制全部内容。
