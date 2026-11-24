"""Reverse DNS for every router interface, link partner and customer edge (DNS over HTTPS, free).

usage: python rdns.py <net-dir>      -> <net>/raw/rdns.json  {ip: [ptr, ...] | []}
Transit providers usually name their side of the handoff (e.g. Arelion "<router>-link.ip.twelve99.net",
"<customer>-ic-<id>.ip.twelve99-cust.net"), which tells you the provider's router and an interconnect ID.
"""
import concurrent.futures as cf, ipaddress, json, pathlib, sys, urllib.request

NET = pathlib.Path(sys.argv[1]).resolve()
t = json.loads((NET / "topology.json").read_text())
ips = set()
for r in t["routers"]:
    for i in r["interfaces"]:
        n = int(ipaddress.ip_address(i))
        ips |= {i, str(ipaddress.ip_address(n ^ 1))}
        if n % 4 in (1, 2):
            ips.add(str(ipaddress.ip_address(n + 1 if n % 4 == 1 else n - 1)))
for c in t.get("customers", []):
    ips |= set(c.get("edge", []))


def ptr(ip):
    q = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    for _ in range(3):
        try:
            req = urllib.request.Request(f"https://cloudflare-dns.com/dns-query?name={q}&type=PTR", headers={"accept": "application/dns-json"})
            d = json.load(urllib.request.urlopen(req, timeout=20))
            return ip, [a["data"] for a in d.get("Answer", []) if a.get("type") == 12]
        except Exception:
            pass
    return ip, None


with cf.ThreadPoolExecutor(16) as ex:
    res = dict(ex.map(ptr, sorted(ips, key=lambda s: ipaddress.ip_address(s))))
(NET / "raw" / "rdns.json").write_text(json.dumps(res, indent=1) + "\n", newline="\n")
print(f"{len(res)} addresses, {sum(1 for v in res.values() if v)} with PTR")
