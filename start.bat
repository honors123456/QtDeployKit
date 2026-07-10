@echo off
setlocal
rem QtDeployKit 一键打包启动器
rem 用法 1: 把 .deploy.toml 配置文件拖到本脚本图标上
rem 用法 2: 把本脚本复制到你的配置文件所在目录,直接双击
rem         (自动查找该目录下的 *.deploy.toml)
rem 用法 3: start.bat 配置文件路径

rem QtDeployKit 所在目录,移动了工具目录就改这里
set "KIT=d:\Code\QtDeployKit"

set "CONFIG=%~1"

if "%CONFIG%"=="" (
    rem 没传参数:在本脚本所在目录找 *.deploy.toml
    for %%F in ("%~dp0*.deploy.toml") do (
        set "CONFIG=%%~fF"
        goto :found
    )
    echo [错误] 没找到配置文件。
    echo 请把 .deploy.toml 拖到本脚本上,或把本脚本复制到配置文件所在目录再双击。
    pause
    exit /b 1
)
:found

echo 配置: %CONFIG%
echo.
python "%KIT%\deploy.py" "%CONFIG%"

if errorlevel 1 (
    echo.
    echo ======== 打包失败,请看上方错误信息 ========
) else (
    echo.
    echo ======== 打包成功 ========
)
pause
