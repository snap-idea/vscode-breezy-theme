#!/usr/bin/env python3
"""
审核 vscode-theme 下两个主题的可读性与完整性。

检查项：
  1. 所有色值格式合法（#rrggbb / #rrggbbaa / rgba() / transparent）
  2. 覆盖 VS Code 默认 2026-{light,dark} 的全部 color ID（不缺键）
  3. 关键 文字/背景 配对达到 WCAG AA（正文 4.5、非文字 UI 3.0）
  4. 每个语法高亮 token 在编辑器底色上达到 4.5
  5. package.json 的 contributes.themes 指向的文件都存在

用法：python3 scripts/audit-theme.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
THEMES = ROOT
DEFAULTS = pathlib.Path(
    "/Applications/Visual Studio Code.app/Contents/Resources/app/extensions/theme-defaults/themes"
)

# VS Code 主题色值只接受 #RGB / #RGBA / #RRGGBB / #RRGGBBAA。
# 注意：rgba() 虽然看着像 CSS，但 VS Code 解析不了，会回退成离谱的颜色
# （实测 widget.border 写 rgba 后命令面板外框变成纯红 #d31411）。
VALID = re.compile(r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8})$")


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(v):
    v = v.strip()
    if v.startswith("#"):
        h = v.lstrip("#")
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)), a
    m = re.findall(r"[\d.]+", v)
    return tuple(int(float(x)) for x in m[:3]), (float(m[3]) if len(m) > 3 else 1.0)


def _lum(v):
    (r, g, b), _ = _rgb(v)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _over(fg, bg):
    (fr, fg_, fb), a = _rgb(fg)
    br, bgc, bb = _rgb(bg)[0]
    return "#%02x%02x%02x" % (round(fr * a + br * (1 - a)),
                              round(fg_ * a + bgc * (1 - a)),
                              round(fb * a + bb * (1 - a)))


def contrast(fg, bg):
    l1, l2 = _lum(_over(fg, bg)), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = [
    ("编辑器正文", "editor.foreground", "editor.background", 4.5),
    ("侧栏文字", "sideBar.foreground", "sideBar.background", 4.5),
    ("状态栏文字", "statusBar.foreground", "statusBar.background", 4.5),
    ("标题栏文字", "titleBar.activeForeground", "titleBar.activeBackground", 4.5),
    ("活动栏图标", "activityBar.foreground", "activityBar.background", 3.0),
    ("活动栏非激活图标", "activityBar.inactiveForeground", "activityBar.background", 3.0),
    ("非激活标签", "tab.inactiveForeground", "tab.inactiveBackground", 4.5),
    ("激活标签", "tab.activeForeground", "tab.activeBackground", 4.5),
    ("列表选中", "list.activeSelectionForeground", "list.activeSelectionBackground", 4.5),
    ("列表悬停", "list.hoverForeground", "list.hoverBackground", 4.5),
    ("输入框", "input.foreground", "input.background", 4.5),
    ("输入占位", "input.placeholderForeground", "input.background", 3.0),
    ("菜单", "menu.foreground", "menu.background", 4.5),
    ("菜单选中", "menu.selectionForeground", "menu.selectionBackground", 4.5),
    ("按钮", "button.foreground", "button.background", 4.5),
    ("徽标", "badge.foreground", "badge.background", 4.5),
    ("面板标题", "panelTitle.activeForeground", "panel.background", 4.5),
    ("描述文字 / 编辑器", "descriptionForeground", "editor.background", 4.5),
    ("描述文字 / 侧栏", "descriptionForeground", "sideBar.background", 4.5),
    ("行号", "editorLineNumber.foreground", "editor.background", 3.0),
    ("行号激活", "editorLineNumber.activeForeground", "editor.background", 4.5),
    ("链接", "textLink.foreground", "editor.background", 4.5),
    ("错误色", "errorForeground", "editor.background", 4.5),
    ("终端正文", "terminal.foreground", "terminal.background", 4.5),
    ("下拉", "dropdown.foreground", "dropdown.background", 4.5),
    ("建议列表", "editorSuggestWidget.foreground", "editorSuggestWidget.background", 4.5),
    ("通知", "notifications.foreground", "notifications.background", 4.5),
    ("面包屑", "breadcrumb.foreground", "breadcrumb.background", 3.0),
    # Cmd+P 快速打开：匹配片段与行首图标画在 focusBackground 上
    ("快速打开 匹配高亮", "quickInputList.focusHighlightForeground", "quickInputList.focusBackground", 4.5),
    ("快速打开 图标", "quickInputList.focusIconForeground", "quickInputList.focusBackground", 3.0),
    ("快速打开 行文字", "quickInputList.focusForeground", "quickInputList.focusBackground", 4.5),
    # 彩色底上的前景：底是品牌绿/错误红/警告琥珀，前景必须跟着模式反转
    ("状态栏 错误项", "statusBarItem.errorForeground", "statusBarItem.errorBackground", 4.5),
    ("状态栏 警告项", "statusBarItem.warningForeground", "statusBarItem.warningBackground", 4.5),
    ("状态栏 远程项", "statusBarItem.remoteForeground", "statusBarItem.remoteBackground", 4.5),
    ("状态栏 调试项", "statusBar.debuggingForeground", "statusBar.debuggingBackground", 4.5),
    ("活动栏 错误徽标", "activityErrorBadge.foreground", "activityErrorBadge.background", 4.5),
    ("活动栏 警告徽标", "activityWarningBadge.foreground", "activityWarningBadge.background", 4.5),
    ("活动栏 徽标", "activityBarBadge.foreground", "activityBarBadge.background", 4.5),
    ("智能体徽标", "agentsBadge.foreground", "agentsBadge.background", 4.5),
    ("扩展安装按钮", "extensionButton.prominentForeground", "extensionButton.prominentBackground", 4.5),
]


def merge_default(kind):
    start = DEFAULTS / f"2026-{kind}.json"
    seen, out = set(), {}

    def walk(path):
        if path in seen:
            return
        seen.add(path)
        d = json.load(open(path))
        inc = d.get("include")
        if inc:
            walk((pathlib.Path(path).parent / inc).resolve())
        out.update(d.get("colors") or {})

    walk(start)
    return out


def main():
    problems = []

    manifest_p = THEMES / "package.json"
    if not manifest_p.exists():
        print("!! 缺少 package.json")
        return 1
    manifest = json.load(open(manifest_p))
    declared = manifest.get("contributes", {}).get("themes", [])
    print(f"manifest: {len(declared)} 个主题")
    for t in declared:
        f = THEMES / t["path"]
        ok = f.exists()
        print(f"  {'OK  ' if ok else 'FAIL'} {t['label']:14} uiTheme={t['uiTheme']:8} {t['path']}")
        if not ok:
            problems.append(f"manifest 指向的文件不存在: {t['path']}")

    for kind in ("light", "dark"):
        path = THEMES / "themes" / f"breezy-{kind}-color-theme.json"
        if not path.exists():
            problems.append(f"缺少 {path.name}")
            continue
        d = json.load(open(path))
        colors = d["colors"]
        print(f"\n── {kind} ({d.get('type')}) ── colors={len(colors)} tokenColors={len(d.get('tokenColors', []))}")

        bad = [(k, v) for k, v in colors.items() if not VALID.match(str(v))]
        if bad:
            for k, v in bad[:5]:
                print(f"  FAIL 非法色值 {k} = {v!r}")
                problems.append(f"{kind}: {k} 色值非法 {v!r}")
        else:
            print("  色值格式：全部合法 ✓")

        missing = sorted(set(merge_default(kind)) - set(colors))
        if missing:
            print(f"  覆盖：缺 {len(missing)} 个默认 color ID")
            problems.append(f"{kind}: 缺 {len(missing)} 个 color ID，如 {missing[:3]}")
        else:
            print("  覆盖：默认 color ID 全覆盖 ✓")

        print(f"  {'配对':20} {'对比度':>7} {'门槛':>5}  判定")
        for label, fk, bk, floor in PAIRS:
            if fk not in colors or bk not in colors:
                problems.append(f"{kind}: 缺 {fk} 或 {bk}")
                continue
            r = contrast(colors[fk], colors[bk])
            ok = r >= floor
            print(f"  {label:20} {r:7.2f} {floor:5.1f}  {'OK' if ok else 'FAIL'}")
            if not ok:
                problems.append(f"{kind}: {label} = {r:.2f} < {floor}")

        bg = colors["editor.background"]
        print("  ── 语法 token ──")
        for t in d.get("tokenColors", []):
            fg = (t.get("settings") or {}).get("foreground")
            if not fg:
                continue
            scope = t["scope"][0] if isinstance(t["scope"], list) else t["scope"]
            r = contrast(fg, bg)
            ok = r >= 4.5
            print(f"    {scope:34} {r:6.2f}  {'OK' if ok else 'FAIL'}")
            if not ok:
                problems.append(f"{kind}: 语法 token {scope} = {r:.2f} < 4.5")

    print()
    if problems:
        print("!! 未通过:")
        for p in problems:
            print("  -", p)
        return 1
    print("全部通过：色值合法、默认 color ID 全覆盖、AA 对比度达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
