#!/usr/bin/env python3
"""QtDeployKit — Qt (MSVC) 项目一键打包:windeployqt 收集 + 依赖闭包扫描 + Inno Setup 出安装包。

用法:
    python deploy.py <config.toml> [--skip-installer] [--smoke]

零第三方依赖,要求 Python >= 3.11(tomllib)。
"""

import argparse
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("需要 Python 3.11+(用到标准库 tomllib),当前版本 %s.%s" % sys.version_info[:2])

import tomllib

MARKER = ".qtdeploykit"  # dist 目录标记,只清理带此标记的目录

MACHINE_NAMES = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}

# MSVC 运行时:不散拷,由安装包内嵌 VC Redist 负责
VC_RUNTIME_DLLS = {
    "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll",
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
    "concrt140.dll", "vccorlib140.dll", "vcomp140.dll",
}

# UCRT:Win10+ 系统自带,老系统由 VC Redist 覆盖,一律不拷
UCRT_PREFIX = "api-ms-win-crt-"
API_SET_PREFIXES = ("api-ms-win-", "ext-ms-")

# 常见系统 DLL 白名单(小写)。不求全,漏网的由 System32 存在性兜底判断
SYSTEM_DLLS = {
    "kernel32.dll", "kernelbase.dll", "user32.dll", "gdi32.dll", "gdi32full.dll",
    "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll", "comdlg32.dll",
    "comctl32.dll", "ws2_32.dll", "winmm.dll", "version.dll", "uxtheme.dll",
    "dwmapi.dll", "dxgi.dll", "d3d9.dll", "d3d10.dll", "d3d11.dll", "d3d12.dll",
    "d2d1.dll", "dwrite.dll", "dcomp.dll", "opengl32.dll", "glu32.dll",
    "wldap32.dll", "crypt32.dll", "bcrypt.dll", "ncrypt.dll", "secur32.dll",
    "sspicli.dll", "netapi32.dll", "userenv.dll", "wtsapi32.dll", "setupapi.dll",
    "cfgmgr32.dll", "shlwapi.dll", "imm32.dll", "msimg32.dll", "mpr.dll",
    "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "psapi.dll",
    "dbghelp.dll", "powrprof.dll", "propsys.dll", "rpcrt4.dll", "msvcrt.dll",
    "ntdll.dll", "authz.dll", "windowscodecs.dll", "shcore.dll", "winspool.drv",
    "oleacc.dll", "usp10.dll", "gdiplus.dll", "avicap32.dll", "avifil32.dll",
    "msacm32.dll", "mf.dll", "mfplat.dll", "mfreadwrite.dll", "mfcore.dll",
    "wsock32.dll", "hid.dll", "winusb.dll", "d3dcompiler_47.dll",
}


class DeployError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} GB"


def run_streamed(cmd: list[str], indent: str = "      | ") -> int:
    """运行子进程并把输出逐行实时透传到控制台(带缩进前缀)。"""
    log(f"  $ {' '.join(cmd)}")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace", bufsize=1)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            print(indent + line, flush=True)
    return p.wait()


_BIG_FILE = 128 * 1024 * 1024
_CHUNK = 4 * 1024 * 1024


def copy_with_progress(src: Path, dst: Path, indent: str = "      ",
                       announce: bool = True) -> None:
    """拷贝文件并显示进度:小文件打一行名字+大小,超过 128MB 的显示百分比。"""
    size = src.stat().st_size
    if size < _BIG_FILE:
        shutil.copy2(src, dst)
        if announce:
            log(f"{indent}拷贝 {src.name}  ({fmt_size(size)})")
        return
    done = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while chunk := fi.read(_CHUNK):
            fo.write(chunk)
            done += len(chunk)
            print(f"\r{indent}拷贝 {src.name}  {done * 100 // size}%"
                  f" ({fmt_size(done)}/{fmt_size(size)})", end="", flush=True)
    print(flush=True)
    shutil.copystat(src, dst)


