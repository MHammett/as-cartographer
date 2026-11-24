"""Offline test: build and DOT render on a made-up 3-router, 2-ASN network (documentation addresses only).
No probing, no network access, no Graphviz.   Run: python tests/test_offline.py   (or pytest)
"""
import json, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixture"


def run(script, net, *extra):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), str(net), *extra], capture_output=True, text=True)
    assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def test_build_and_render():
    with tempfile.TemporaryDirectory() as d:
        net = pathlib.Path(d) / "net"
        shutil.copytree(FIX, net)
        run("build_topology.py", net)
        first = (net / "topology.json").read_bytes()
        run("build_topology.py", net)
        assert (net / "topology.json").read_bytes() == first, "build is not deterministic"

        t = json.loads(first)
        routers = {r["id"]: r for r in t["routers"]}
        assert sorted(routers) == ["CHI-129", "DAL-131", "STL-130"], sorted(routers)
        assert routers["STL-130"]["evidence"].endswith("(no St. Louis probe answers)"), "metro_to_pop rule not applied"
        assert routers["CHI-129"]["pop"] == "CHI" and routers["DAL-131"]["pop"] == "DAL"
        assert routers["DAL-131"]["asn"] == 64501 and routers["CHI-129"]["asn"] == 64500, "family ASN tagging"
        links = {(l["a"], l["b"]): l for l in t["links"]}
        assert set(links) == {("CHI-129", "STL-130"), ("STL-130", "DAL-131")}, set(links)
        assert links[("STL-130", "DAL-131")]["inter_as"] == [64500, 64501], "inter-AS link not marked"
        assert "inter_as" not in links[("CHI-129", "STL-130")]
        assert links[("CHI-129", "STL-130")]["rtt_est_ms"] == 8.4  # Chicago probe: 0.5 + 7.9
        ext = {(e["kind"], e["router"]) for e in t["externals"]}
        assert ("transit", "DAL-131") in ext and ("ix", "CHI-129") in ext, ext
        transit = next(e for e in t["externals"] if e["kind"] == "transit")
        assert transit["far_ip"] == "203.0.113.0" and transit["far_ptr"] == "dal-r1-link.transit.example"

        run("render.py", net, "--dot-only")
        dot = (net / "out" / "map.dot").read_text()
        assert "AS64500 - AS64501" in dot and 'color="#D85A30"' in dot, "inter-AS link not drawn"
        assert "Example IX Chicago" in (net / "out" / "map_full.dot").read_text()


if __name__ == "__main__":
    test_build_and_render()
    print("ok")
