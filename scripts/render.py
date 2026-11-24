"""Render <net>/topology.json to Graphviz DOT, then SVG, PDF and PNG.   usage: python render.py <net-dir>

Two maps, in <net>/out/:
  map.*        backbone: routers grouped region > PoP, with router-router links
  map_full.*   the same plus transit handoffs, IX ports, other devices and every downstream customer AS
Region/PoP names come from config.json "pops" ({code: [region, display name]}) and "region_order".

Deterministic: the DOT text is generated in sorted order, and Graphviz dot lays out
identical input identically. Edit topology.json (or rerun build_topology.py), then rerun this.
Visio: render_visio.py draws .vsdx from the .dot files written here.

Graphviz: uses `dot` on PATH if present, otherwise `wsl -e dot` (Graphviz in WSL).
"""
import collections, json, pathlib, shutil, subprocess, sys

HERE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OUT = HERE / "out"
CFG = json.loads((HERE / "config.json").read_text())
FORMATS = ["svg", "pdf", "png"]

# PoP code -> (region, display name); a code "XX-<place>" falls under XX's region with <place> as its name.
POPS = {k: tuple(v) for k, v in CFG.get("pops", {}).items()}
REGION_ORDER = CFG.get("region_order", [])
REGION_FILL = collections.defaultdict(lambda: "#E1F5EE", {"Unknown": "#FFFFFF", **CFG.get("region_fill", {})})
CORE_FILL = "#EEEDFE"  # routers holding transit or IX ports


def pop_of(r):
    return r["pop"].rstrip("?")


def region_name(pop):
    if "-" in pop and pop.split("-", 1)[0] in POPS:
        base, place = pop.split("-", 1)
        return POPS[base][0], place.replace("_", " ")
    return POPS.get(pop, ("Unknown", pop))


def q(s):
    # backslashes are left alone on purpose: labels use Graphviz's \n line-break escape
    return '"' + str(s).replace('"', "'") + '"'


def plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


ASN_COLOURS = ["#185FA5", "#993C1D", "#3B6D11", "#534AB7", "#993556"]


def node_label(r):
    lines = [r["id"] + (f"  AS{r['asn']}" if r.get("asn") else ""), f"lo {r['loopback']}"] + r["ports"]
    lines.append(plural(len(r["interfaces"]), "interface") + " seen")
    if r["downstream_devices"]:
        lines.append(plural(r["downstream_devices"], "downstream device"))
    if r["pop"].endswith("?"):
        lines.append("location inferred from neighbours")
    return "\\n".join(lines)


def cust_label(c):
    lines = [f"AS{c['asn']}", c["name"][:32]]
    for e in c.get("edge", [])[:2]:
        ptr = c.get("edge_ptr", {}).get(e)
        lines.append(f"edge {e}" + (f" ({ptr})" if ptr else ""))
    if c.get("other_upstreams"):
        lines.append("also via AS" + ", AS".join(str(a) for a in c["other_upstreams"][:4]))
    return "\\n".join(lines)