# ---------------------------------------------------------------- 配置

def load_config(path: Path) -> dict:
    if not path.is_file():
        raise DeployError(f"配置文件不存在:{path}")
    try:
        # utf-8-sig:容忍 Windows 记事本保存 UTF-8 时带的 BOM
        cfg = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as e:
        raise DeployError(f"配置文件 TOML 语法错误:{path}\n{e}")

    base = path.parent.resolve()

    def resolve(p: str) -> Path:
        q = Path(p).expanduser()
        return q if q.is_absolute() else (base / q).resolve()

    app = cfg.get("app", {})
    if not app.get("exe"):
        raise DeployError("配置缺少 [app].exe(主程序路径)")
    if not app.get("name"):
        raise DeployError("配置缺少 [app].name(应用名)")

    exe = resolve(app["exe"])
    if not exe.is_file():
        raise DeployError(f"主程序不存在:{exe}")
    icon = resolve(app["icon"]) if app.get("icon") else None
    if icon and not icon.is_file():
        raise DeployError(f"图标文件不存在:{icon}")

    deps = cfg.get("deps", {})
    extra_files = []
    for item in deps.get("extra_files", []):
        if isinstance(item, str):
            extra_files.append((item, ""))
        else:
            extra_files.append((item["src"], item.get("dest", "")))

    out = cfg.get("output", {})
    installer = cfg.get("installer", {})
    signing = cfg.get("signing", {})

    return {
        "exe": exe,
        "name": app["name"],
        "publisher": app.get("publisher", ""),
        "icon": icon,
        "qt_dir": resolve(cfg["qt"]["dir"]) if cfg.get("qt", {}).get("dir") else None,
        "qml_dirs": [resolve(d) for d in cfg.get("qt", {}).get("qml_dirs", [])],
        "windeployqt_args": cfg.get("qt", {}).get("windeployqt_args", []),
        "search_dirs": [resolve(d) for d in deps.get("search_dirs", [])],
        "extra_files": [(resolve(s) if not any(c in s for c in "*?") else (base, s), d)
                        for s, d in extra_files],
        "out_dir": resolve(out.get("dir", "deploy")),
        "installer_name": out.get("installer_name", ""),
        "iscc": resolve(installer["iscc"]) if installer.get("iscc") else None,
        "vc_redist": resolve(installer["vc_redist"]) if installer.get("vc_redist") else None,
        "sign_enabled": signing.get("enabled", False),
        "signtool": signing.get("signtool", "signtool"),
        "sign_args": signing.get("args", []),
    }


# ---------------------------------------------------------------- PE 解析

