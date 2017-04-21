#!/usr/bin/env python3

import datetime
import ipaddress
import json
import os
import sys
import tempfile
import traceback

import jinja2
import requests
import dns
import dns.zone


def main():
    vars = {key.lower(): value for (key, value) in os.environ.items()}

    try:
        resp = requests.get(os.environ["NETBOX_ENDPOINT"])
        resp.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(err, file=sys.stderr)
        sys.exit(1)

    forward_records = []
    reverse_records = {}

    origin_records = []
    for name, ip in json.loads(os.environ["DNS_SERVERS"]).items():
        origin_records.append(("NS", name.strip() + "." + os.environ["DNS_ZONE"] + "."))
        forward_records.append((name.strip(), "A", ip))

    data = resp.json()
    for name, data in sorted(data.items(), key=lambda x: (ip_str_key(x[1]["primary"]), x[0])):
        ip_str = data["primary"]
        primary_ip = ipaddress.ip_address(ip_str)
        forward_records.append((name, "A", primary_ip.compressed))
        for cname in sorted(data.get("cnames", [])):
            forward_records.append((cname, "CNAME", name))
        for ip in sorted([primary_ip] + [ipaddress.ip_address(i) for i in data.get("secondary_ips", [])], key=ip_key):
            block = ".".join(reversed(ip.compressed.split(".")[:3]))
            if block not in reverse_records:
                reverse_records[block] = []
            reverse_records[block].append((_ipv4_reverse_pointer(ip) + ".", "PTR", name + "." + os.environ["DNS_ZONE"] + "."))

    update_zonefile(os.path.join(os.environ["DNS_DIRECTORY"], os.environ["DNS_ZONE"], "zone.db"), origin_records, os.environ["DNS_ZONE"], forward_records)

    for block, block_reverse_records in reverse_records.items():
        block += ".in-addr.arpa"
        update_zonefile(os.path.join(os.environ["DNS_DIRECTORY"], block, "zone.db"), origin_records, block, block_reverse_records)


def update_zonefile(path, origin_records, zone_name, records):

    try:
        zone = dns.zone.from_text(open(path))
        origin_node = zone.get("@")
        soa_rdataset = origin_node.get_rdataset(dns.rdataclass.IN, dns.rdatatype.SOA)
        previous_serial = soa_rdataset.items[0].serial
    except:
        traceback.print_exc()
        previous_serial = 0

    new_serial = todays_serial = int(datetime.datetime.today().strftime("%Y%m%d00"))
    if os.path.exists(path):
        new_serial = max(previous_serial + 1, todays_serial)
    new_serial_str = str(new_serial)
    assert len(new_serial_str) == len("2000123100")

    vars = {
        "dns_zone": zone_name,
        "dns_contact": os.environ["DNS_CONTACT"],

        "dns_serial": new_serial_str,
        "dns_refresh_time": os.environ["DNS_REFRESH_TIME"],
        "dns_retry_time": os.environ["DNS_RETRY_TIME"],
        "dns_expire_time": os.environ["DNS_EXPIRE_TIME"],
        "dns_negative_cache_time": os.environ["DNS_NEGATIVE_CACHE_TIME"],

        "dns_servers": [s.strip() for s in os.environ["DNS_SERVERS"].split(",")],
        "dns_source": "netbox",

        "origin_records": origin_records,
        "records": records,
    }

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("."), undefined=jinja2.StrictUndefined)
    text = env.get_template("zonefile.j2").render(vars)

    with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), delete=False) as temp_file:
        temp_file.write(env.get_template("zonefile.j2").render(vars).encode("utf-8"))
    os.replace(temp_file.name, path)


# Copied from Python 3.5 standard library for Python 3.4 compatibility
def _ipv4_reverse_pointer(self):
    reverse_octets = str(self).split('.')[::-1]
    return '.'.join(reverse_octets) + '.in-addr.arpa'

# ipaddress.__cmp__ is broken, it sorts ".30" between ".3" and ".4" :-(
def ip_key(ip):
    return tuple(int(part) for part in ip.compressed.split('.'))
def ip_str_key(ip_str):
    return ip_key(ipaddress.ip_address(ip_str))


if __name__ == "__main__":
    main()
