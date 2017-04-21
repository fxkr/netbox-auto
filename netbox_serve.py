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

    records = {}

    with get_db().cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""\
            SELECT DISTINCT
                ipam_ipaddress.address as i_address,
                dcim_device.name as d_name
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

        result = {row["d_name"].lower(): row["i_address"].ip.compressed for row in cur}
        return jsonify(result)


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
