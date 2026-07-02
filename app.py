#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C 盘清理工具 - 后端服务
基于实战清理经验，提供磁盘扫描、分类检测、一键清理功能
"""

import os
import sys
import json
import shutil
import ctypes
import subprocess

# 禁止 subprocess 弹出控制台窗口
NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000

def run_hidden(*args, **kwargs):
    """静默运行外部命令，不弹出控制台窗口"""
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(*args, **kwargs)
import threading
import time
import webbrowser
import signal
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, jsonify, request


# ============ PyInstaller 资源路径 ============

def resource_path(relative_path):
    """兼容 PyInstaller 打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))

# 版本标识（默认 v1.0，通过 app.config['APP_VERSION'] 覆盖）
APP_VERSION = "v1.0"
app.config['APP_VERSION'] = APP_VERSION


# ============ Jinja 上下文: 缓存破坏 + 版本号 ============

@app.context_processor
def inject_cache_bust():
    import random
    return {'cache_bust': random.randint(100000, 999999), 'app_version': app.config.get('APP_VERSION', APP_VERSION)}

# ============ 工具函数 ============

def get_dir_size(path, timeout=10):
    """获取目录大小（字节），支持超时防止单目录卡住"""
    import time
    total = 0
    start = time.time()
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            if time.time() - start > timeout:
                # 超时后，按当前已统计大小返回，不再继续深入
                break
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def format_size(bytes_size):
    """格式化文件大小"""
    if bytes_size == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(bytes_size) < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def is_admin():
    """检查是否管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def get_user_home():
    """获取用户目录"""
    return os.path.expanduser("~")


# ============ 清理目标定义 ============
# 基于实战经验，所有可清理项分类定义

def discover_conda_pkgs_dirs():
    """动态发现 Conda 包缓存目录"""
    dirs = []
    candidates = [
        "C:\\ProgramData\\Anaconda3\\pkgs",
        "C:\\Users\\" + os.getlogin() + "\\Anaconda3\\pkgs",
        "C:\\ProgramData\\Miniconda3\\pkgs",
        "C:\\Users\\" + os.getlogin() + "\\miniconda3\\pkgs",
    ]
    for c in candidates:
        if os.path.exists(c):
            dirs.append(c)
    # 从 conda 命令获取 pkgs_dirs
    try:
        r = run_hidden(["conda", "config", "--show", "pkgs_dirs"],
                           capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("pkgs_dirs"):
                d = line.strip("'\"[] ,")
                if d and os.path.exists(d):
                    dirs.append(d)
    except:
        pass
    return list(set(dirs))


def discover_dingtalk_dirs():
    """动态发现钉钉缓存目录"""
    home = get_user_home()
    local = os.path.join(home, "AppData", "Local")
    dirs = []
    try:
        for name in os.listdir(local):
            if name.startswith("DingTalk_"):
                d = os.path.join(local, name)
                if os.path.isdir(d):
                    dirs.append(d)
    except:
        pass
    return dirs


def discover_updater_dirs():
    """动态发现各种应用的 updater 缓存目录"""
    home = get_user_home()
    local = os.path.join(home, "AppData", "Local")
    dirs = []
    try:
        for name in os.listdir(local):
            if "updater" in name.lower() or name.endswith("-updater"):
                d = os.path.join(local, name)
                if os.path.isdir(d):
                    dirs.append(d)
    except:
        pass
    return dirs


def discover_browser_profiles():
    """动态发现所有浏览器缓存路径"""
    home = get_user_home()
    local = os.path.join(home, "AppData", "Local")
    paths = []

    # Chrome - 扫描所有用户配置文件
    chrome_base = os.path.join(local, "Google", "Chrome", "User Data")
    if os.path.exists(chrome_base):
        for name in ["Default"] + [d for d in os.listdir(chrome_base) if d.startswith("Profile ")]:
            profile = os.path.join(chrome_base, name)
            if os.path.isdir(profile):
                paths.extend([
                    os.path.join(profile, "Cache"),
                    os.path.join(profile, "Code Cache"),
                    os.path.join(profile, "GPUCache"),
                    os.path.join(profile, "Service Worker"),
                ])

    # Edge - 扫描所有用户配置文件
    edge_base = os.path.join(local, "Microsoft", "Edge", "User Data")
    if os.path.exists(edge_base):
        for name in ["Default"] + [d for d in os.listdir(edge_base) if d.startswith("Profile ")]:
            profile = os.path.join(edge_base, name)
            if os.path.isdir(profile):
                paths.extend([
                    os.path.join(profile, "Cache"),
                    os.path.join(profile, "Code Cache"),
                    os.path.join(profile, "GPUCache"),
                ])

    # Firefox
    ff_base = os.path.join(local, "Mozilla", "Firefox", "Profiles")
    if os.path.exists(ff_base):
        try:
            for name in os.listdir(ff_base):
                profile = os.path.join(ff_base, name)
                if os.path.isdir(profile):
                    paths.extend([
                        os.path.join(profile, "cache2"),
                        os.path.join(profile, "thumbnails"),
                    ])
        except:
            pass

    return paths


def discover_app_logs():
    """动态发现各应用的日志/缓存子目录（不误伤用户数据）"""
    home = get_user_home()
    local = os.path.join(home, "AppData", "Local")
    roaming = os.path.join(home, "AppData", "Roaming")
    dirs = []

    # 常见应用的日志/缓存子目录模式
    apps = [
        # (base, app_sub, cache_sub_patterns)
        (roaming, "Tencent", ["*Logs*", "*log*", "*Cache*", "*cache*", "*GPUCache*", "TBS"]),
        (local, "Tencent", ["*Logs*", "*log*", "*Cache*", "*cache*", "*GPUCache*"]),
        (roaming, "discord", ["Cache", "Code Cache", "GPUCache", "logs"]),
        (local, "discord", ["Cache", "Code Cache", "GPUCache"]),
        (roaming, "Slack", ["Cache", "Code Cache", "logs"]),
        (local, "Slack", ["Cache", "Code Cache"]),
        (roaming, "Spotify", ["Cache", "logs"]),
        (local, "Spotify", ["Cache"]),
        (roaming, "steam", ["logs", "appcache"]),
        (local, "steam", ["htmlcache"]),
        (roaming, "qBittorrent", ["logs"]),
        (local, "qBittorrent", ["logs"]),
    ]

    for base, app, patterns in apps:
        app_dir = os.path.join(base, app)
        if not os.path.exists(app_dir):
            continue
        try:
            for item in os.listdir(app_dir):
                for pat in patterns:
                    import fnmatch
                    if fnmatch.fnmatch(item, pat):
                        full = os.path.join(app_dir, item)
                        if os.path.isdir(full):
                            dirs.append(full)
                        break
        except:
            pass

    return dirs

def get_clean_targets():
    """返回所有可清理目标的配置（动态发现路径）"""
    home = get_user_home()
    local = os.path.join(home, "AppData", "Local")
    roaming = os.path.join(home, "AppData", "Roaming")

    return {
        # ===== 安全清理项 =====
        "system_temp": {
            "name": "系统临时文件",
            "icon": "fa-trash",
            "color": "#ff6b6b",
            "safe": True,
            "paths": [
                os.path.join(local, "Temp"),
                "C:\\Windows\\Temp",
            ],
            "desc": "Windows 和应用程序的临时文件，删除不影响任何功能"
        },
        "browser_cache": {
            "name": "浏览器缓存",
            "icon": "fa-globe",
            "color": "#4ecdc4",
            "safe": True,
            "paths": discover_browser_profiles(),
            "desc": "Chrome / Edge / Firefox 浏览器缓存，清理后网页首次加载稍慢"
        },
        "vscode_cache": {
            "name": "VS Code 缓存",
            "icon": "fa-code",
            "color": "#45b7d1",
            "safe": True,
            "paths": [
                os.path.join(roaming, "Code", "Cache"),
                os.path.join(roaming, "Code", "CachedData"),
                os.path.join(roaming, "Code", "logs"),
                os.path.join(roaming, "Code", "User", "workspaceStorage"),
                os.path.join(local, "Microsoft", "vscode-cpptools"),
                os.path.join(local, "Code", "Cache"),
                os.path.join(local, "Code", "CachedData"),
                os.path.join(local, "Code", "CachedExtensionVSIXs"),
                os.path.join(local, "Code", "Crashpad"),
            ],
            "desc": "VS Code 工作区缓存、C++ 智能感知索引，清理后自动重建"
        },
        "conda_cache": {
            "name": "Conda / pip 包缓存",
            "icon": "fa-box",
            "color": "#96ceb4",
            "safe": True,
            "paths": discover_conda_pkgs_dirs() + [
                os.path.join(local, "pip", "cache"),
            ],
            "desc": "Conda 和 pip 的下载包缓存，清理后已安装的包不受影响"
        },
        "app_logs": {
            "name": "应用日志与缓存",
            "icon": "fa-file-alt",
            "color": "#ffeaa7",
            "safe": True,
            "paths": discover_app_logs(),
            "desc": "常见应用（微信/QQ/Discord/Slack 等）的日志和缓存文件"
        },
        "dingtalk_cache": {
            "name": "钉钉缓存",
            "icon": "fa-comments",
            "color": "#a29bfe",
            "safe": True,
            "paths": (lambda dirs: [
                os.path.join(d, c) for d in dirs for c in ("Cache", "Code Cache", "Service Worker")
            ])(discover_dingtalk_dirs()),
            "desc": "钉钉浏览器缓存，自动发现所有钉钉版本"
        },
        "jetbrains_cache": {
            "name": "JetBrains IDE 缓存",
            "icon": "fa-rocket",
            "color": "#fd79a8",
            "safe": True,
            "paths": [
                os.path.join(local, "JetBrains"),
            ],
            "desc": "PyCharm / IDEA 等 JetBrains IDE 的索引缓存"
        },
        "crash_dumps": {
            "name": "崩溃转储文件",
            "icon": "fa-bug",
            "color": "#e17055",
            "safe": True,
            "paths": [
                os.path.join(local, "CrashDumps"),
                "C:\\Windows\\memory.dmp",
                "C:\\Windows\\Minidump",
            ],
            "desc": "程序崩溃时生成的调试转储文件，一般无用可删"
        },
        "updater_cache": {
            "name": "应用更新缓存",
            "icon": "fa-download",
            "color": "#74b9ff",
            "safe": True,
            "paths": discover_updater_dirs(),
            "desc": "各应用的更新下载缓存，自动发现所有 *updater* 目录"
        },
        "thumbnails": {
            "name": "系统缩略图缓存",
            "icon": "fa-image",
            "color": "#00cec9",
            "safe": True,
            "paths": [
                os.path.join(local, "Microsoft", "Windows", "Explorer"),
            ],
            "desc": "资源管理器缩略图缓存，清理后打开图片文件夹会稍慢"
        },
        "delivery_optimization": {
            "name": "传递优化缓存",
            "icon": "fa-satellite-dish",
            "color": "#6c5ce7",
            "safe": True,
            "paths": [
                "C:\\Windows\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache",
            ],
            "desc": "Windows 更新传递优化下载缓存，可安全删除"
        },
        "windows_update": {
            "name": "Windows 更新缓存",
            "icon": "fa-windows",
            "color": "#00b894",
            "safe": True,
            "paths": [
                "C:\\Windows\\SoftwareDistribution\\Download",
            ],
            "desc": "Windows Update 已下载的安装包缓存"
        },
        "search_index": {
            "name": "Windows 搜索索引",
            "icon": "fa-search",
            "color": "#0984e3",
            "safe": True,
            "paths": [
                "C:\\ProgramData\\Microsoft\\Search\\Data",
            ],
            "desc": "Windows 搜索索引数据，删除后会自动重建（需重启搜索服务）",
            "special": "search_index"
        },
        "package_cache": {
            "name": "安装包缓存",
            "icon": "fa-archive",
            "color": "#636e72",
            "safe": True,
            "paths": [
                "C:\\ProgramData\\Package Cache",
            ],
            "desc": "Visual Studio 等已安装程序的包缓存"
        },
        "font_cache": {
            "name": "字体缓存",
            "icon": "fa-font",
            "color": "#e84393",
            "safe": True,
            "paths": [
                os.path.join(local, "Microsoft", "Windows", "FontCache"),
            ],
            "desc": "Windows 字体缓存文件，清理后系统自动重建"
        },
        # ===== 需管理员权限的项 =====
        "recycle_bin": {
            "name": "回收站",
            "icon": "fa-recycle",
            "color": "#2d3436",
            "safe": True,
            "paths": [],
            "desc": "回收站中的文件，清空后不可恢复",
            "special": "recycle_bin"
        },
        "hibernation": {
            "name": "休眠文件",
            "icon": "fa-moon",
            "color": "#6c5ce7",
            "safe": False,
            "paths": [],
            "desc": "关闭休眠功能可释放 ~6GB（需管理员权限，执行 powercfg /h off）",
            "special": "hibernation"
        },
        "dism_cleanup": {
            "name": "Windows 组件存储",
            "icon": "fa-cube",
            "color": "#b2bec3",
            "safe": False,
            "paths": [],
            "desc": "Windows 更新后残留的旧组件文件，可释放大量空间（需管理员，执行 DISM 清理）",
            "special": "dism_cleanup"
        },
    }


# ============ 扫描状态 ============

scan_progress = {"status": "idle", "current": "", "progress": 0}
clean_progress = {"status": "idle", "current": "", "progress": 0, "freed": 0}


# ============ API 路由 ============

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/disk")
def api_disk():
    """获取磁盘空间信息"""
    try:
        result = run_hidden(
            ["powershell", "-Command",
             "Get-WmiObject Win32_LogicalDisk -Filter \"DeviceID='C:'\" | "
             "Select-Object @{N='Size';E={$_.Size}}, @{N='Free';E={$_.FreeSpace}} | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout.strip())
        size = int(data["Size"])
        free = int(data["Free"])
        used = size - free
        return jsonify({
            "total": size,
            "used": used,
            "free": free,
            "total_str": format_size(size),
            "used_str": format_size(used),
            "free_str": format_size(free),
            "used_pct": round(used / size * 100, 1) if size > 0 else 0,
            "free_pct": round(free / size * 100, 1) if size > 0 else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scan")
def api_scan():
    """扫描所有清理目标的大小"""
    targets = get_clean_targets()
    results = []
    total_cleanable = 0

    for key, target in targets.items():
        size = 0
        if target.get("special") == "hibernation":
            # 检查 hiberfil.sys
            if os.path.exists("C:\\hiberfil.sys"):
                try:
                    size = os.path.getsize("C:\\hiberfil.sys")
                except:
                    pass
        elif target.get("special") == "recycle_bin":
            # 回收站大小
            try:
                result = run_hidden(
                    ["powershell", "-Command",
                     "(Get-ChildItem 'C:\\$Recycle.Bin' -Recurse -File -Force -ErrorAction SilentlyContinue | "
                     "Measure-Object -Property Length -Sum).Sum"],
                    capture_output=True, text=True, timeout=15
                )
                size = int(result.stdout.strip()) if result.stdout.strip() else 0
            except:
                pass
        elif target.get("special") == "dism_cleanup":
            # DISM 组件存储可回收空间（通过分析备份功能获取）
            try:
                result = run_hidden(
                    ["powershell", "-Command",
                     "chcp 65001 > $null; "
                     "$output = & Dism /Online /English /Cleanup-Image /AnalyzeComponentStore 2>&1; "
                     "$line = $output | Select-String 'Backups and Disabled Features'; "
                     "if ($line) { $nums = [regex]::Matches($line, '[\\d.]+'); "
                     "if ($nums.Count -ge 1) { $size = [double]$nums[0].Value; "
                     "if ($line -match 'GB') { [int]($size * 1073741824) } "
                     "elseif ($line -match 'MB') { [int]($size * 1048576) } "
                     "else { [int]$size } } else { 0 } } else { 0 }"],
                    capture_output=True, text=True, timeout=60
                )
                val = result.stdout.strip()
                size = int(val) if val and val.isdigit() else 0
            except:
                pass
        else:
            for p in target["paths"]:
                if os.path.exists(p):
                    size += get_dir_size(p)

        results.append({
            "key": key,
            "name": target["name"],
            "icon": target["icon"],
            "color": target["color"],
            "safe": target["safe"],
            "desc": target["desc"],
            "size": size,
            "size_str": format_size(size),
            "special": target.get("special", ""),
        })
        if target["safe"] and size > 0:
            total_cleanable += size

    # 按大小降序
    results.sort(key=lambda x: x["size"], reverse=True)

    return jsonify({
        "targets": results,
        "total_cleanable": total_cleanable,
        "total_cleanable_str": format_size(total_cleanable),
    })


@app.route("/api/scan_large_files")
def api_scan_large_files():
    """扫描 C 盘大文件 (>500MB)"""
    home = get_user_home()
    large_files = []

    scan_dirs = [
        home,
        "C:\\ProgramData",
    ]

    for scan_dir in scan_dirs:
        try:
            for dirpath, dirnames, filenames in os.walk(scan_dir):
                # 跳过 .workbuddy 目录
                if ".workbuddy" in dirpath:
                    continue
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        size = os.path.getsize(fp)
                        if size > 500 * 1024 * 1024:  # >500MB
                            large_files.append({
                                "path": fp,
                                "name": f,
                                "size": size,
                                "size_str": format_size(size),
                                "dir": os.path.dirname(fp),
                            })
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            pass

    large_files.sort(key=lambda x: x["size"], reverse=True)
    large_files = large_files[:30]  # Top 30

    return jsonify({"files": large_files})


def clean_path(path):
    """清理一个路径下的所有内容（保留目录本身），返回实际释放的字节数"""
    if not os.path.exists(path):
        return 0

    before_size = get_dir_size(path)

    try:
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass

    after_size = get_dir_size(path)
    freed = before_size - after_size
    return max(freed, 0)


@app.route("/api/clean", methods=["POST"])
def api_clean():
    """执行清理"""
    data = request.json
    keys = data.get("keys", [])

    targets = get_clean_targets()
    total_freed = 0
    results = []

    for key in keys:
        if key not in targets:
            continue
        target = targets[key]
        freed = 0

        if target.get("special") == "hibernation":
            # 关闭休眠
            before_size = 0
            if os.path.exists("C:\\hiberfil.sys"):
                try:
                    before_size = os.path.getsize("C:\\hiberfil.sys")
                except:
                    pass
            try:
                run_hidden(["powercfg", "/h", "off"], capture_output=True, timeout=10)
                time.sleep(1)
            except:
                pass
            # 实际释放 = 清理前大小 - 清理后大小
            after_size = 0
            if os.path.exists("C:\\hiberfil.sys"):
                try:
                    after_size = os.path.getsize("C:\\hiberfil.sys")
                except:
                    pass
            freed = max(before_size - after_size, 0)
        elif target.get("special") == "recycle_bin":
            # 清空回收站
            try:
                run_hidden(
                    ["powershell", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                    capture_output=True, timeout=60
                )
                freed = 0  # 无法精确知道释放了多少
            except:
                pass
        elif target.get("special") == "search_index":
            # 搜索索引需要停止服务再清理
            try:
                run_hidden(["powershell", "-Command", "Stop-Service WSearch -Force -ErrorAction SilentlyContinue"],
                               capture_output=True, timeout=15)
                time.sleep(2)
                freed = clean_path("C:\\ProgramData\\Microsoft\\Search\\Data")
                run_hidden(["powershell", "-Command", "Start-Service WSearch -ErrorAction SilentlyContinue"],
                               capture_output=True, timeout=15)
            except:
                pass
        elif target.get("special") == "dism_cleanup":
            # DISM 组件清理
            try:
                result = run_hidden(
                    ["Dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
                    capture_output=True, text=True, timeout=600
                )
                # DISM 清理后无法精确知道释放了多少，返回 0 让前端显示"已执行"
                freed = 0
            except:
                pass
        else:
            for p in target["paths"]:
                freed += clean_path(p)

        total_freed += freed
        results.append({
            "key": key,
            "name": target["name"],
            "freed": freed,
            "freed_str": format_size(freed),
        })

    return jsonify({
        "results": results,
        "total_freed": total_freed,
        "total_freed_str": format_size(total_freed),
    })


@app.route("/api/dism")
def api_dism():
    """运行 DISM 组件清理（需要管理员）"""
    try:
        result = run_hidden(
            ["Dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            capture_output=True, text=True, timeout=600
        )
        return jsonify({"output": result.stdout, "returncode": result.returncode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """关闭服务（退出程序）"""
    def do_shutdown():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=do_shutdown, daemon=True).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    import socket

    PORT = 18080

    # 检查端口是否被占用，如果是则尝试释放
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    if is_port_in_use(PORT):
        # 端口被占用，尝试杀掉占用进程
        try:
            run_hidden(
                ["powershell", "-Command",
                 f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue | "
                 "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                capture_output=True, timeout=10
            )
            time.sleep(2)
        except:
            pass

    # 延迟 1.5 秒后自动打开浏览器
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=PORT, debug=False)