def get_file_version(path: Path) -> str | None:
    """读 exe/dll 的 FileVersion 资源,返回 'a.b.c.d';没有版本资源返回 None。"""
    ver = ctypes.WinDLL("version")
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                   ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL

    handle = wintypes.DWORD()
    size = ver.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    pblock = wintypes.LPVOID()
    plen = wintypes.UINT()
    if not ver.VerQueryValueW(buf, "\\", ctypes.byref(pblock), ctypes.byref(plen)) or plen.value < 52:
        return None
    ffi = ctypes.cast(pblock.value, ctypes.POINTER(wintypes.DWORD * 13)).contents
    if ffi[0] != 0xFEEF04BD:  # VS_FIXEDFILEINFO.dwSignature
        return None
    ms, ls = ffi[2], ffi[3]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def parse_pe(path: Path) -> tuple[str, list[str]]:
    """解析 PE 文件,返回 (架构, 导入的 DLL 名列表[小写],含 delay-load)。"""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise DeployError(f"{path.name} 不是有效的 PE 文件(缺 MZ 头)")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise DeployError(f"{path.name} 不是有效的 PE 文件(缺 PE 签名)")

    machine, nsec = struct.unpack_from("<HH", data, pe + 4)
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    plus = magic == 0x20B  # PE32+
    image_base = (struct.unpack_from("<Q", data, opt + 24)[0] if plus
                  else struct.unpack_from("<I", data, opt + 28)[0])
    ndirs = struct.unpack_from("<I", data, opt + (108 if plus else 92))[0]
    dirs_off = opt + (112 if plus else 96)

    def dir_entry(i: int) -> tuple[int, int]:
        if i >= ndirs:
            return 0, 0
        return struct.unpack_from("<II", data, dirs_off + 8 * i)

    sections = []
    sec_off = opt + opt_size
    for i in range(nsec):
        o = sec_off + 40 * i
        vsize, va, rsize, praw = struct.unpack_from("<IIII", data, o + 8)
        sections.append((va, vsize, rsize, praw))

    def rva2off(rva: int) -> int | None:
        for va, vsize, rsize, praw in sections:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + praw
        return None

    def cstr(off: int) -> str:
        return data[off:data.index(b"\0", off)].decode("latin-1")

    imports: list[str] = []

    rva, _ = dir_entry(1)  # import table
    off = rva2off(rva) if rva else None
    while off is not None and off + 20 <= len(data):
        entry = data[off:off + 20]
        name_rva = struct.unpack_from("<I", entry, 12)[0]
        if entry == b"\0" * 20 or name_rva == 0:
            break
        noff = rva2off(name_rva)
        if noff is not None:
            imports.append(cstr(noff))
        off += 20

    rva, _ = dir_entry(13)  # delay-load import table
    off = rva2off(rva) if rva else None
    while off is not None and off + 32 <= len(data):
        entry = data[off:off + 32]
        attrs, name_addr = struct.unpack_from("<II", entry, 0)
        if entry == b"\0" * 32 or name_addr == 0:
            break
        name_rva = name_addr if (attrs & 1) else name_addr - image_base
        noff = rva2off(name_rva)
        if noff is not None:
            imports.append(cstr(noff))
        off += 32

    return MACHINE_NAMES.get(machine, f"0x{machine:04x}"), [n.lower() for n in imports]


# ---------------------------------------------------------------- 工具定位

def find_qt_bin(cfg: dict) -> Path:
    if cfg["qt_dir"]:
        d = cfg["qt_dir"]
        for cand in (d / "bin", d):
            if (cand / "windeployqt.exe").is_file():
                return cand
        raise DeployError(f"[qt].dir 下找不到 windeployqt.exe:{d}")
    w = shutil.which("windeployqt")
    if w:
        return Path(w).parent
    raise DeployError("找不到 windeployqt:请在配置 [qt].dir 指定 Qt kit 目录,或将其 bin 加入 PATH")


def find_iscc(cfg: dict) -> Path:
    if cfg["iscc"]:
        if cfg["iscc"].is_file():
            return cfg["iscc"]
        raise DeployError(f"[installer].iscc 指定的路径不存在:{cfg['iscc']}")
    w = shutil.which("iscc") or shutil.which("ISCC")
    if w:
        return Path(w)
    # 注册表卸载信息里找 Inno Setup 的安装目录
    for hive_flag in (0, winreg.KEY_WOW64_32KEY):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                  0, winreg.KEY_READ | hive_flag)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as k:
                        name = winreg.QueryValueEx(k, "DisplayName")[0]
                        if not name.startswith("Inno Setup"):
                            continue
                        loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                        iscc = Path(loc) / "ISCC.exe"
                        if iscc.is_file():
                            return iscc
                except OSError:
                    continue
    for p in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
              r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if Path(p).is_file():
            return Path(p)
    raise DeployError("找不到 Inno Setup 的 ISCC.exe:请安装 Inno Setup 6,或在配置 [installer].iscc 指定路径")


# ---------------------------------------------------------------- 收集与扫描

