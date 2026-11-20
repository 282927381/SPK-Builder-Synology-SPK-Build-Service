#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spkpack.py — 生成 Synology .spk 安装包的核心模块(纯标准库,可选 Pillow 画图标)。

一个 .spk 的结构:
  外层 = 不压缩的 tar 归档,内含:
    INFO               元信息(key="value" 文本)
    package.tgz        gzip tar,装到 /var/packages/<包名>/target/
    scripts/           生命周期脚本(preinst/postinst/.../start-stop-status)
    PACKAGE_ICON.PNG / PACKAGE_ICON_256.PNG
    (可选) conf/  WIZARD_UIFILES/  LICENSE
"""
import io
import json
import os
import shutil
import tarfile
import tempfile

# 哪些文件需要 0755(可执行)
EXEC_NAMES = {"start-stop-status", "run", "service"}
EXEC_EXTS = {"", ".sh", ".py", ".pl", ".bash", ".cgi", ".rb", ".php"}

# 架构 -> 群晖机型代号列表。写入 INFO 的 arch 字段,用于第三方套件源(如 sspks-imnks)
# 按机型精确分发:同一架构家族共享一个通用包(而非每机型单独编译一个包),靠 arch 字段
# 的空格分隔多机型列表覆盖机型。家族代号放在最前(sspks-imnks 认 x86_64 / armv8),
# 后面跟该家族所有具体机型代号,保证群晖任何具体机型都能匹配到。
# 机型代号与 sspks-imnks 的 conf/synology_models.yaml 保持一致(1:1 对齐):
#   x86_64 家族 22 个 SoC;armv8 家族 3 个 SoC。
# 注意:sspks-imnks 用 armv8 而非 arm64,故 arm64 架构需同时写 armv8 / arm64 / aarch64。
ARCH_MODELS = {
    "x86_64": [
        "x86_64", "apollolake", "avoton", "braswell", "broadwell",
        "broadwellnk", "broadwellnkv2", "broadwellntbap", "bromolow",
        "cedarview", "denverton", "epyc7002", "epyc7003", "geminilake",
        "geminilakenk", "grantley", "icelaked", "kvmx64", "purley",
        "r1000", "r1000nk", "v1000", "v1000nk",
    ],
    "armv7": [
        "armv7", "armada370", "armada375", "armada38x", "armadaxp", "alpine",
        "alpine4k", "monaco", "comcerto2k", "hi3535",
    ],
    "arm64": [
        "armv8", "arm64", "aarch64", "rtd1296", "rtd1619b", "armada37xx",
    ],
    "noarch": ["noarch"],
}


def arch_field_value(arch):
    """返回写入 INFO arch 字段的值:该架构家族代号 + 所有具体机型代号(空格分隔)。"""
    models = ARCH_MODELS.get(arch)
    if models:
        return " ".join(models)
    return arch


def _norm(p):
    return p.replace(os.sep, "/")


def _long_path(path):
    """Windows 下为路径添加 \\\\?\\\\ 前缀,以支持超过 260 字符(MAX_PATH)的长路径。
    fengoffice 等套件含超长文件名的资源,不解包/打包时 open()/stat() 会因路径过长报
    [Errno 2] No such file or directory,本函数用于规避该限制。"""
    if os.name != "nt":
        return path
    p = str(path)
    if p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\" + os.path.abspath(p).replace("/", "\\")


def rmtree(path):
    """删除目录树,兼容超长路径(Windows MAX_PATH)。重新导入套件时旧目录里可能
    残留超长路径文件,直接 shutil.rmtree 会失败,这里用长路径前缀逐个删除。"""
    if os.name != "nt":
        shutil.rmtree(path, ignore_errors=True)
        return
    p = _long_path(path)
    if not os.path.isdir(p):
        try:
            os.remove(p)
        except OSError:
            pass
        return
    for root, dirs, files in os.walk(p, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    try:
        os.rmdir(p)
    except OSError:
        pass


def _is_exec(relpath):
    rel = _norm(relpath)
    name = os.path.basename(rel)
    ext = os.path.splitext(name)[1].lower()
    parts = rel.split("/")
    if "bin" in parts or "scripts" in parts or "sbin" in parts:
        return True
    if name in EXEC_NAMES:
        return True
    if ext in EXEC_EXTS:
        return True
    return False


def add_file(tar, filepath, arcname, mode=None):
    """向 tar 添加一个文件,自动决定 0644/0755。"""
    info = tar.gettarinfo(_long_path(filepath), arcname=_norm(arcname))
    if mode is not None:
        info.mode = mode
    else:
        info.mode = 0o755 if _is_exec(arcname) else 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    with open(_long_path(filepath), "rb") as fh:
        tar.addfile(info, fh)


def add_tree(tar, src_dir, prefix=""):
    """把 src_dir 下所有内容加入 tar,保留相对路径(可加 prefix)。"""
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        files.sort()
        rel_root = os.path.relpath(root, src_dir)
        if rel_root == ".":
            rel_root = ""
        for d in dirs:
            arc = _norm(os.path.join(prefix, rel_root, d)) if rel_root else _norm(os.path.join(prefix, d))
            ti = tarfile.TarInfo(arc)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
            ti.uid = ti.gid = 0
            tar.addfile(ti)
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src_dir)
            arc = _norm(os.path.join(prefix, rel))
            add_file(tar, full, arc)


def render_info(fields):
    """把字段字典渲染成 INFO 文本。"""
    out = []
    for k, v in fields.items():
        if v is None or v == "":
            continue
        v = str(v).replace("\\", "\\\\").replace('"', '\\"')
        out.append('{k}="{v}"'.format(k=k, v=v))
    return "\n".join(out) + "\n"


def parse_info(text):
    """把 INFO 文本解析成字段字典(key -> 去除引号后的值)。"""
    info = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip().strip('"').strip()
    return info


# 二次打包时应从原包 INFO 原样继承的字段（用户表单没有这些字段，丢失会导致
# 「打开」按钮消失、依赖缺失、帮助链接/更新说明丢失等问题）。
# 注意 checksum 除外:它在 build_spk 里按新生成的 package.tgz 重新计算。
PRESERVE_INFO_FIELDS = [
    # 套件中心「打开」按钮 / DSM UI 集成
    "adminport", "adminprotocol", "adminurl", "adminport_http", "adminport_https",
    "dsmuidir", "dsmappname", "dsmapppage", "dsmapplaunchname", "checkport",
    # 依赖与安装
    "install_dep_packages", "install_dep_services", "start_dep_services",
    "ctl_uninstall", "silent_upgrade", "startable", "firmware",
    # 其他元信息
    "helpurl", "report_url", "changelog", "thirdparty",
]


def md5_file(path):
    """计算文件 MD5(分块读取,兼容大文件)。"""
    import hashlib
    h = hashlib.md5()
    with open(_long_path(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def render_start_stop_status(pkg, binary, start_cmd=None, stop_cmd=None):
    """生成默认 start-stop-status 脚本。"""
    b = '"$TARGET/bin/%s"' % binary
    start = start_cmd or ('%s >>"$LOG" 2>&1 & echo $! > "$PIDFILE"' % b)
    stop = stop_cmd or ('[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; rm -f "$PIDFILE"')
    lines = [
        "#!/bin/sh",
        'PKG="%s"' % pkg,
        'TARGET="/var/packages/$PKG/target"',
        'VAR="/var/packages/$PKG/var"',
        'PIDFILE="$VAR/$PKG.pid"',
        'LOG="$VAR/$PKG.log"',
        'mkdir -p "$VAR"',
        "",
        "start_daemon() {",
        "  %s" % start,
        "}",
        "",
        "stop_daemon() {",
        "  %s" % stop,
        "}",
        "",
        "status_daemon() {",
        '  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then exit 0; else exit 3; fi',
        "}",
        "",
        'case "$1" in',
        "  start)  start_daemon;  exit 0 ;;",
        "  stop)   stop_daemon;   exit 0 ;;",
        "  status) status_daemon ;;",
        "esac",
        "exit 0",
    ]
    return "\n".join(lines) + "\n"


def make_icon(path, size, color=(47, 128, 237)):
    """生成占位图标(优先 Pillow)。"""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (size, size), color)
        d = ImageDraw.Draw(img)
        margin = max(2, size // 8)
        d.rectangle(
            [margin, margin, size - margin - 1, size - margin - 1],
            outline=(255, 255, 255), width=max(1, size // 32),
        )
        img.save(path, "PNG")
        return True
    except Exception:
        return False


def _resize_icon_bytes(src_path, size):
    """把 src 图标缩放到 size x size,返回 PNG 字节(失败返回 None)。"""
    try:
        from PIL import Image
        import io
        img = Image.open(_long_path(src_path)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


def _add_tar_bytes(tar, arcname, data, mode=0o644):
    info = tarfile.TarInfo(_norm(arcname))
    info.size = len(data)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def _render_dsm_config(name, displayname, description, port):
    """生成 DSM 桌面图标配置(app/config)的 JSON 文本。"""
    app_id = "com.synocommunity.packages." + name
    config = {
        ".url": {
            app_id: {
                "title": displayname or name,
                "desc": description or "",
                "icon": "images/%s-{0}.png" % name,
                "type": "url",
                "protocol": "http",
                "port": str(port),
                "url": "/",
                "allUsers": True,
                "grantPrivilege": "all",
                "advanceGrantPrivilege": True,
            }
        }
    }
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def add_dsm_ui(tar, name, displayname, description, port, icon_src=None):
    """把 DSM 桌面图标(config + app/images/ 图标)写进 tar。
    前提:原包缺少 app/config,但有 Web 端口。"""
    # 1) config
    _add_tar_bytes(tar, "app/config", _render_dsm_config(name, displayname, description, port).encode("utf-8"))
    # 2) 图标(16/24/32/48/64/72/256)
    made = 0
    if icon_src and os.path.isfile(icon_src):
        for size in (16, 24, 32, 48, 64, 72, 256):
            data = _resize_icon_bytes(icon_src, size)
            if data:
                _add_tar_bytes(tar, "app/images/%s-%d.png" % (name, size), data)
                made += 1
    if made == 0:
        # 无 Pillow 或无源图标:生成纯色占位图标
        for size in (16, 24, 32, 48, 64, 72, 256):
            tmp = os.path.join(tempfile.gettempdir(), "_spk_icon_%d.png" % size)
            if make_icon(tmp, size):
                with open(_long_path(tmp), "rb") as fh:
                    _add_tar_bytes(tar, "app/images/%s-%d.png" % (name, size), fh.read())
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return True


def build_spk(output_dir, *, name, version, arch, info_fields, target_dir,
              scripts_dir=None, icons_dir=None, binary=None,
              start_cmd=None, stop_cmd=None, extra_dir=None,
              run_as=None, run_user=None, run_group=None, symlinks=None,
              web_port=None):
    """把 target_dir 打包为 <output_dir>/<name>_<arch>-<version>.spk,返回 spk 路径。
    symlinks: 可选,符号链接列表 [(相对路径, 目标), ...],写入 package.tgz。
    web_port: 可选,Web 服务端口;若原包缺 app/config 但有端口,则自动生成 DSM 桌面图标。"""
    os.makedirs(output_dir, exist_ok=True)
    spk_name = "{n}_{a}-{v}.spk".format(n=name, a=arch, v=version)
    spk_path = os.path.join(output_dir, spk_name)
    tmp_tgz = os.path.join(output_dir, "." + spk_name + ".package.tgz")
    stage = os.path.join(output_dir, "." + spk_name + ".stage")

    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)

    # 1) package.tgz = gzip tar(target_dir 的内容)
    with tarfile.open(tmp_tgz, "w:gz") as tar:
        add_tree(tar, target_dir)
        for link_name, link_target in (symlinks or []):
            ti = tarfile.TarInfo(_norm(link_name))
            ti.type = tarfile.SYMTYPE
            ti.linkname = link_target
            ti.mode = 0o777
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            tar.addfile(ti)
        # DSM 桌面图标:原包缺 app/config 但有 Web 端口时自动生成
        if web_port and not os.path.isfile(os.path.join(target_dir, "app", "config")):
            icon_src = None
            if icons_dir and os.path.isdir(icons_dir):
                for cand in ("PACKAGE_ICON_256.PNG", "PACKAGE_ICON.PNG"):
                    p = os.path.join(icons_dir, cand)
                    if os.path.isfile(p):
                        icon_src = p
                        break
            add_dsm_ui(tar, name,
                       info_fields.get("displayname") or name,
                       info_fields.get("description") or "",
                       web_port, icon_src)

    # 2) INFO
    info_fields = dict(info_fields)
    info_fields.setdefault("package", name)
    info_fields.setdefault("version", version)
    info_fields.setdefault("arch", arch_field_value(arch))
    info_fields.setdefault("os_min_ver", "7.0-40000")
    # checksum = package.tgz 的 MD5(始终按新包重新计算,保证与 package.tgz 一致)
    info_fields["checksum"] = md5_file(tmp_tgz)
    with open(os.path.join(stage, "INFO"), "w", encoding="utf-8") as fh:
        fh.write(render_info(info_fields))

    shutil.copyfile(tmp_tgz, os.path.join(stage, "package.tgz"))

    # 3) scripts
    sdir = os.path.join(stage, "scripts")
    os.makedirs(sdir, exist_ok=True)
    if scripts_dir and os.path.isdir(scripts_dir):
        for f in os.listdir(scripts_dir):
            src = os.path.join(scripts_dir, f)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(sdir, f))
    for f in ("preinst", "postinst", "preuninst", "postuninst", "preupgrade", "postupgrade"):
        p = os.path.join(sdir, f)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
    sss = os.path.join(sdir, "start-stop-status")
    if not os.path.exists(sss):
        with open(sss, "w", encoding="utf-8") as fh:
            fh.write(render_start_stop_status(name, binary or name, start_cmd, stop_cmd))

    # 4) icons
    if icons_dir and os.path.isdir(icons_dir):
        for f in os.listdir(icons_dir):
            if f.upper().startswith("PACKAGE_ICON") and f.upper().endswith(".PNG"):
                shutil.copyfile(os.path.join(icons_dir, f), os.path.join(stage, f))
    if not os.path.exists(os.path.join(stage, "PACKAGE_ICON.PNG")):
        make_icon(os.path.join(stage, "PACKAGE_ICON.PNG"), 64)
    if not os.path.exists(os.path.join(stage, "PACKAGE_ICON_256.PNG")):
        make_icon(os.path.join(stage, "PACKAGE_ICON_256.PNG"), 256)

    # 5) 额外的外层资源(conf / WIZARD_UIFILES / LICENSE)
    if extra_dir and os.path.isdir(extra_dir):
        for entry in ("conf", "WIZARD_UIFILES", "LICENSE"):
            src = os.path.join(extra_dir, entry)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(stage, entry), dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copyfile(src, os.path.join(stage, entry))

    # 5.5) 运行权限(conf/privilege)——在 extra_dir 之后生成,确保用户选择优先
    if run_as in ("root", "package"):
        os.makedirs(os.path.join(stage, "conf"), exist_ok=True)
        priv = {"defaults": {"run-as": run_as}}
        if run_as == "package" and run_user:
            priv["username"] = run_user
        if run_group:
            priv["groupname"] = run_group
        with open(os.path.join(stage, "conf", "privilege"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(priv, ensure_ascii=False, indent=2) + "\n")

    # 6) 外层 = 不压缩 tar,INFO 放最前
    with tarfile.open(spk_path, "w") as tar:
        add_file(tar, os.path.join(stage, "INFO"), "INFO", 0o644)
        for entry in sorted(os.listdir(stage)):
            if entry == "INFO":
                continue
            full = os.path.join(stage, entry)
            if os.path.isdir(full):
                add_tree(tar, full, entry)
            else:
                add_file(tar, full, entry)

    os.remove(tmp_tgz)
    shutil.rmtree(stage)
    return spk_path


def unpack_spk(spk_path, out_dir, log=None):
    """解包 .spk 为「可二次打包」的工程目录:
    外层文件(INFO/package.tgz/scripts/图标/conf 等)-> out_dir/ 根目录,
    内层 package.tgz -> out_dir/target/。
    返回 {"info": {key:value}, "outer": [..], "target": [..]}。"""
    import io

    def _log(m):
        if log:
            log(m)

    _log("解包: %s" % os.path.basename(spk_path))
    os.makedirs(out_dir, exist_ok=True)
    target_dir = os.path.join(out_dir, "target")
    os.makedirs(target_dir, exist_ok=True)

    info = {}
    outer_files = []
    target_files = []
    symlinks = []  # 记录 package.tgz 内的符号链接 (相对 target/ 的路径, 目标)

    def _safe_write(dest_base, arcname, data):
        base = os.path.abspath(dest_base)
        target = os.path.abspath(os.path.join(dest_base, arcname))
        if not (target == base or target.startswith(base + os.sep)):
            return False
        os.makedirs(_long_path(os.path.dirname(target)), exist_ok=True)
        with open(_long_path(target), "wb") as fh:
            fh.write(data)
        return True

    def _extract(tar, dest_dir, collect):
        for m in tar.getmembers():
            if m.isdir():
                continue
            if m.issym() or m.islnk():
                name = m.name
                if name.startswith("./"):
                    name = name[2:]
                symlinks.append((name, m.linkname))
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            if _safe_write(dest_dir, m.name, f.read()):
                collect.append(m.name)

    with tarfile.open(spk_path, "r:*") as t:
        for m in t.getmembers():
            if m.isdir():
                continue
            f = t.extractfile(m)
            if f is None:
                continue
            data = f.read()
            if m.name == "INFO":
                _safe_write(out_dir, "INFO", data)
                _log("  提取 INFO")
                for line in data.decode("utf-8", "replace").splitlines():
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        info[k.strip()] = v.strip().strip('"').strip()
            elif m.name == "package.tgz":
                _safe_write(out_dir, "package.tgz", data)
                _log("  提取 package.tgz -> target/")
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tgz:
                    _extract(tgz, target_dir, target_files)
                _log("    目标文件 %d 个" % len(target_files))
            else:
                if m.issym() or m.islnk():
                    continue
                if _safe_write(out_dir, m.name, data):
                    outer_files.append(m.name)
                    _log("  提取外层文件: %s" % m.name)

    _log("解包完成: 外层 %d 个文件, 目标 %d 个文件 -> %s" % (len(outer_files), len(target_files), out_dir))
    if symlinks:
        with open(os.path.join(out_dir, "_symlinks.json"), "w", encoding="utf-8") as fh:
            json.dump(symlinks, fh, ensure_ascii=False)
        _log("  符号链接 %d 个(已记录,二次打包时恢复)" % len(symlinks))
    return {"info": info, "outer": sorted(outer_files), "target": sorted(target_files), "symlinks": symlinks}


_X86 = {"x86_64", "x86", "i686", "bromolow", "cedarview", "broadwell", "avoton",
        "braswell", "apollolake", "geminilake", "geminilakenk", "denverton",
        "v1000", "v1000nk", "r1000", "r1000nk", "epyc7002", "epyc7003",
        "epyc7003ntb", "icelaked", "broadwellnk", "broadwellnkv2",
        "broadwellntbap", "grantley", "purley", "kvmx64", "dockerx64"}
_ARM64 = {"arm64", "armv8", "aarch64", "rtd1619b", "rtd1296", "rtd1293",
          "armada8040", "armada37xx", "rtd1619"}
_ARM = {"armv7", "armv7l", "armada370", "armada375", "armada38x", "armadaxp",
        "alpine", "alpine4k", "monaco", "hi3535", "comcerto2k"}


def map_arch(arch_str):
    """把 INFO 的 arch 字段(平台名/架构)粗略映射成 x86_64/arm64/armv7/noarch。"""
    tokens = [t.lower() for t in str(arch_str or "").split()]
    if not tokens or "noarch" in tokens or "all" in tokens:
        return ["noarch"]
    out = []
    for a in tokens:
        if a in _X86:
            out.append("x86_64")
        elif a in _ARM64:
            out.append("arm64")
        elif a in _ARM:
            out.append("armv7")
    return list(dict.fromkeys(out))
