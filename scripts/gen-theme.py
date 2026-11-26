#!/usr/bin/env python3
"""
把 breezy-skin 的亮/暗配色生成为两个 VS Code 主题。

色值来源：本仓库的 palette.json（同步自 dsh-skin 的 src/theme.css）
骨架来源：VS Code 自带 2026-light / 2026-dark 的完整 color ID 集合
         （含 include 链合并后 light 346 / dark 332 个 ID）

映射分三层，优先级从高到低：
  1. 结构色显式映射 —— 编辑器、侧栏、状态栏、标签页、列表选中、边框、文字阶
  2. 主色替换 —— 默认主题里以 #0069CC 为代表的蓝色系整体换成本主题的绿
  3. 中性色统一染色 —— 其余低色度色统一到品牌色相，保证整屏是一个色族

用法：python3 scripts/gen-theme.py
输出：themes/breezy-{light,dark}-color-theme.json
"""
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PALETTE = ROOT / "palette.json"
OUT_DIR = ROOT / "themes"

DEFAULTS = pathlib.Path(
    "/Applications/Visual Studio Code.app/Contents/Resources/app/extensions/theme-defaults/themes"
)


# ─────────────────────────────────────────────────────────────
# OKLCH 工具（与 scripts/derive-dark.py 保持一致）
# ─────────────────────────────────────────────────────────────
def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    v = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0, min(255, round(v * 255)))


def hex_to_oklch(hexs):
    h = hexs.lstrip("#")[:6]
    r, g, b = (_lin(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3)) for x in (l_, m_, s_))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def oklch_to_hex(L, C, H):
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l_, m_, s_ = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return "#%02x%02x%02x" % (_unlin(r), _unlin(g), _unlin(bb))


def split_alpha(v):
    """'#rrggbbaa' -> ('#rrggbb', 'aa')；其他形式 alpha 返回 ''"""
    v = v.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{8}", v):
        return v[:7].lower(), v[7:].lower()
    if v.lower().startswith("rgba"):
        m = re.findall(r"[\d.]+", v)
        a = round(float(m[3]) * 255)
        return oklch_to_hex(*hex_to_oklch("#%02x%02x%02x" % tuple(int(float(x)) for x in m[:3]))), "%02x" % a
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower(), ""
    return v, ""


def with_alpha(hex6, alpha_hex):
    return hex6 + alpha_hex if alpha_hex else hex6


