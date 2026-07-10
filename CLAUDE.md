# QtDeployKit

windeployqt + Inno Setup 一键打包工具。把 Qt/MSVC 项目的部署流程(DLL 收集、依赖闭包校验、安装包生成)固化成脚本,新项目复制一份配置即可复用。

## 目录结构

```
QtDeployKit/
├── deploy.py                 # 主脚本,零第三方依赖
├── start.bat                 # 双击/拖拽启动器,与配置模板同级
├── sample.deploy.toml        # 配置模板,新项目连同 start.bat 一起复制
├── templates/
│   └── installer.iss.tpl     # Inno Setup 模板,占位符格式 @NAME@
├── CLAUDE.md / ROADMAP.md / README.md
```

## 技术约定

- Python ≥ 3.11,**只用标准库**(`tomllib`、`ctypes`、`struct`、`winreg`),不引入第三方包。
- 配置用 TOML;路径字段用单引号字面量(不转义反斜杠)。
- 版本号唯一来源是 exe 的 FileVersion 资源;读不到就报错,不允许静默兜底。
- 模板占位符用 `@NAME@`,不用 `{{}}`(与 Inno Setup 自身的 `{}` 常量语法冲突)。
- 只支持 MSVC 工具链;MinGW 支持在 ROADMAP 待办里,未实现。
- VC 运行时绝不散拷 DLL,统一走安装包内嵌 VC Redist 静默安装。
- 系统 DLL(kernel32、api-ms-win-* 等)绝不拷贝,内置白名单 + System32 存在性兜底判断。
- deploy.py 只清理带 `.qtdeploykit` 标记文件的 dist 目录,拒绝删除来历不明的目录。
- bat 脚本必须 GBK(ANSI)编码 + CRLF 换行(.gitattributes 已固定 eol):
  cmd 对 LF/UTF-8 批处理会按错误字节位置断行,2026-07-10 踩过。

## 验证方式

用本机 Qt 自带的 MSVC 工具 exe(如 `designer.exe`)当被打包对象,跑通
collect → scan → package 全流程,产出 setup.exe 即为通过。改动 PE 解析、
依赖扫描逻辑后必须重跑一次端到端。

## 已知原理性盲区(文档里要写明,不要试图"修复")

- 运行时动态加载的 DLL(`LoadLibrary`/`QLibrary`,如 OpenCV 的
  `opencv_videoio_ffmpeg*_64.dll`)不在导入表里,静态扫描看不见,必须在
  `deps.extra_files` 手工配置。
- 数据文件(模型、级联分类器 xml 等)同上。