def prepare_dist(out_dir: Path) -> Path:
    dist = out_dir / "dist"
    if dist.exists():
        if not (dist / MARKER).exists():
            raise DeployError(
                f"输出目录已存在且不是本工具生成的(缺 {MARKER} 标记),拒绝清理:{dist}\n"
                "请手动确认后删除,或在配置里换一个 output.dir")
        try:
            # 标记文件保留到最后:清理中途被占用中断时,目录仍可被识别为本工具所建
            for child in dist.iterdir():
                if child.name == MARKER:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        except PermissionError as e:
            raise DeployError(
                f"清理 dist 时文件被占用:{e.filename}\n"
                "上次打包的程序可能还在运行,请关闭后重试。")
    else:
        dist.mkdir(parents=True)
    (dist / MARKER).write_text("generated by QtDeployKit\n", encoding="utf-8")
    return dist


def run_windeployqt(qt_bin: Path, exe_in_dist: Path, extra_args: list[str],
                    qml_dirs: list[Path]) -> None:
    qml_args = []
    for d in qml_dirs:
        if not d.is_dir():
            raise DeployError(f"[qt].qml_dirs 目录不存在:{d}")
        qml_args += ["--qmldir", str(d)]
    cmd = [str(qt_bin / "windeployqt.exe"), "--release", "--no-compiler-runtime",
           *qml_args, *extra_args, str(exe_in_dist)]
    rc = run_streamed(cmd)
    if rc != 0:
        raise DeployError(f"windeployqt 失败(退出码 {rc}),错误信息见上方输出")


def copy_extra_files(cfg: dict, dist: Path) -> list[str]:
    copied = []
    for src, dest in cfg["extra_files"]:
        if isinstance(src, tuple):  # (base, pattern) 通配
            base, pattern = src
            matches = sorted(base.glob(pattern)) if not Path(pattern).is_absolute() else \
                sorted(Path(pattern).parent.glob(Path(pattern).name))
            if not matches:
                raise DeployError(f"extra_files 通配没有匹配到任何文件:{pattern}")
        else:
            if not src.exists():
                raise DeployError(f"extra_files 不存在:{src}")
            matches = [src]
        target_dir = (dist / dest) if dest else dist
        target_dir.mkdir(parents=True, exist_ok=True)
        for m in matches:
            if m.is_dir():
                shutil.copytree(m, target_dir / m.name, dirs_exist_ok=True)
                log(f"      拷贝目录 {m.name}\\")
            else:
                copy_with_progress(m, target_dir / m.name)
            copied.append(m.name)
    return copied


def resolve_vc_runtime(vc: Path | None, machine: str) -> tuple[str, Path | None]:
    """解析 [installer].vc_redist 的两种形态。
    返回 (mode, path):'installer' = vc_redist*.exe 内嵌静默安装;
    'dlls' = 运行时 DLL 目录,直拷进包(app-local);'' = 未配置。"""
    if not vc:
        return "", None
    if vc.is_file():
        return "installer", vc
    if vc.is_dir():
        exes = sorted(f for f in vc.glob("*.exe") if "redist" in f.name.lower())
        match = [f for f in exes if machine in f.name.lower()]
        if match:
            return "installer", match[0]
        if len(exes) == 1:
            return "installer", exes[0]
        if sorted(vc.glob("*.dll")):
            return "dlls", vc
        raise DeployError(f"[installer].vc_redist 目录里既没有 vc_redist*.exe 也没有运行时 DLL:{vc}")
    raise DeployError(f"[installer].vc_redist 路径不存在:{vc}")


def bulk_copy_search_dirs(search_dirs: list[Path], dist: Path) -> set[str]:
    """把 search_dirs 各目录下的所有 DLL(不含子目录)全量拷入 dist。
    返回拷入的文件名集合(小写),供闭包扫描区分「主动引用」和「随包携带」。"""
    payload: set[str] = set()
    for d in search_dirs:
        if not d.is_dir():
            raise DeployError(f"[deps].search_dirs 目录不存在:{d}")
        log(f"      全量拷入 {d}:")
        for f in sorted(d.glob("*.dll")):
            if not (dist / f.name).exists():  # windeployqt/前面目录已放的不覆盖
                copy_with_progress(f, dist / f.name, indent="        ")
            payload.add(f.name.lower())
    return payload


