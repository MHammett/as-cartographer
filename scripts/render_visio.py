"""Draw <net>/out/map.vsdx and map_full.vsdx in Microsoft Visio (usage: python render_visio.py <net-dir>) at the coordinates Graphviz computed.

Why not Graphviz's own -Tvdx: Visio rejects that file with "Unexpected end of file"
even though the XML is well-formed; the writer is old and unmaintained. Here, Graphviz
does the layout (deterministic) and Visio draws native shapes with glued connectors.

Needs: Visio installed, pywin32, and out/map*.dot from render.py.
The drawing is the same each run; the .vsdx bytes differ only by Visio's save metadata.
"""
import json, pathlib, shutil, subprocess, sys

import win32com.client

HERE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
MAPS = ["map", "map_full"]  # out/<name>.dot -> out/<name>.vsdx
MARGIN = 0.5  # inches


def layout(DOT):
    if shutil.which("dot"):
        cmd = ["dot", "-Tjson0", str(DOT)]
    else:
        p = DOT.resolve()
        cmd = ["wsl", "-e", "dot", "-Tjson0", "/mnt/" + p.drive[0].lower() + p.as_posix()[2:]]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return f"RGB({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)})"


def pt(v):  # Graphviz points -> inches, offset by the margin
    return float(v) / 72 + MARGIN


def text(label):
    return label.replace("\\n", "\n")


def draw(name):
    DOT = HERE / "out" / f"{name}.dot"
    VSDX = HERE / "out" / f"{name}.vsdx"
    g = layout(DOT)
    bb = [float(v) for v in g["bb"].split(",")]
    app = win32com.client.Dispatch("Visio.InvisibleApp")
    app.AlertResponse = 7
    try:
        doc = app.Documents.Add("")
        page = doc.Pages.Item(1)
        page.PageSheet.CellsU("PageWidth").FormulaU = f"{bb[2] / 72 + 2 * MARGIN} in"
        page.PageSheet.CellsU("PageHeight").FormulaU = f"{bb[3] / 72 + 2 * MARGIN} in"

        title = page.DrawRectangle(MARGIN, pt(bb[3]) - 0.2, pt(bb[2]), pt(bb[3]) + 0.3)
        title.Text = g.get("label", "")
        title.CellsU("LinePattern").FormulaU = "0"
        title.CellsU("FillPattern").FormulaU = "0"
        title.CellsU("Char.Size").FormulaU = "16 pt"

        shapes = {}
        for o in g["objects"]:
            if o["name"].startswith("cluster_"):
                x1, y1, x2, y2 = (float(v) for v in o["bb"].split(","))
                s = page.DrawRectangle(pt(x1), pt(y1), pt(x2), pt(y2))
                s.Text = o.get("label", "")
                s.CellsU("LinePattern").FormulaU = "2"
                s.CellsU("LineColor").FormulaU = rgb("#888780")
                s.CellsU("FillPattern").FormulaU = "0"
                s.CellsU("VerticalAlign").FormulaU = "0"
                s.CellsU("Rounding").FormulaU = "0.15 in"
                s.CellsU("Char.Size").FormulaU = "11 pt"
                s.SendToBack()
        for o in g["objects"]:
            if "pos" not in o:
                continue
            x, y = (float(v) for v in o["pos"].split(","))
            w, h = float(o["width"]), float(o["height"])
            s = page.DrawRectangle(pt(x) - w / 2, pt(y) - h / 2, pt(x) + w / 2, pt(y) + h / 2)
            s.Text = text(o.get("label", o["name"]))
            s.Name = o["name"]
            s.CellsU("FillForegnd").FormulaU = rgb(o.get("fillcolor", "#FFFFFF"))
            s.CellsU("Rounding").FormulaU = "0.08 in"
            s.CellsU("Char.Size").FormulaU = "8 pt"
            s.CellsU("LineWeight").FormulaU = f"{float(o.get('penwidth', 1))} pt"
            if "dashed" in o.get("style", ""):
                s.CellsU("LinePattern").FormulaU = "2"
            shapes[o["_gvid"]] = s
        for e in g.get("edges", []):
            c = page.Drop(app.ConnectorToolDataObject, 0, 0)
            c.CellsU("BeginX").GlueTo(shapes[e["tail"]].CellsU("PinX"))
            c.CellsU("EndX").GlueTo(shapes[e["head"]].CellsU("PinX"))
            c.Text = text(e.get("label", ""))
            c.CellsU("Char.Size").FormulaU = "6 pt"
            c.CellsU("LineColor").FormulaU = rgb(e.get("color", "#378ADD"))
            c.CellsU("LineWeight").FormulaU = f"{float(e.get('penwidth', 1))} pt"
            c.CellsU("EndArrow").FormulaU = "0"
            if "dashed" in e.get("style", ""):
                c.CellsU("LinePattern").FormulaU = "2"
        if VSDX.exists():
            VSDX.unlink()
        doc.SaveAs(str(VSDX.resolve()))
        doc.Close()
        print(f"wrote {VSDX.relative_to(HERE)}: {len(shapes)} nodes, {len(g.get("edges", []))} lines")
    finally:
        app.Quit()


if __name__ == "__main__":
    for name in MAPS:
        if (HERE / "out" / f"{name}.dot").exists():
            draw(name)
