# QtDeployKit

Qt (MSVC) 项目一键打包工具:`windeployqt` 收集 DLL → 依赖闭包扫描自动补齐 →
生成 Inno Setup 脚本 → 编译出安装包。零第三方依赖,只需 Python ≥ 3.11。

把手动部署踩过的坑固化进脚本:

- **0xc000012f / 缺 DLL 防坑**:打包前校验 exe 与 Qt kit 位数一致;递归解析
  所有 PE 文件的导入表(含 delay-load),缺什么、谁引用的,打包前就报出来。
- **第三方 DLL 自动补齐**:OpenCV 等静态链接的库不用逐个列,给出 `search_dirs`
  自动查找拷贝,二级依赖也能递归带出。
- **QML 工程**:`[qt].qml_dirs` 指向 QML 源码目录即可部署 QML 模块;链接了
  QML 却没配会在打包时报错拦截,不让白屏的包流出去。
- **VC 运行时不散拷**:统一由安装包内嵌 VC Redist 静默安装(已装则跳过),
  避免运行库版本错乱。
- **写权限**:安装包默认装到 Program Files 且可选用户目录;程序数据应写
  `AppData`,注意事项生成在 `DEPLOY_NOTES.md`。
- **杀软误报**:生成白名单提交指引;支持可选 signtool 签名步骤。

## 使用

最简方式(双击):把 `start.bat` 和填好的 `xxx.deploy.toml` 一起复制到你的项目
目录,双击 `start.bat` 即可(自动查找同目录的 `*.deploy.toml`);也可以把配置
文件直接拖到 `start.bat` 图标上。

命令行方式:

```powershell
# 1. 复制配置模板并按注释填写
copy sample.deploy.toml myapp.deploy.toml

# 2. 一键打包
python deploy.py myapp.deploy.toml

# 只收集 DLL 不出安装包(调试用)
python deploy.py myapp.deploy.toml --skip-installer

# 打包前对主程序做启动冒烟测试
python deploy.py myapp.deploy.toml --smoke
```

产物在配置的 `output.dir` 下:

```
deploy/
├── dist/                # 完整的绿色可运行目录
├── installer.iss        # 生成的 Inno Setup 脚本
├── DEPLOY_NOTES.md      # 扫描报告 + 杀软/写权限注意事项
└── output/
    └── MyApp-1.2.3.0-setup.exe
```

## 前提

- Python ≥ 3.11(用到标准库 `tomllib`)
- Qt MSVC kit(配置里指定或在 PATH 里能找到 `windeployqt`)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)(自动从注册表定位,或配置里指定 ISCC 路径)
- 版本号从 exe 的 FileVersion 读取,工程需设置版本:qmake 加 `VERSION = 1.2.3`,
  CMake 在 `add_executable` 目标上配 `VERSION` 属性并生成 rc。

## 限制

- 仅支持 MSVC 构建的 x64/x86 程序,MinGW 未支持。
- 运行时动态加载的 DLL(如 OpenCV 的 `opencv_videoio_ffmpeg*_64.dll`)和数据
  文件在导入表里不可见,需在 `deps.extra_files` 里手工声明。