def to_vscode_color(v):
    """VS Code 主题色值只接受 #RGB / #RGBA / #RRGGBB / #RRGGBBAA。

    rgba(...) 写法它解析不了，会回退成一个完全不相干的颜色 —— 实测
    widget.border 写 rgba(224,233,226,.08) 时，命令面板外框被渲染成了
    #d31411 的纯红。所以这里统一把 rgba 折成 8 位 hex。
    这个函数是最后一道闸，生成物里不应该再出现非 hex 的值。
    """
    v = str(v).strip()
    if v.startswith("#") or v.lower() in ("transparent", "default"):
        return v
    m = re.fullmatch(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", v)
    if not m:
        raise ValueError(f"无法转成 VS Code 色值: {v!r}")
    r, g, b = (int(round(float(m.group(i)))) for i in (1, 2, 3))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    out = "#%02x%02x%02x" % (r, g, b)
    if a < 1.0:
        out += "%02x" % int(round(a * 255))
    return out


# ─────────────────────────────────────────────────────────────
# 从 src/theme.css 取本主题调色板
# ─────────────────────────────────────────────────────────────
def load_palette():
    """从本仓库的 palette.json 读取调色板快照。

    真源是 dsh-skin 仓库的 src/theme.css；那边改了色以后重新导出 palette.json
    覆盖过来即可，本仓库不直接依赖 dsh-skin。
    """
    data = json.loads(PALETTE.read_text(encoding="utf-8"))
    required = {
        "page", "panel", "layer2", "layer3", "sidebar", "inset", "bubble",
        "text", "text2", "text3", "text4", "brand", "link",
        "hairline", "borderMid", "borderStrong", "error", "warn", "success",
    }
    for scheme in ("light", "dark"):
        missing = required - set(data.get(scheme, {}))
        if missing:
            raise KeyError(f"palette.json 的 {scheme} 缺少角色: {sorted(missing)}")
    return data["light"], data["dark"]


# ─────────────────────────────────────────────────────────────
# 默认主题骨架（解析 include 链）
# ─────────────────────────────────────────────────────────────
def load_default(kind):
    start = DEFAULTS / f"2026-{kind}.json"

    def walk(path, seen):
        if path in seen:
            return {}
        seen.add(path)
        d = json.load(open(path))
        out = {}
        inc = d.get("include")
        if inc:
            out.update(walk((pathlib.Path(path).parent / inc).resolve(), seen))
        out.update(d.get("colors") or {})
        return out

    colors = walk(start, set())
    tokens = []
    p = start
    chain = []
    while p and pathlib.Path(p).exists():
        d = json.load(open(p))
        chain.append(d)
        inc = d.get("include")
        p = (pathlib.Path(p).parent / inc).resolve() if inc else None
    # tokenColors 从基到覆盖依次叠加
    for d in reversed(chain):
        tc = d.get("tokenColors")
        if isinstance(tc, list):
            tokens.extend(tc)
    return colors, tokens


# ─────────────────────────────────────────────────────────────
# 结构色：显式映射（这些决定了主题的样子）
# ─────────────────────────────────────────────────────────────
def structural(p, dark):
    """p = 调色板；返回 {colorID: value}。未列出的走下方替换/染色。"""
    T = p
    focus = T["brand"]
    on_brand = T["panel"] if not dark else T["page"]
    sel = "#cee3d0" if not dark else "#26312a"     # 与 DSH 侧栏会话选中一致
    hover = T["layer2"] if not dark else "#232823"

    m = {
        # ── 顶/底/侧边框条 ───────────────────────────────
        "foreground": T["text"],
        "descriptionForeground": T["text2"],
        "disabledForeground": T["text4"],
        "errorForeground": T["error"],
        "icon.foreground": T["text2"],
        "focusBorder": focus,
        "widget.border": T["hairline"],
        "widget.shadow": "#2f493814" if not dark else "#00000066",
        "selection.background": T["brand"] + ("40" if not dark else "4d"),

        # ── 编辑器 ──────────────────────────────────────
        "editor.background": T["panel"],
        "editor.foreground": T["text"],
        "editor.lineHighlightBackground": T["layer2"],
        "editor.lineHighlightBorder": "#00000000",
        "editor.selectionBackground": T["brand"] + ("40" if not dark else "4d"),
        "editor.inactiveSelectionBackground": T["brand"] + ("1a" if not dark else "26"),
        "editor.selectionHighlightBackground": T["brand"] + ("20" if not dark else "33"),
        "editor.wordHighlightBackground": T["brand"] + ("26" if not dark else "33"),
        "editor.wordHighlightStrongBackground": T["brand"] + ("33" if not dark else "40"),
        "editor.findMatchBackground": T["brand"] + ("55" if not dark else "66"),
        "editor.findMatchHighlightBackground": T["brand"] + ("26" if not dark else "33"),
        "editor.findRangeHighlightBackground": T["layer2"],
        "editor.hoverHighlightBackground": T["layer2"],
        "editor.rangeHighlightBackground": T["layer2"],
        "editor.placeholder.foreground": T["text3"],
        "editorLineNumber.foreground": T["text3"],
        "editorLineNumber.activeForeground": T["text"],
        "editorCursor.foreground": T["brand"],
        "editorIndentGuide.background1": T["hairline"],
        "editorIndentGuide.background": T["hairline"],
        "editorIndentGuide.activeBackground1": T["borderMid"],
        "editorIndentGuide.activeBackground": T["borderMid"],
        "editorWhitespace.foreground": T["borderMid"],
        "editorRuler.foreground": T["hairline"],
        "editorCodeLens.foreground": T["text3"],
        "editorLink.activeForeground": T["link"],
        "editorBracketMatch.background": T["bubble"],
        "editorBracketMatch.border": T["borderMid"],
        "editorGutter.background": T["panel"],
        "editorGutter.addedBackground": T["success"],
        "editorGutter.modifiedBackground": T["warn"],
        "editorGutter.deletedBackground": T["error"],

        # ── 侧栏 / 活动栏 / 标题栏 / 状态栏 ────────────────
        "sideBar.background": T["sidebar"],
        "sideBar.foreground": T["text"],
        "sideBar.border": T["hairline"],
        "sideBarTitle.foreground": T["text"],
        "sideBarSectionHeader.background": T["sidebar"],
        "sideBarSectionHeader.foreground": T["text"],
        "sideBarSectionHeader.border": T["hairline"],

        "activityBar.background": T["sidebar"],
        "activityBar.foreground": T["text"],
        "activityBar.inactiveForeground": T["text3"],
        "activityBar.border": T["hairline"],
        "activityBar.activeBorder": focus,
        "activityBar.activeBackground": T["layer2"] if not dark else "#1f2420",
        "activityBar.activeFocusBorder": focus,
        "activityBarBadge.background": T["brand"],
        "activityBarBadge.foreground": on_brand,

        "titleBar.activeBackground": T["sidebar"],
        "titleBar.activeForeground": T["text2"],
        "titleBar.inactiveBackground": T["sidebar"],
        "titleBar.inactiveForeground": T["text3"],
        "titleBar.border": T["hairline"],

        "statusBar.background": T["sidebar"],
        "statusBar.foreground": T["text2"],
        "statusBar.border": T["hairline"],
        "statusBar.inactiveBackground": T["sidebar"],
        "statusBar.inactiveForeground": T["text3"],
        "statusBar.noFolderBackground": T["sidebar"],
        "statusBar.noFolderForeground": T["text2"],
        "statusBar.debuggingBackground": T["brand"],
        "statusBar.debuggingForeground": on_brand,
        "statusBar.focusBorder": focus,
        "statusBarItem.hoverBackground": hover,
        "statusBarItem.activeBackground": T["layer3"] if not dark else "#282d29",
        "statusBarItem.hoverForeground": T["text"],
        "statusBarItem.prominentBackground": T["brand"],
        "statusBarItem.prominentForeground": on_brand,
        "statusBarItem.prominentHoverBackground": T["brand"],
        # 彩色底上的前景一律用 on_brand：亮色是白、暗色是深底。
        # 我们的 error/warn 在暗色下是浅红/浅琥珀，白字只有 2.2~2.8，必须用深字。
        "statusBarItem.remoteBackground": T["brand"],
        "statusBarItem.remoteForeground": on_brand,
        "statusBarItem.remoteHoverBackground": T["brand"],
        "statusBarItem.offlineBackground": T["text3"],
        "statusBarItem.offlineForeground": on_brand,
        "agentsBadge.background": T["brand"],
        "agentsBadge.foreground": on_brand,
        "agentsUnreadBadge.background": T["brand"],
        "agentsUnreadBadge.foreground": on_brand,
        "extensionButton.prominentBackground": T["brand"],
        "extensionButton.prominentHoverBackground": T["brand"],
        "extensionButton.prominentForeground": on_brand,
        "statusBarItem.errorBackground": T["error"],
        "statusBarItem.errorForeground": on_brand,
        "statusBarItem.warningBackground": T["warn"],
        "statusBarItem.warningForeground": on_brand,
        "activityErrorBadge.foreground": on_brand,
        # 警告徽标的底是浅琥珀，两种模式都得用深字（on_brand 在亮色是白，会瞎）
        "activityWarningBadge.foreground": T["text"] if not dark else T["page"],

        # ── 标签页 ──────────────────────────────────────
        "editorGroupHeader.tabsBackground": T["sidebar"] if not dark else "#121613",
        "editorGroupHeader.tabsBorder": T["hairline"],
        "editorGroupHeader.noTabsBackground": T["sidebar"] if not dark else "#121613",
        "editorGroup.border": T["hairline"],
        "tab.activeBackground": T["panel"],
        "tab.activeForeground": T["text"],
        "tab.activeBorder": T["panel"],
        "tab.activeBorderTop": focus,
        "tab.inactiveBackground": T["sidebar"] if not dark else "#121613",
        "tab.inactiveForeground": T["text2"],
        "tab.border": T["hairline"],
        "tab.hoverBackground": T["layer2"],
        "tab.hoverForeground": T["text"],
        "tab.unfocusedActiveBackground": T["panel"],
        "tab.unfocusedActiveForeground": T["text2"],
        "tab.unfocusedInactiveForeground": T["text4"],
        "tab.unfocusedHoverBackground": T["layer2"],
        "tab.selectedBackground": T["layer2"],
        "tab.selectedForeground": T["text"],
        "tab.lastPinnedBorder": T["hairline"],

        # ── 面板（底部）──────────────────────────────────
        "panel.background": T["layer2"],
        "panel.border": T["hairline"],
        "panelTitle.activeBorder": focus,
        "panelTitle.activeForeground": T["text"],
        "panelTitle.inactiveForeground": T["text3"],
        "panelSectionHeader.background": T["layer2"],
        "panelSectionHeader.foreground": T["text2"],
        "panelSection.border": T["hairline"],

        # ── 浮层：菜单 / 下拉 / 输入 / 通知 / 快捷选择 ─────
        "menu.background": T["layer3"] if not dark else "#282d29",
        "menu.foreground": T["text"],
        "menu.border": T["hairline"],
        "menu.selectionBackground": T["bubble"],
        "menu.selectionForeground": T["text"],
        "menu.separatorBackground": T["hairline"],
        "menu.selectionBorder": focus,

        "dropdown.background": T["layer3"] if not dark else "#282d29",
        "dropdown.foreground": T["text"],
        "dropdown.border": T["borderMid"],
        "dropdown.listBackground": T["layer3"] if not dark else "#282d29",

        "input.background": T["panel"] if not dark else "#1f2420",
        "input.foreground": T["text"],
        "input.border": T["borderMid"],
        "input.placeholderForeground": T["text3"],
        "inputOption.activeBackground": T["bubble"],
        "inputOption.activeForeground": T["text"],
        "inputOption.activeBorder": focus,

        "notifications.background": T["layer3"] if not dark else "#282d29",
        "notifications.foreground": T["text"],
        "notifications.border": T["hairline"],
        "notificationCenterHeader.background": T["layer2"],
        "notificationCenterHeader.foreground": T["text"],
        "notificationLink.foreground": T["link"],

        "quickInput.background": T["layer3"] if not dark else "#282d29",
        "quickInput.foreground": T["text"],
        "quickInputTitle.background": T["layer2"],
        "quickInputList.focusBackground": T["bubble"],
        "quickInputList.focusForeground": T["text"],
        # 匹配到的那几个字符（Cmd+P 文件名里的加粗片段）和行首图标。
        # 默认主题这两个是白色，因为它的焦点底是深蓝；我们的焦点底是浅薄荷，白字全瞎。
        "quickInputList.focusHighlightForeground": T["brand"],
        "quickInputList.focusIconForeground": T["brand"],

        "editorWidget.background": T["layer3"] if not dark else "#282d29",
        "editorWidget.foreground": T["text"],
        "editorWidget.border": T["hairline"],
        "editorSuggestWidget.background": T["layer3"] if not dark else "#282d29",
        "editorSuggestWidget.border": T["hairline"],
        "editorSuggestWidget.foreground": T["text"],
        "editorSuggestWidget.selectedBackground": T["bubble"],
        "editorHoverWidget.background": T["layer3"] if not dark else "#282d29",
        "editorHoverWidget.foreground": T["text"],
        "editorHoverWidget.border": T["hairline"],

        # ── 列表 / 树 ───────────────────────────────────
        "list.activeSelectionBackground": sel,
        "list.activeSelectionForeground": T["text"],
        "list.inactiveSelectionBackground": sel,
        "list.inactiveSelectionForeground": T["text"],
        "list.focusBackground": sel,
        "list.focusForeground": T["text"],
        "list.hoverBackground": hover,
        "list.hoverForeground": T["text"],
        "list.highlightForeground": T["link"],
        "list.focusOutline": focus,
        "list.focusAndSelectionOutline": focus,
        "list.inactiveFocusOutline": T["borderMid"],
        "list.dropBackground": T["bubble"],
        "list.errorForeground": T["error"],
        "list.warningForeground": T["warn"],
        "list.invalidItemForeground": T["text4"],
        "listFilterWidget.background": T["layer2"],
        "listFilterWidget.outline": focus,
        "listFilterWidget.noMatchesOutline": T["error"],

        # ── 按钮 / 徽标 / 进度 ────────────────────────────
        "button.background": T["brand"],
        "button.foreground": on_brand,
        "button.hoverBackground": T["brand"] + ("d9" if not dark else "d9"),
        "button.border": T["brand"],
        "button.secondaryBackground": T["bubble"],
        "button.secondaryForeground": T["text"],
        "button.secondaryBorder": T["borderMid"],
        "button.secondaryHoverBackground": T["layer2"],
        "badge.background": T["brand"],
        "badge.foreground": on_brand,
        "progressBar.background": T["brand"],

        # ── 终端 ────────────────────────────────────────
        "terminal.background": T["panel"],
        "terminal.foreground": T["text"],
        "terminalCursor.foreground": T["brand"],
        "terminal.selectionBackground": T["brand"] + ("40" if not dark else "4d"),
        "terminal.inactiveSelectionBackground": T["layer2"],
        "terminal.tab.activeBorder": focus,
        "terminal.border": T["hairline"],

        # ── 面包屑 / 欢迎页 / 其它 ────────────────────────
        "breadcrumb.background": T["panel"],
        "breadcrumb.foreground": T["text3"],
        "breadcrumb.focusForeground": T["text"],
        "breadcrumb.activeSelectionForeground": T["text"],
        "breadcrumbPicker.background": T["layer3"] if not dark else "#282d29",

        "welcomePage.tileBackground": T["layer2"],
        "welcomePage.tileHoverBackground": T["bubble"],
        "welcomePage.progress.background": T["hairline"],
        "welcomePage.progress.foreground": T["brand"],

        "textLink.foreground": T["link"],
        "textLink.activeForeground": T["link"],
        "textBlockQuote.background": T["bubble"],
        "textBlockQuote.border": T["borderMid"],
        "textCodeBlock.background": T["inset"],
        "textPreformat.foreground": T["text"],
        "textSeparator.foreground": T["hairline"],

        "scrollbarSlider.background": T["text3"],
        "scrollbarSlider.hoverBackground": T["text2"],
        "scrollbarSlider.activeBackground": T["text2"],

        "gitDecoration.addedResourceForeground": T["success"],
        "gitDecoration.modifiedResourceForeground": T["warn"],
        "gitDecoration.deletedResourceForeground": T["error"],
        "gitDecoration.untrackedResourceForeground": T["success"],
        "gitDecoration.ignoredResourceForeground": T["text4"],
        "gitDecoration.conflictingResourceForeground": T["warn"],
        "gitDecoration.renamedResourceForeground": T["link"],
        "gitDecoration.submoduleResourceForeground": T["text3"],

        "editorOverviewRuler.border": "#00000000",
        "editorOverviewRuler.addedForeground": T["success"] + "cc",
        "editorOverviewRuler.modifiedForeground": T["warn"] + "cc",
        "editorOverviewRuler.deletedForeground": T["error"] + "cc",
        "editorOverviewRuler.findMatchForeground": T["brand"] + "cc",
        "editorOverviewRuler.selectionHighlightForeground": T["brand"] + "99",
        "editorOverviewRuler.wordHighlightForeground": T["brand"] + "99",

        # 文字 token 自带 alpha（8 位 hex），不能再拼两位，否则变 10 位非法值
        "minimapSlider.background": T["text4"],
        "minimapSlider.hoverBackground": T["text3"],
        "minimapSlider.activeBackground": T["text2"],
    }
    return m


# 默认主题里的主色 → 本主题对应色（按默认值精确替换）
def accent_substitutions(p, dark):
    on_brand = p["panel"] if not dark else p["page"]
    return {
        "#0069cc": p["brand"],          # VS Code 2026 默认强调蓝
        "#0063c1": p["brand"],          # 其上 hover
        "#005fb8": p["brand"],          # 更深一档
        "#0069cc40": p["brand"] + ("40" if not dark else "4d"),
        "#0069cc1a": p["brand"] + ("1a" if not dark else "26"),
        "#0069cc15": p["brand"] + ("15" if not dark else "1f"),
        "#0069cc26": p["brand"] + ("26" if not dark else "33"),
        "#0069ccdd": p["brand"] + "dd",
        "#ad0707": p["error"],
        "#c72e0f": p["error"],
        "#667309": p["warn"],
        "#68a3da": p["brand"],
        "#ffffff": on_brand if not dark else "#ffffff",
    }


# ─────────────────────────────────────────────────────────────
# 兜底：残留蓝色 → 品牌绿
#
# 默认主题的强调色是一族蓝（#0069CC / #005FB8 / #1B6AC3 / #3E7997 …），
# 值各不相同、还带各种 alpha，精确表匹配不完。这里按色相兜底：
# 色相落在 195°~275° 且有一定色度的，一律把色相换成品牌色相、保留明度。
# 三类豁免 —— 它们「本来就该是蓝」：
#   charts.*        数据可视化系列色（图表里要能区分蓝/绿）
#   confetti.*      装饰彩带
#   terminal.ansi*  终端 16 色（蓝就是蓝，改了语义就错）
# ─────────────────────────────────────────────────────────────
BLUE_EXEMPT = ("charts.", "confetti.", "terminal.ansi")


def remap_blue(key, value, p):
    if any(key.startswith(x) for x in BLUE_EXEMPT):
        return None
    hex6, alpha = split_alpha(value)
    if len(hex6) != 7:
        return None
    L, C, H = hex_to_oklch(hex6)
    if not (195 <= H <= 275 and C > 0.05):
        return None
    brand_L, brand_C, brand_H = hex_to_oklch(p["brand"].lstrip("#")[:6])
    # 保留原明度（保住它在界面里的层级），色度压到品牌色度附近避免过艳
    return with_alpha(oklch_to_hex(L, min(C * 0.72, brand_C), brand_H), alpha)


# ─────────────────────────────────────────────────────────────
# 兜底：中性色统一染色
# ─────────────────────────────────────────────────────────────
def tint_neutral(value, p, dark):
    hex6, alpha = split_alpha(value)
    if len(hex6) != 7:
        return value
    L, C, H = hex_to_oklch(hex6)
    brand_h = hex_to_oklch(p["brand"].lstrip("#")[:6])[2]
    if C < 0.04:
        # 近中性：统一到品牌色相，保留明度以保证对比结构不变
        new_c = 0.010 if dark else 0.008
        out = oklch_to_hex(L, new_c, brand_h)
    else:
        # 有语义的彩色：保色相，轻微降饱和使其不刺眼
        out = oklch_to_hex(L, C * (0.80 if dark else 0.90), H)
    return with_alpha(out, alpha)


# ─────────────────────────────────────────────────────────────
# 语法高亮 tokenColors
# ─────────────────────────────────────────────────────────────
def syntax(dark):
    """自然系语法配色：绿 / 青 / 琥珀三族，靠明度与字重区分角色。"""
    if dark:
        c = {
            "comment": "#7d9182",
            "string": "#9ec97a",
            "number": "#e0a556",
            "keyword": "#79cd94",
            "function": "#86d69f",
            "type": "#6ec5b8",
            "variable": "#c8d8cc",
            "constant": "#e0a556",
            "operator": "#9fb3a4",
            "tag": "#79cd94",
            "attr": "#e0a556",
            "invalid": "#f57272",
            "text": "#e0e9e2",
        }
    else:
        c = {
            "comment": "#5f7362",
            "string": "#4f7a2e",
            "number": "#8a5a2b",
            "keyword": "#21472b",
            "function": "#2e6943",
            "type": "#1f6f6a",
            "variable": "#3d5a46",
            "constant": "#8a5a2b",
            "operator": "#4a5f4f",
            "tag": "#21472b",
            "attr": "#8a5a2b",
            "invalid": "#b83c3c",
            "text": "#2f4938",
        }
    return [
        {"scope": ["comment", "punctuation.definition.comment", "string.comment"],
         "settings": {"foreground": c["comment"], "fontStyle": "italic"}},
        {"scope": ["string", "string.quoted", "string.template", "punctuation.definition.string"],
         "settings": {"foreground": c["string"]}},
        {"scope": ["constant.numeric", "constant.language", "constant.character", "constant.other"],
         "settings": {"foreground": c["number"]}},
        {"scope": ["keyword", "keyword.control", "storage", "storage.type", "storage.modifier"],
         "settings": {"foreground": c["keyword"], "fontStyle": "bold"}},
        {"scope": ["entity.name.function", "support.function", "meta.function-call"],
         "settings": {"foreground": c["function"]}},
        {"scope": ["entity.name.type", "entity.name.class", "support.type", "support.class",
                   "entity.other.inherited-class"],
         "settings": {"foreground": c["type"]}},
        {"scope": ["variable", "variable.other", "variable.parameter", "meta.definition.variable"],
         "settings": {"foreground": c["variable"]}},
        {"scope": ["variable.other.constant", "variable.other.enummember", "constant.other.symbol"],
         "settings": {"foreground": c["constant"]}},
        {"scope": ["keyword.operator", "punctuation", "meta.brace"],
         "settings": {"foreground": c["operator"]}},
        {"scope": ["entity.name.tag", "meta.tag", "punctuation.definition.tag"],
         "settings": {"foreground": c["tag"]}},
        {"scope": ["entity.other.attribute-name"],
         "settings": {"foreground": c["attr"]}},
        {"scope": ["markup.heading", "markup.bold", "entity.name.section"],
         "settings": {"foreground": c["keyword"], "fontStyle": "bold"}},
        {"scope": ["markup.italic"], "settings": {"fontStyle": "italic"}},
        {"scope": ["markup.underline.link", "string.other.link"], "settings": {"foreground": c["function"]}},
        {"scope": ["markup.inserted", "meta.diff.header.to-file"], "settings": {"foreground": c["string"]}},
        {"scope": ["markup.deleted", "meta.diff.header.from-file"], "settings": {"foreground": c["invalid"]}},
        {"scope": ["invalid", "invalid.illegal"], "settings": {"foreground": c["invalid"]}},
    ]


# ─────────────────────────────────────────────────────────────
# 终端 ANSI

def ansi(p, dark):
    if dark:
        return {
            "terminal.ansiBlack": "#121613", "terminal.ansiRed": "#f57272",
            "terminal.ansiGreen": "#9ec97a", "terminal.ansiYellow": "#e0a556",
            "terminal.ansiBlue": "#6ec5b8", "terminal.ansiMagenta": "#c9a0dc",
            "terminal.ansiCyan": "#7fd4c6", "terminal.ansiWhite": "#e0e9e2",
            "terminal.ansiBrightBlack": "#3f4a42", "terminal.ansiBrightRed": "#ff9a9a",
            "terminal.ansiBrightGreen": "#b6dd97", "terminal.ansiBrightYellow": "#f0c078",
            "terminal.ansiBrightBlue": "#8fd8cd", "terminal.ansiBrightMagenta": "#dcb8e8",
            "terminal.ansiBrightCyan": "#9fe3d8", "terminal.ansiBrightWhite": "#f2f8f3",
        }
    return {
        "terminal.ansiBlack": "#2f4938", "terminal.ansiRed": "#b83c3c",
        "terminal.ansiGreen": "#4f7a2e", "terminal.ansiYellow": "#8a5a2b",
        "terminal.ansiBlue": "#1f6f6a", "terminal.ansiMagenta": "#7a4f8a",
        "terminal.ansiCyan": "#2b7d74", "terminal.ansiWhite": "#e3ece4",
        "terminal.ansiBrightBlack": "#7d8f80", "terminal.ansiBrightRed": "#d05050",
        "terminal.ansiBrightGreen": "#5f9040", "terminal.ansiBrightYellow": "#a8712f",
        "terminal.ansiBrightBlue": "#2a8a83", "terminal.ansiBrightMagenta": "#9460a8",
        "terminal.ansiBrightCyan": "#369a90", "terminal.ansiBrightWhite": "#fcfefc",
    }


# ─────────────────────────────────────────────────────────────
# 生成
# ─────────────────────────────────────────────────────────────
def build(kind, p):
    dark = kind == "dark"
    defaults, _ = load_default(kind)

    out = {}
    explicit = structural(p, dark)
    subs = accent_substitutions(p, dark)

    for key, dv in defaults.items():
        if key in explicit:
            out[key] = explicit[key]
            continue
        low = dv.lower()
        if low in subs:
            out[key] = subs[low]
            continue
        blued = remap_blue(key, dv, p)
        if blued:
            out[key] = blued
            continue
        out[key] = tint_neutral(dv, p, dark)

    # 显式映射里可能有默认主题不存在的键，一并补上
    for k, v in explicit.items():
        out[k] = v
    out.update(ansi(p, dark))

    theme = {
        "$schema": "vscode://schemas/color-theme",
        "name": "Workbuddy Breezy Light" if not dark else "Workbuddy Breezy Dark",
        "type": "light" if not dark else "dark",
        "semanticHighlighting": True,
        # 所有色值统一过 to_vscode_color：rgba() 必须折成 #RRGGBBAA
        "colors": dict(sorted((k, to_vscode_color(v)) for k, v in out.items())),
        "tokenColors": syntax(dark),
    }
    return theme


def main():
    light_p, dark_p = load_palette()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for kind, p in (("light", light_p), ("dark", dark_p)):
        theme = build(kind, p)
        path = OUT_DIR / f"breezy-{kind}-color-theme.json"
        path.write_text(json.dumps(theme, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}  colors={len(theme['colors'])}  tokenColors={len(theme['tokenColors'])}")


if __name__ == "__main__":
    main()