def is_system_dll(name: str) -> bool:
    if name in SYSTEM_DLLS or name.startswith(API_SET_PREFIXES):
        return True
    sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return (sysdir / name).exists()


def scan_and_complete(dist: Path, search_dirs: list[Path], want_machine: str,
                      payload: frozenset[str] = frozenset()) -> dict:
    """从「exe/插件等主动部署的 PE」出发递归扫描导入表,校验依赖闭包。
    payload 是 search_dirs 全量拷入的文件名集合:只有被引用链实际用到的才参与
    扫描,没被引用的当作随包携带的货物,不检查其依赖(比如 debug 版 DLL)。
    缺的 DLL 先在 search_dirs 子目录外兜底查找拷入,仍找不到且不是系统件/
    VC 运行时的记为 missing。返回分类报告。"""
    report = {"copied": [], "vc_runtime": set(), "missing": {}, "arch_mismatch": [], "used_payload": set()}
    queue = [p for p in sorted(dist.rglob("*"))
             if p.suffix.lower() in (".dll", ".exe") and p.name.lower() not in payload]
    scanned: set[str] = set()

    def present(name: str) -> bool:
        return (dist / name).exists()

    while queue:
        pe = queue.pop(0)
        key = pe.name.lower()
        if key in scanned:
            continue
        scanned.add(key)
        machine, imports = parse_pe(pe)
        if machine != want_machine:
            report["arch_mismatch"].append(f"{pe.relative_to(dist)}: {machine}(期望 {want_machine})")
            continue
        for dep in imports:
            if present(dep):
                if dep in payload and dep not in scanned:
                    report["used_payload"].add(dep)
                    queue.append(dist / dep)
                continue
            if dep in VC_RUNTIME_DLLS:
                report["vc_runtime"].add(dep)
                continue
            if dep.startswith(UCRT_PREFIX) or dep == "ucrtbase.dll":
                report["vc_runtime"].add("(UCRT)")
                continue
            if dep in SYSTEM_DLLS or dep.startswith(API_SET_PREFIXES):
                continue
            found = None
            for d in search_dirs:
                cand = d / dep
                if cand.is_file():
                    found = cand
                    break
            if found:
                copy_with_progress(found, dist / found.name, announce=False)
                report["copied"].append(f"{found.name}  <- {found.parent}")
                queue.append(dist / found.name)
            elif is_system_dll(dep):
                continue
            else:
                report["missing"].setdefault(dep, set()).add(pe.name)
    return report


def smoke_test(exe_in_dist: Path, seconds: int = 5) -> None:
    log(f"  启动 {exe_in_dist.name},观察 {seconds} 秒 ...")
    p = subprocess.Popen([str(exe_in_dist)], cwd=str(exe_in_dist.parent))
    time.sleep(seconds)
    if p.poll() is None:
        p.terminate()
        log("  冒烟测试通过:进程存活")
    elif p.returncode == 0:
        log("  冒烟测试通过:进程正常退出")
    else:
        raise DeployError(
            f"冒烟测试失败:进程启动后退出,退出码 0x{p.returncode & 0xFFFFFFFF:08x}\n"
            "常见原因:缺动态加载的 DLL、缺 Qt 插件、VC 运行时未装(本机一般已装,目标机才缺)")


# ---------------------------------------------------------------- 安装包