def to_dot(t, customers=False):
    title = f'{t["name"]} AS{t["asn"]} - router-level map from external measurement'
    if customers:
        title += " - with transit, IX ports and downstream customers"
    out = [
        "graph network {",
        f"  label={q(title)}; labelloc=t; fontname=\"Helvetica\"; fontsize=18;",
        "  rankdir=LR; nodesep=0.3; ranksep=1.0; splines=true; newrank=true; compound=true;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=8, color="#378ADD"];',
    ]
    tree = {}
    for r in t["routers"]:
        reg, _ = region_name(pop_of(r))
        tree.setdefault(reg, {}).setdefault(pop_of(r), []).append(r)
    for reg in REGION_ORDER + sorted(set(tree) - set(REGION_ORDER)):
        if reg not in tree:
            continue
        rid = reg.replace(" ", "_")
        out.append(f"  subgraph cluster_region_{rid} {{")
        out.append(f'    label={q(reg)}; style="rounded"; color="#5F5E5A"; penwidth=1.5; fontsize=14;')
        for pop in sorted(tree[reg]):
            out.append(f"    subgraph cluster_pop_{pop.replace('-', '_')} {{")
            out.append(f'      label={q(region_name(pop)[1])}; style="rounded,dashed"; color="#888780"; fontsize=11;')
            for r in sorted(tree[reg][pop], key=lambda r: r["id"]):
                style = '"rounded,filled,dashed"' if r["pop"].endswith("?") else '"rounded,filled"'
                fill = CORE_FILL if r["ports"] else REGION_FILL[reg]
                pen = 2 if r["ports"] else 1
                fam = t.get("asns", [])
                if len(fam) > 1 and r.get("asn") in fam:  # border colour identifies the family ASN
                    style = style[:-1] + ',bold"' if r["ports"] else style
                    out.append(f'      {q(r["id"])} [color="{ASN_COLOURS[fam.index(r["asn"]) % len(ASN_COLOURS)]}"];')
                out.append(f'      {q(r["id"])} [label={q(node_label(r))}, fillcolor="{fill}", style={style}, penwidth={pen}];')
            out.append("    }")
        out.append("  }")
    for l in t["links"]:
        lines = list(l["addresses"])
        if "rtt_est_ms" in l:
            lines.append(f"~{l['rtt_est_ms']} ms")
        colour = ""
        if l.get("inter_as"):  # link between two ASNs of the same company
            lines.append("AS{} - AS{}".format(*l["inter_as"]))
            colour = ', color="#D85A30"'
        out.append(f'  {q(l["a"])} -- {q(l["b"])} [label={q("\\n".join(lines))}, penwidth=1.6{colour}];')
    for l in t["inferred_links"]:
        out.append(f'  {q(l["a"])} -- {q(l["b"])} [style=dashed, color="#888780", label={q("inferred via " + l["via"])}];')
    for l in t.get("extra_links", []):  # e.g. a standby link confirmed live but not carrying traffic
        out.append(f'  {q(l["a"])} -- {q(l["b"])} [style=dashed, color="#534AB7", penwidth=1.6, '
                   f'label={q(l["a_ip"] + " - " + l["b_ip"] + "\\n" + l["kind"] + " (live, not preferred)")}];')
    if customers:
        for d in t.get("other_devices", []):
            n = d["name"]
            out.append(f'  {q(n)} [shape=box, style="rounded,dashed", label={q(n + "\\n" + ", ".join(d["ips"]) + "\\nno core loopback")}];')
            if d.get("behind_router"):
                out.append(f'  {q(d["behind_router"])} -- {q(n)} [color="#888780"];')
        # outside networks: transit handoffs and IX ports, with the far-end interfaces
        out.append('  node [shape=box, style="filled", fontsize=9];')
        seen = set()
        for e in t.get("externals", []):
            if e["kind"] == "transit":
                n = f"{e['org'].split()[0]} {e['far_router']}"
                if n not in seen:
                    seen.add(n)
                    lab = f"{e['org']}\\n{e['far_router']}\\n{e['far_ip']}\\n{e.get('far_ptr') or ''}"
                    out.append(f'  {q(n)} [label={q(lab)}, fillcolor="#E6F1FB"];')
                lab = e["near_ip"] + (f"\\n{e['near_ptr']}" if e.get("near_ptr") else "")
                out.append(f'  {q(e["router"])} -- {q(n)} [color="#185FA5", penwidth=1.6, label={q(lab)}];')
            elif e["kind"] == "ix":
                n = e["org"]
                speed = f"{e['speed_mbps'] // 1000}G port (PeeringDB)" if e.get("speed_mbps") else "speed not listed"
                he = f"\\nHE peer {e['he_ip']}" if e.get("he_ip") else ""
                lab = f"{e['org']}\\n{speed}{he}"
                style = "filled" if e["router"] else "filled,dashed"
                out.append(f'  {q(n)} [label={q(lab)}, fillcolor="#EAF3DE", style={q(style)}];')
                if e["router"]:
                    dashed = ", style=dashed" if "only router seen" in e["evidence"] else ""
                    out.append(f'  {q(e["router"])} -- {q(n)} [color="#3B6D11", label={q(e["near_ip"])}{dashed}];')
        out.append('  node [shape=ellipse, style=filled, fillcolor="#FAEEDA", fontsize=9];')
        for c in sorted(t.get("customers", []), key=lambda c: c["asn"]):
            n = f"AS{c['asn']}"
            style = "filled,dashed" if not c["attach"] else "filled"
            out.append(f"  {q(n)} [label={q(cust_label(c))}, style={q(style)}];")
            for a in c["attach"]:
                out.append(f'  {q(a["router"])} -- {q(n)} [color="#BA7517", label={q(a["evidence"])}];')
    out.append("}")
    return "\n".join(out) + "\n"


def dot_cmd():
    if shutil.which("dot"):
        return ["dot"], lambda p: str(p)
    if shutil.which("wsl"):
        def wslpath(p):
            p = pathlib.Path(p).resolve()
            return "/mnt/" + p.drive[0].lower() + p.as_posix()[2:]
        return ["wsl", "-e", "dot"], wslpath
    sys.exit("Graphviz not found: install it, or Graphviz in WSL (apt install graphviz)")


def main():
    t = json.loads((HERE / "topology.json").read_text())
    OUT.mkdir(exist_ok=True)
    dot_only = "--dot-only" in sys.argv  # write the .dot files and stop (tests; machines without Graphviz)
    cmd, path = (None, None) if dot_only else dot_cmd()
    for name, cust in (("map", False), ("map_full", True)):
        if cust and not t.get("customers") and not t.get("externals"):
            continue
        dot_file = OUT / f"{name}.dot"
        dot_file.write_text(to_dot(t, cust), newline="\n")
        if dot_only:
            print(f"wrote {dot_file.relative_to(HERE)}")
            continue
        for fmt in FORMATS:
            target = OUT / f"{name}.{fmt}"
            extra = ["-Gdpi=150"] if fmt == "png" else []
            subprocess.run(cmd + extra + [f"-T{fmt}", path(dot_file), "-o", path(target)], check=True)
            print(f"wrote {target.relative_to(HERE)} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
