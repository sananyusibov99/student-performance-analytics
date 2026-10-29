"""Derive three styled report themes from the sqlbi base theme.

Usage: py -I make-themes.py <base sqlbi.json> <output dir>
"""
import copy
import json
import re
import sys
from pathlib import Path

STYLES = {
    "StudentClean": {
        "description": "Clean light: soft grey canvas, white cards, indigo accent",
        "page": "#F3F5FA", "card": "#FFFFFF", "text": "#1E293B", "title": "#334155",
        "muted": "#64748B", "subtle": "#EEF2F7", "line": "#E2E8F0", "shadow": "#CBD5E1",
        "accent": "#4F46E5", "font": "Segoe UI", "headFont": "Segoe UI Semibold",
        "data": ["#4F46E5", "#14B8A6", "#F59E0B", "#EC4899", "#0EA5E9", "#8B5CF6", "#22C55E", "#EF4444"],
        "good": "#14B8A6", "bad": "#EF4444", "shadowShow": True,
    },
    "StudentMidnight": {
        "description": "Dark navy: deep background, glowing cyan and violet accents",
        "page": "#0B1220", "card": "#131C2E", "text": "#E2E8F0", "title": "#CBD5E1",
        "muted": "#94A3B8", "subtle": "#1B2740", "line": "#24324D", "shadow": "#020617",
        "accent": "#38BDF8", "font": "Segoe UI", "headFont": "Segoe UI Semibold",
        "data": ["#38BDF8", "#A78BFA", "#34D399", "#FBBF24", "#F472B6", "#60A5FA", "#F87171", "#2DD4BF"],
        "good": "#34D399", "bad": "#F87171", "shadowShow": False,
    },
    "StudentAcademic": {
        "description": "Academic warm: cream paper, deep teal and gold, serif headings",
        "page": "#F6F1E7", "card": "#FFFDF8", "text": "#2B2A27", "title": "#1F4E5A",
        "muted": "#7A7266", "subtle": "#EFE7D8", "line": "#E4DACA", "shadow": "#D9CDB8",
        "accent": "#1F6F78", "font": "Segoe UI", "headFont": "Georgia",
        "data": ["#1F6F78", "#E09F3E", "#9E2A2B", "#540B0E", "#335C67", "#C9A227", "#6A994E", "#7F5539"],
        "good": "#1F6F78", "bad": "#9E2A2B", "shadowShow": False,
    },
}

# sqlbi base colours -> semantic role in the new style
ROLE_OF = {
    "#1971c2": "accent",
    "#404040": "text", "#333333": "text",
    "#707070": "title",
    "#aaaaaa": "muted", "#909090": "muted", "#868e96": "muted", "#999999": "muted",
    "#ffffff": "card",
    "#f0f0f0": "subtle", "#f5f5f5": "subtle", "#f1f1f1": "subtle", "#f2f2f2": "subtle",
    "#f3f3f3": "subtle", "#f4f4f4": "subtle", "#e9ecef": "subtle", "#eeeeee": "subtle",
    "#cccccc": "line", "#e0e0e0": "line", "#dfdfdf": "line", "#b3b0ad": "line",
    "#dddddd": "shadow",
}
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def recolor(text, s):
    return HEX.sub(lambda m: s[ROLE_OF[m.group(0).lower()]] if m.group(0).lower() in ROLE_OF else m.group(0), text)


def solid(c):
    return {"solid": {"color": c}}


def override(vs, obj, props):
    """Apply props to obj in the wildcard style and in every visual type that already sets obj."""
    for vtype, selectors in vs.items():
        entry = selectors.get("*", {})
        if vtype == "*" or obj in entry:
            target = selectors.setdefault("*", {}).setdefault(obj, [{}])
            target[0].update(copy.deepcopy(props))


def build(base, name, s):
    t = json.loads(recolor(json.dumps(base), s))
    t["name"] = name
    t["dataColors"] = s["data"] + base["dataColors"][len(s["data"]):]
    t.update({"good": s["good"], "bad": s["bad"], "maximum": s["good"], "minimum": s["bad"],
              "background": s["card"], "backgroundLight": s["card"], "foreground": s["text"],
              "accent": s["accent"], "tableAccent": s["accent"]})
    for tc in t["textClasses"].values():
        tc["color"] = s["text"]
        tc["fontFace"] = s["font"]
    for key in ("title", "callout", "header", "largeTitle"):
        t["textClasses"][key]["fontFace"] = s["headFont"]
    t["textClasses"]["title"]["color"] = s["title"]
    t["textClasses"]["dataTitle"]["color"] = s["muted"]

    vs = t["visualStyles"]
    override(vs, "title", {"fontFamily": s["headFont"], "fontColor": solid(s["title"]), "fontSize": 12})
    override(vs, "background", {"show": True, "color": solid(s["card"]), "transparency": 0})
    override(vs, "border", {"show": True, "color": solid(s["line"]), "radius": 14, "width": 1})
    override(vs, "dropShadow", {"show": s["shadowShow"], "color": solid(s["shadow"]),
                                "shadowBlur": 12, "shadowDistance": 3, "transparency": 70})
    override(vs, "divider", {"show": False})
    # solid bars instead of the outlined sqlbi look
    override(vs, "dataPoint", {"fillTransparency": 0, "Transparency": 0, "borderShow": False,
                               "borderOutlineOnly": False})
    override(vs, "labels", {"color": solid(s["text"]), "fontFamily": s["headFont"]})
    override(vs, "categoryAxis", {"labelColor": solid(s["muted"])})
    override(vs, "valueAxis", {"labelColor": solid(s["muted"]), "gridlineColor": solid(s["line"])})
    vs["card"]["*"]["labels"][0].update({"color": solid(s["accent"]), "fontFamily": s["headFont"]})
    vs["card"]["*"]["categoryLabels"][0].update({"color": solid(s["muted"])})
    # text boxes (page titles) sit on the page canvas, not on a card
    vs["textbox"]["*"]["background"] = [{"show": False}]
    vs["textbox"]["*"]["border"] = [{"show": False}]
    vs["textbox"]["*"]["dropShadow"] = [{"show": False}]
    vs["textbox"]["*"]["text"] = [{"fontFamily": s["headFont"], "color": solid(s["title"])}]
    # set last: the generic "background" override above also matches the page style
    vs["page"]["*"]["background"] = [{"color": solid(s["page"]), "transparency": 0}]
    vs["page"]["*"]["outspace"] = [{"color": solid(s["page"]), "transparency": 0}]
    return t


def main():
    base = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"templates": {}}
    for name, style in STYLES.items():
        theme = build(base, name, style)
        (out / f"{name}.json").write_text(json.dumps(theme, indent=2), encoding="utf-8")
        manifest["templates"][name] = {"description": style["description"], "author": "StudentExamPBI",
                                       "updated": "2026-10-23T00:00:00", "colors": len(theme["dataColors"]),
                                       "recommended": "none"}
        print("wrote", name)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
