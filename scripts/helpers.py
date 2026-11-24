#!/usr/bin/env python3
"""Small helpers for field_run.sh. Standard library only; reads scamper's sc_warts2json output.

  helpers.py hops   <traces.json> <prefixes.txt> <outdir>  -> hops.txt, infra24.txt (target-space hop addrs and their /24s)
  helpers.py expand <infra24.txt>                          -> every address in those /24s, on stdout
  helpers.py cands  <outdir> [max]                         -> cands.txt: hops + live addresses in infra /24s
  helpers.py pairs  <traces.json...> <prefixes.txt> <out>  -> consecutive hop pairs ending in target space
  helpers.py summary <outdir>                              -> counts, for the end-of-run printout
  helpers.py loopbacks <config.json>                       -> every address in the configured loopback blocks
  helpers.py lbloc <config.json> <out.json> <traces.json...> -> [loopback, last hop before it, n]
"""
import ipaddress, json, pathlib, sys


def nets(prefix_file):
    return [ipaddress.ip_network(l.strip()) for l in open(prefix_file) if l.strip()]


def inside(ip, ns):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in ns)


def traces(path):
    for line in open(path):
        d = json.loads(line)
        if d.get("type") != "trace":
            continue
        hops = {}
        for h in d.get("hops", []):
            hops.setdefault(h["probe_ttl"], h["addr"])
        yield d["dst"], [hops.get(t) for t in range(1, max(hops, default=0) + 1)]


def key(ip):
    return tuple(int(x) for x in ip.split("."))


def cmd_hops(tr, pf, outdir):
    ns, out = nets(pf), pathlib.Path(outdir)
    hops = set()
    for dst, hl in traces(tr):
        for ip in hl[:-1] if hl and hl[-1] == dst else hl:
            if ip and inside(ip, ns):
                hops.add(ip)
    s24 = sorted({".".join(h.split(".")[:3]) + ".0/24" for h in hops}, key=lambda s: key(s.split("/")[0]))
    (out / "hops.txt").write_text("".join(h + "\n" for h in sorted(hops, key=key)))
    (out / "infra24.txt").write_text("".join(s + "\n" for s in s24))
    print(f"{len(hops)} router addresses in target space, in {len(s24)} /24s")


def cmd_expand(f):
    for l in open(f):
        if l.strip():
            for h in ipaddress.ip_network(l.strip()).hosts():
                print(h)


def cmd_cands(outdir, mx=600):
    out = pathlib.Path(outdir)
    hops = [l.strip() for l in open(out / "hops.txt") if l.strip()]
    alive = [l.strip() for l in open(out / "alive.txt") if l.strip()] if (out / "alive.txt").exists() else []
    c = sorted(set(hops) | set(alive), key=key)
    if len(c) > int(mx):  # keep every hop address; trim live hosts to fit radargun's budget
        rest = [a for a in alive if a not in set(hops)]
        c = sorted(set(hops) | set(rest[: max(0, int(mx) - len(hops))]), key=key)
    (out / "cands.txt").write_text("".join(x + "\n" for x in c))
    print(f"{len(c)} alias candidates")


def cmd_pairs(*args):
    """One prefixscan test per far address b, using the hop seen most often before it.
    Testing every (a, b) combination ran 40+ minutes on a 46-/24 network."""
    import collections
    *trs, pf, outf = args
    ns, seen = nets(pf), collections.defaultdict(collections.Counter)
    # A trace's destination is tested only if radargun already tied it to another address (rg_aliases.txt
    # in the run directory), i.e. it is a router interface, not an end host. On a 46-/24 network this kept
    # every router-router link that testing all destinations found, with 343 tests instead of 548.
    # Dropping destinations entirely lost half of them: sweep traces reach router interfaces as destinations.
    rg = set()
    if pathlib.Path("rg_aliases.txt").exists():
        for line in open("rg_aliases.txt"):
            rg.update(line.split()[:2])
    for tr in trs:
        for dst, hl in traces(tr):
            for a, b in zip(hl, hl[1:]):
                if a and b and a != b and inside(b, ns) and (b != dst or b in rg):
                    seen[b][a] += 1
    pairs = sorted((c.most_common(1)[0][0], b) for b, c in seen.items())
    pathlib.Path(outf).write_text("".join(f"{a} {b}\n" for a, b in pairs))
    print(f"{len(pairs)} hop pairs for prefixscan")


def cmd_loopbacks(cfg):
    """Every address in config.json's loopback blocks, so each router's ID gets swept and traced."""
    for n in json.load(open(cfg)).get("loopbacks", []):
        for h in ipaddress.ip_network(n).hosts():
            print(h)


def cmd_lbloc(cfg, outf, *trs):
    """For each loopback a trace reached, the last hop before it: that router's upstream neighbour."""
    import collections
    ns = [ipaddress.ip_network(n) for n in json.load(open(cfg)).get("loopbacks", [])]
    last = collections.defaultdict(collections.Counter)
    for tr in trs:
        for dst, hl in traces(tr):
            if inside(dst, ns) and hl and hl[-1] == dst:
                prev = next((x for x in reversed(hl[:-1]) if x), None)
                if prev:
                    last[dst][prev] += 1
    rows = sorted(([d, c.most_common(1)[0][0], sum(c.values())] for d, c in last.items()), key=lambda r: key(r[0]))
    pathlib.Path(outf).write_text(json.dumps(rows, indent=1) + "\n")
    print(f"{len(rows)} loopbacks located behind a neighbour")


def cmd_summary(outdir):
    out = pathlib.Path(outdir)
    for f in ("hops.txt", "infra24.txt", "alive.txt", "cands.txt", "pairs.txt", "rg_aliases.txt", "ps_out.txt"):
        p = out / f
        n = sum(1 for l in open(p) if l.strip()) if p.exists() else 0
        print(f"  {f:16s} {n}")


if __name__ == "__main__":
    c, *a = sys.argv[1:]
    {"hops": cmd_hops, "expand": cmd_expand, "cands": cmd_cands, "pairs": cmd_pairs, "summary": cmd_summary,
     "loopbacks": cmd_loopbacks, "lbloc": cmd_lbloc}[c](*a)
