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
- [x] Inno 模板:VC Redist 静默安装(已装跳过)、权限模式 dialog、
      x86/x64 架构参数化、中文语言包存在时自动启用

## 进行中

(无)

## 待办

- [ ] 用一个真实业务项目(含 OpenCV 依赖)实测 search_dirs 自动补齐和
      extra_files 动态加载 DLL 场景
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
