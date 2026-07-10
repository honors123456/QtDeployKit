# QtDeployKit Roadmap

## 当前阶段

v0.1 已跑通:MSVC x64 Qt 程序从 exe 到 setup.exe 的全流程可用。

## 已完成(均已验证)

- [x] `deploy.py` 全流程:读配置 → 版本/架构校验 → windeployqt 收集 →
      依赖闭包扫描自动补齐 → 生成 iss → ISCC 编译出安装包(2026-07-10)
- [x] PE 解析(x64/x86 判断、导入表含 delay-load)、FileVersion 读取,
      对 designer.exe / SysWOW64 notepad.exe / Qt5Core.dll 核对通过
- [x] 依赖扫描三分支验证:search_dirs 自动补齐、缺失报错并列出引用者、
      VC 运行时/UCRT 正确归类不误报
- [x] 端到端验证:designer.exe → 12.6 MB 安装包 → `/VERYSILENT /CURRENTUSER`
      静默安装 → 安装目录启动程序存活 → 静默卸载无残留
- [x] `--smoke` 冒烟测试、`--skip-installer` 调试模式
- [x] `start.bat` 双击/拖拽启动器:自动查找同目录 `*.deploy.toml`,带参、
      自动查找、无配置报错三条路径均验证(2026-07-10;bat 必须 GBK+CRLF,
      已用 .gitattributes 固定)
- [x] Inno 模板:VC Redist 静默安装(已装跳过)、权限模式 dialog、
      x86/x64 架构参数化、中文语言包存在时自动启用

- [x] QML 支持:`[qt].qml_dirs` → `--qmldir`,已验证 QtQuick 模块正确部署
      (Qt5 落在部署根目录而非 qml\ 子目录);程序链接 QML 却未配 qml_dirs
      时报错拦截(2026-07-10)
- [x] 配置文件容忍 UTF-8 BOM(记事本保存会带),TOML 语法错误给出友好提示
- [x] 需求变更(2026-07-10):版本号不强制,读不到 FileVersion 用默认 1.0,
      只进安装包元数据;安装包直接落打包工作目录,命名 <name>-setup 不带版本
- [x] search_dirs 改为全量拷贝语义:目录内所有 DLL 进包,闭包检查只走
      exe 可达引用链,富余 DLL(如 debug 版)不误报缺依赖
- [x] vc_redist 双模式:指向 vc_redist*.exe 内嵌静默安装;指向运行时 DLL
      目录则直拷进包(app-local),两种均以 demo 验证
- [x] 配置定名 deploy.toml,start.bat 优先查找;dist 清理保留标记文件到
      最后,清理中断不再丢失目录身份;文件被占用给出人话提示

- [x] 实时进度与详细输出(2026-07-10):windeployqt/ISCC 输出逐行透传;
      每个拷贝文件显示名字大小,>128MB 显示百分比进度;各阶段与总耗时统计

## 进行中

(无)

## 待办

- [ ] K-LiveCellImage 真实项目端到端出包并在目标机验证(收集阶段已跑通,
      安装包阶段待桌面残留 dist 清理后重跑)
- [ ] vc_redist 内嵌 exe 安装模式在目标机实测(DLL 直拷模式已验证)
- [ ] 在没装 Qt / VC 运行时的干净虚拟机里安装验证(本机验证无法覆盖
      「目标机缺运行库」场景)
- [ ] vc_redist 配置后的安装包实测(本机已装运行时,Check 跳过分支未走到)
- [ ] signtool 签名步骤实测(需要证书)
- [ ] MinGW 工具链支持(libgcc/libstdc++/libwinpthread 收集)

## 阻塞

(无)

## 最近验证

2026-07-10:单元级(PE 解析/版本读取/DLL 归类)+ 扫描三分支 + 端到端
(打包→安装→运行→卸载)全部通过,环境:Win10、Python 3.12.6、
Qt 5.12.12 msvc2017_64、Inno Setup 6.3.3。

## 待确认

- Inno 6.3 的 `ArchitecturesAllowed=x64compatible` 在 ARM64 Windows 目标机
  上的行为(允许 x64 模拟安装)是否符合预期,暂无 ARM64 设备可测。