def generate_iss(cfg: dict, version: str, dist: Path, iscc: Path, machine: str,
                 vc_installer: Path | None):
    tpl_path = Path(__file__).parent / "templates" / "installer.iss.tpl"
    tpl = tpl_path.read_text(encoding="utf-8")

    out_dir = cfg["out_dir"]
    installer_name = cfg["installer_name"] or f"{cfg['name']}-setup"
    app_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "qtdeploykit:" + cfg["name"])).upper()

    lang_lines = ['Name: "english"; MessagesFile: "compiler:Default.isl"']
    if (iscc.parent / "Languages" / "ChineseSimplified.isl").is_file():
        lang_lines.append('Name: "chinesesimplified"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"')

    vc_file_line = vc_run_line = ""
    if vc_installer:
        vc_file_line = f'Source: "{vc_installer}"; DestDir: "{{tmp}}"; Flags: deleteafterinstall'
        vc_run_line = ('Filename: "{tmp}\\' + vc_installer.name + '"; '
                       'Parameters: "/install /quiet /norestart"; '
                       'StatusMsg: "Installing Microsoft Visual C++ Runtime..."; '
                       'Check: not VCRedistInstalled')

    arch_lines = ("ArchitecturesAllowed=x64compatible\n"
                  "ArchitecturesInstallIn64BitMode=x64compatible") if machine == "x64" else ""

    repl = {
        "ARCH_LINES": arch_lines,
        "ARCH": machine,
        "APP_NAME": cfg["name"],
        "APP_VERSION": version,
        "PUBLISHER": cfg["publisher"],
        "EXE_NAME": cfg["exe"].name,
        "APP_ID": app_id,
        "DIST_DIR": str(dist),
        "OUTPUT_DIR": str(out_dir),
        "OUTPUT_BASENAME": installer_name,
        "SETUP_ICON_LINE": f"SetupIconFile={cfg['icon']}" if cfg["icon"] else "",
        "LANGUAGE_LINES": "\n".join(lang_lines),
        "VCREDIST_FILE_LINE": vc_file_line,
        "VCREDIST_RUN_LINE": vc_run_line,
    }
    text = tpl
    for k, v in repl.items():
        text = text.replace(f"@{k}@", v)

    iss = out_dir / "installer.iss"
    iss.write_text(text, encoding="utf-8-sig")
    return iss, out_dir / f"{installer_name}.exe"


def run_iscc(iscc: Path, iss: Path, expected_setup: Path) -> Path:
    rc = run_streamed([str(iscc), str(iss)])
    if rc != 0:
        raise DeployError(f"ISCC 编译失败(退出码 {rc}),错误信息见上方输出")
    if not expected_setup.is_file():
        raise DeployError(f"ISCC 成功但没找到安装包:{expected_setup}")
    return expected_setup


