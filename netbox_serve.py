#!/usr/bin/env python3

import json
import os
import urllib.parse

import jinja2

import psycopg2
import psycopg2.extras

from flask import Flask, g, jsonify
from flask_basicauth import BasicAuth


psycopg2.extras.register_ipaddress()


app = Flask(__name__)
app.config.from_mapping(**os.environ)
basic_auth = BasicAuth(app)


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        url = urllib.parse.urlparse(os.environ["DATABASE_URL"])
        db = g._database = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port)
    return db


@app.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route("/devices")
@basic_auth.required
def get_zone():

    results = {}

    with get_db().cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:

        # Primary addresses

        cur.execute("""\
            SELECT DISTINCT
                ipam_ipaddress.address as i_address,
                dcim_device.name as d_name,
                dcim_device.comments as d_comments
            FROM
                ipam_ipaddress
            JOIN dcim_device ON ipam_ipaddress.id = dcim_device.primary_ip4_id
            JOIN tenancy_tenant ON ipam_ipaddress.tenant_id = tenancy_tenant.id
            WHERE
                bool(ipam_ipaddress.status) AND
                bool(dcim_device.status) AND
                ipam_ipaddress.family = 4 AND
                tenancy_tenant.slug = %s
            ORDER BY
                ipam_ipaddress.address ASC,
                dcim_device.name ASC
        """, (app.config["NETBOX_TENANT_SLUG"],))

        for row in cur:
            result = {"primary": row["i_address"].ip.compressed}
            if row["d_comments"]:
                for line in row["d_comments"].split("\n"):
                    line = line.strip()
                    if not line.startswith("`{") or not line.endswith("}`"):
                        continue
                    line = line[1:-1]
                    try:
                        obj = json.loads(line)
                    except:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if "cnames" in obj and isinstance(obj["cnames"], list) and all(isinstance(x, str) for x in obj["cnames"]):
                        result["cnames"] = obj["cnames"]
            results[row["d_name"].lower()] = result

        # Secondary addresses

        cur.execute("""\
            SELECT DISTINCT
                ipam_ipaddress.address as i_address,
                dcim_device.name as d_name,
                dcim_device.comments as d_comments
            FROM
                ipam_ipaddress
            JOIN dcim_interface ON ipam_ipaddress.interface_id = dcim_interface.id
            JOIN dcim_device ON dcim_interface.device_id = dcim_device.id
            JOIN tenancy_tenant ON ipam_ipaddress.tenant_id = tenancy_tenant.id
            WHERE
                bool(ipam_ipaddress.status) AND
                bool(dcim_device.status) AND
                ipam_ipaddress.family = 4 AND
                tenancy_tenant.slug = %s AND
                ipam_ipaddress.id != dcim_device.primary_ip4_id
            ORDER BY
                ipam_ipaddress.address ASC,
                dcim_device.name ASC
        """, (app.config["NETBOX_TENANT_SLUG"],))

        for row in cur:
            if row["d_name"] in results:
                secondary_ips = results[row["d_name"]].setdefault("secondary_ips", [])
                if row["i_address"] not in secondary_ips:
                    secondary_ips.append(row["i_address"].ip.compressed)


    return jsonify(results)


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