def sign_file(cfg: dict, target: Path) -> None:
    cmd = [cfg["signtool"], "sign", *cfg["sign_args"], str(target)]
    log(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise DeployError(f"signtool 签名失败:\n{r.stdout}\n{r.stderr}")


# ---------------------------------------------------------------- 报告

def write_notes(cfg: dict, version: str, report: dict, extra: list[str],
                setup: Path | None, vc_desc: str) -> Path:
    vc = "、".join(sorted(report["vc_runtime"])) or "(未检测到)"
    copied = "\n".join(f"- {c}" for c in report["copied"]) or "- (无,windeployqt 已收集完整)"
    extra_s = "\n".join(f"- {e}" for e in extra) or "- (无)"
    signed = "已签名" if cfg["sign_enabled"] else "未签名"
    redist = vc_desc

    notes = f"""# {cfg['name']} v{version} 部署说明

由 QtDeployKit 自动生成。

## 依赖扫描结果

- 自动补齐的第三方 DLL:
{copied}
- 配置声明的额外文件:
{extra_s}
- 检出的 VC 运行时引用:{vc}
- VC 运行时方案:{redist}

## VC 运行时

目标机需要 Microsoft Visual C++ 2015-2022 运行库,本包的提供方式见上。
缺它的典型症状是 0xc000012f / 0xc000007b 或「找不到 VCRUNTIME140.dll」。
[installer].vc_redist 支持两种写法:指向 vc_redist.x64.exe(安装时静默安装、
已装跳过,官方下载:https://aka.ms/vs/17/release/vc_redist.x64.exe ),
或指向存放运行时 DLL 的目录(直拷进包,app-local 方式)。

## 杀软误报与白名单({signed})

无签名的新 exe + 安装器特征容易被杀软误报,这是概率问题不是 bug。按优先级:

1. **代码签名**(根治):购买代码签名证书,配置 [signing] 后本工具自动对
   主程序和安装包签名。EV 证书可立即建立 SmartScreen 信誉。
2. **提交厂商白名单**(免费):
   - Microsoft Defender: https://www.microsoft.com/wdsi/filesubmission
   - 360: https://open.soft.360.cn
   - 火绒: https://www.huorong.cn (工单提交误报)
3. **告知用户**:在下载页注明可能误报及原因,提供文件哈希供校验。

## 写权限注意事项

- 安装目录(Program Files)对普通用户只读。程序的配置、日志、缓存必须写到
  用户目录:Qt 里用 QStandardPaths::writableLocation(AppDataLocation)。
- 若程序确实需要写安装目录(不推荐),让用户安装时选「仅为我安装」——本安装包
  的权限模式为 dialog,用户可选装到用户目录,免 UAC 且可写。
- 卸载不会删除用户数据目录,如需清理请在文档中说明位置。
"""
    p = cfg["out_dir"] / "DEPLOY_NOTES.md"
    p.write_text(notes, encoding="utf-8")
    return p


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser(description="QtDeployKit — Qt(MSVC) 一键打包")
    ap.add_argument("config", help="项目配置 .toml 文件")
    ap.add_argument("--skip-installer", action="store_true", help="只收集 DLL,不生成安装包")
    ap.add_argument("--smoke", action="store_true", help="收集后启动主程序做冒烟测试")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    exe: Path = cfg["exe"]

    t_total = time.perf_counter()

    def stage_done(t: float) -> None:
        log(f"      阶段耗时 {time.perf_counter() - t:.1f}s")

    log(f"[1/6] 读取版本与架构:{exe.name}")
    version = get_file_version(exe)
    if not version or version == "0.0.0.0":
        version = "1.0"
        log(f"      exe 没有有效的 FileVersion,安装包元数据版本号用默认 {version}")
    machine, _ = parse_pe(exe)
    if machine not in ("x64", "x86"):
        raise DeployError(f"不支持的目标架构:{machine}")
    log(f"      版本 {version},架构 {machine}")

    log("[2/6] 定位工具链")
    qt_bin = find_qt_bin(cfg)
    qt_core = next((qt_bin / n for n in ("Qt6Core.dll", "Qt5Core.dll") if (qt_bin / n).is_file()), None)
    if qt_core is None:
        raise DeployError(f"{qt_bin} 下找不到 Qt5Core.dll/Qt6Core.dll,确认这是 Qt kit 的 bin 目录")
    qt_machine, _ = parse_pe(qt_core)
    if qt_machine != machine:
        raise DeployError(
            f"架构不匹配:主程序是 {machine},但 Qt kit({qt_bin})是 {qt_machine}。\n"
            "这是 0xc000012f/0xc000007b 的典型来源,请换用对应架构的 Qt kit。")
    iscc = None if args.skip_installer else find_iscc(cfg)
    vc_mode, vc_path = resolve_vc_runtime(cfg["vc_redist"], machine)
    log(f"      Qt: {qt_bin}" + (f"\n      ISCC: {iscc}" if iscc else ""))

    log("[3/6] windeployqt 收集")
    t = time.perf_counter()
    dist = prepare_dist(cfg["out_dir"])
    exe_in_dist = dist / exe.name
    shutil.copy2(exe, exe_in_dist)
    run_windeployqt(qt_bin, exe_in_dist, cfg["windeployqt_args"], cfg["qml_dirs"])
    if not cfg["qml_dirs"] and any((dist / n).exists() for n in ("Qt5Qml.dll", "Qt6Qml.dll")):
        raise DeployError(
            "程序链接了 QML(dist 里有 QtQml.dll),但配置没给 [qt].qml_dirs,\n"
            "windeployqt 不会部署 qml 模块,打出的包在目标机上会白屏/报 QML 模块缺失。\n"
            "请把 QML 源码所在目录(工程里 .qml 文件的根目录,可多个)填入 [qt].qml_dirs。")
    extra = copy_extra_files(cfg, dist)
    payload = bulk_copy_search_dirs(cfg["search_dirs"], dist)
    if vc_mode == "dlls":
        n_vc = 0
        for f in sorted(vc_path.glob("*.dll")):
            if not (dist / f.name).exists():
                shutil.copy2(f, dist / f.name)
                n_vc += 1
        log(f"      VC 运行时 DLL 直拷进包:{n_vc} 个(来自 {vc_path})")
    n_files = sum(1 for _ in dist.rglob("*") if _.is_file())
    total_size = sum(f.stat().st_size for f in dist.rglob("*") if f.is_file())
    log(f"      dist 共 {n_files} 个文件、{fmt_size(total_size)}"
        f"(search_dirs 全量拷入 {len(payload)} 个 DLL,额外文件 {len(extra)} 个)")
    stage_done(t)

    log("[4/6] 依赖闭包扫描")
    t = time.perf_counter()
    report = scan_and_complete(dist, cfg["search_dirs"], machine, frozenset(payload))
    if payload:
        log(f"      search_dirs 拷入的 {len(payload)} 个 DLL 中,"
            f"被引用链实际用到 {len(report['used_payload'])} 个,其余随包携带")
    for c in report["copied"]:
        log(f"      自动补齐: {c}")
    if report["arch_mismatch"]:
        raise DeployError("发现架构不一致的 DLL(0xc000012f 风险):\n  " +
                          "\n  ".join(report["arch_mismatch"]))
    if report["missing"]:
        lines = [f"  {dll}   被引用于: {', '.join(sorted(refs))}"
                 for dll, refs in sorted(report["missing"].items())]
        raise DeployError(
            "以下 DLL 缺失,目标机上会启动失败。请加入 [deps].search_dirs 或 extra_files:\n"
            + "\n".join(lines))
    if report["vc_runtime"] and not vc_mode and not args.skip_installer:
        log("      警告: 程序依赖 VC 运行时,但 [installer].vc_redist 未配置,"
            "安装包将不含运行库(目标机需自装)")
    log("      依赖闭包完整")
    stage_done(t)

    if args.smoke:
        smoke_test(exe_in_dist)

    if cfg["sign_enabled"]:
        log("[5/6] 签名主程序")
        sign_file(cfg, exe_in_dist)
    else:
        log("[5/6] 跳过签名([signing].enabled = false)")

    setup = None
    if args.skip_installer:
        log("[6/6] 跳过安装包(--skip-installer)")
    else:
        log("[6/6] 生成安装包(大体量包 lzma2 压缩可能要几分钟到十几分钟,请耐心)")
        t = time.perf_counter()
        iss, expected = generate_iss(cfg, version, dist, iscc, machine,
                                     vc_path if vc_mode == "installer" else None)
        setup = run_iscc(iscc, iss, expected)
        if cfg["sign_enabled"]:
            sign_file(cfg, setup)
        stage_done(t)

    vc_desc = {"installer": f"内嵌 {vc_path.name if vc_path else ''} 静默安装(已装跳过)",
               "dlls": f"运行时 DLL 直拷进包(来自 {vc_path})",
               "": "未内嵌(目标机需自行安装,见下)"}[vc_mode]
    notes = write_notes(cfg, version, report, extra, setup, vc_desc)
    log("")
    log(f"完成(总耗时 {time.perf_counter() - t_total:.0f} 秒):")
    log(f"  绿色目录   {dist}")
    if setup:
        log(f"  安装包     {setup}  ({setup.stat().st_size / 1048576:.1f} MB)")
    log(f"  部署说明   {notes}")


if __name__ == "__main__":
    try:
        main()
    except DeployError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        sys.exit(1)
