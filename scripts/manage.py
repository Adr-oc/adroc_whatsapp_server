#!/usr/bin/env python3
"""CLI manager for the WhatsApp-Odoo multi-tenant middleware.

Usage:
    python scripts/manage.py tenants list
    python scripts/manage.py tenants create acme "Acme Corp" https://acme.odoo.com/whatsapp/webhook secret123
    python scripts/manage.py tenants get acme
    python scripts/manage.py tenants update acme --display-name "Acme Inc" --max-instances 20
    python scripts/manage.py tenants deactivate acme
    python scripts/manage.py tenants rotate-key acme

    python scripts/manage.py instances list --tenant-key <key>
    python scripts/manage.py instances create ventas --tenant-key <key>
    python scripts/manage.py instances status ventas --tenant-key <key>
    python scripts/manage.py instances delete ventas --tenant-key <key>
    python scripts/manage.py instances restart ventas --tenant-key <key>
    python scripts/manage.py instances logout ventas --tenant-key <key>

    python scripts/manage.py health

Environment variables:
    MIDDLEWARE_URL   Base URL (default: http://localhost:8000)
    ADMIN_API_KEY    Admin key for tenant management
    TENANT_API_KEY   Tenant key for instance/message operations
"""

import argparse
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx")
    sys.exit(1)

BASE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8000")
CLIENT_TIMEOUT = 30.0


def _client():
    return httpx.Client(timeout=CLIENT_TIMEOUT)


def _admin_headers(args):
    key = getattr(args, "admin_key", None) or os.environ.get("ADMIN_API_KEY")
    if not key:
        print("Error: admin key required. Pass --admin-key or set $ADMIN_API_KEY.")
        sys.exit(1)
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _tenant_headers(args):
    key = getattr(args, "tenant_key", None) or os.environ.get("TENANT_API_KEY")
    if not key:
        print("Error: tenant key required. Pass --tenant-key or set $TENANT_API_KEY.")
        sys.exit(1)
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _url(path: str) -> str:
    return f"{BASE_URL.rstrip('/')}{path}"


def _print_json(data):
    print(json.dumps(data, indent=2, default=str))


def _handle_response(resp):
    if resp.status_code >= 400:
        print(f"Error: HTTP {resp.status_code}")
        try:
            _print_json(resp.json())
        except Exception:
            print(resp.text)
        sys.exit(1)
    return resp.json()


# -- Health -------------------------------------------------------------------

def cmd_health(_args):
    with _client() as c:
        resp = c.get(_url("/api/health"))
        data = _handle_response(resp)

    db = data.get("database", {})
    tenants = data.get("tenants", {})
    evo = data.get("evolution_api", {})
    workers = data.get("workers", {})

    print(f"Status:       {data.get('status', '?')}")
    print(f"Database:     {db.get('status', '?')} ({db.get('pending_events', 0)} pending events)")
    print(f"Tenants:      {tenants.get('active', 0)} active / {tenants.get('total', 0)} total")
    print(f"Evolution:    {evo.get('status', '?')}")
    print(f"Workers:      {workers.get('active', 0)} active, queue={workers.get('queue_size', 0)}")


# -- Tenants ------------------------------------------------------------------

def cmd_tenants_list(args):
    with _client() as c:
        resp = c.get(_url("/api/admin/tenants"), headers=_admin_headers(args))
        data = _handle_response(resp)

    if not data:
        print("No tenants found.")
        return

    print(f"{'SLUG':<20} {'DISPLAY NAME':<25} {'ACTIVE':<8} {'MAX':<5} {'ODOO URL'}")
    print("-" * 100)
    for t in data:
        active = "yes" if t["is_active"] else "no"
        print(f"{t['slug']:<20} {t['display_name']:<25} {active:<8} {t['max_instances']:<5} {t['odoo_webhook_url']}")


def cmd_tenants_create(args):
    payload = {
        "slug": args.slug,
        "display_name": args.display_name,
        "odoo_webhook_url": args.odoo_url,
        "odoo_api_key": args.odoo_key,
        "max_instances": args.max_instances,
    }
    with _client() as c:
        resp = c.post(_url("/api/admin/tenants"), json=payload, headers=_admin_headers(args))
        data = _handle_response(resp)

    tenant = data["tenant"]
    api_key = data["api_key"]
    print(f"Tenant '{tenant['slug']}' created successfully.")
    print(f"  Display name: {tenant['display_name']}")
    print(f"  Max instances: {tenant['max_instances']}")
    print(f"  Odoo URL: {tenant['odoo_webhook_url']}")
    print()
    print(f"  API KEY: {api_key}")
    print()
    print("  ** Save this key — it won't be shown again **")


def cmd_tenants_get(args):
    with _client() as c:
        resp = c.get(_url(f"/api/admin/tenants/{args.slug}"), headers=_admin_headers(args))
        data = _handle_response(resp)

    print(f"Slug:           {data['slug']}")
    print(f"Display name:   {data['display_name']}")
    print(f"Active:         {data['is_active']}")
    print(f"Max instances:  {data['max_instances']}")
    print(f"Odoo URL:       {data['odoo_webhook_url']}")
    print(f"Created:        {data['created_at']}")


def cmd_tenants_update(args):
    payload = {}
    if args.display_name is not None:
        payload["display_name"] = args.display_name
    if args.odoo_url is not None:
        payload["odoo_webhook_url"] = args.odoo_url
    if args.odoo_key is not None:
        payload["odoo_api_key"] = args.odoo_key
    if args.max_instances is not None:
        payload["max_instances"] = args.max_instances
    if args.activate:
        payload["is_active"] = True
    if args.deactivate:
        payload["is_active"] = False

    if not payload:
        print("Nothing to update. Use --display-name, --odoo-url, --odoo-key, --max-instances, --activate, or --deactivate.")
        sys.exit(1)

    with _client() as c:
        resp = c.patch(_url(f"/api/admin/tenants/{args.slug}"), json=payload, headers=_admin_headers(args))
        data = _handle_response(resp)

    print(f"Tenant '{data['slug']}' updated.")
    print(f"  Display name:  {data['display_name']}")
    print(f"  Active:        {data['is_active']}")
    print(f"  Max instances: {data['max_instances']}")
    print(f"  Odoo URL:      {data['odoo_webhook_url']}")


def cmd_tenants_deactivate(args):
    with _client() as c:
        resp = c.delete(_url(f"/api/admin/tenants/{args.slug}"), headers=_admin_headers(args))
        data = _handle_response(resp)

    print(f"Tenant '{data['slug']}' deactivated.")


def cmd_tenants_rotate_key(args):
    with _client() as c:
        resp = c.post(_url(f"/api/admin/tenants/{args.slug}/rotate-key"), headers=_admin_headers(args))
        data = _handle_response(resp)

    print(f"API key rotated for tenant '{data['tenant']['slug']}'.")
    print()
    print(f"  NEW API KEY: {data['api_key']}")
    print()
    print("  ** Save this key — it won't be shown again **")
    print("  ** The old key is now invalid **")


# -- Instances ----------------------------------------------------------------

def cmd_instances_list(args):
    with _client() as c:
        resp = c.get(_url("/api/instances"), headers=_tenant_headers(args))
        data = _handle_response(resp)

    if not data:
        print("No instances found.")
        return

    print(f"{'NAME':<25} {'STATE':<15} {'PHONE'}")
    print("-" * 60)
    for inst in data:
        phone = inst.get("phone_number") or "-"
        print(f"{inst['instance_name']:<25} {inst['state']:<15} {phone}")


def cmd_instances_create(args):
    payload = {"instance_name": args.name}
    with _client() as c:
        resp = c.post(_url("/api/instances"), json=payload, headers=_tenant_headers(args))
        data = _handle_response(resp)

    print(f"Instance '{data['instance_name']}' created (state: {data['state']}).")
    if data.get("qrcode_base64"):
        print("  QR code available. Use 'instances qr <name>' to retrieve it.")


def cmd_instances_status(args):
    with _client() as c:
        resp = c.get(_url(f"/api/instances/{args.name}/status"), headers=_tenant_headers(args))
        data = _handle_response(resp)

    print(f"Instance: {data['instance_name']}")
    print(f"State:    {data['state']}")


def cmd_instances_qr(args):
    with _client() as c:
        resp = c.get(_url(f"/api/instances/{args.name}/qr"), headers=_tenant_headers(args))
        data = _handle_response(resp)

    b64 = data.get("base64")
    code = data.get("code")
    if code:
        print(f"Pairing code: {code}")
    if b64:
        if args.save:
            import base64
            # Strip data URI prefix if present
            raw = b64.split(",", 1)[-1] if "," in b64 else b64
            with open(args.save, "wb") as f:
                f.write(base64.b64decode(raw))
            print(f"QR code saved to {args.save}")
        else:
            print(f"QR base64 ({len(b64)} chars) — use --save qr.png to save as image")


def cmd_instances_delete(args):
    with _client() as c:
        resp = c.delete(_url(f"/api/instances/{args.name}"), headers=_tenant_headers(args))
        _handle_response(resp)

    print(f"Instance '{args.name}' deleted.")


def cmd_instances_restart(args):
    with _client() as c:
        resp = c.put(_url(f"/api/instances/{args.name}/restart"), headers=_tenant_headers(args))
        _handle_response(resp)

    print(f"Instance '{args.name}' restarted.")


def cmd_instances_logout(args):
    with _client() as c:
        resp = c.delete(_url(f"/api/instances/{args.name}/logout"), headers=_tenant_headers(args))
        _handle_response(resp)

    print(f"Instance '{args.name}' logged out.")


# -- Send message -------------------------------------------------------------

def cmd_send(args):
    payload = {"number": args.number, "text": args.text}
    if args.media_url:
        payload["media_url"] = args.media_url
    if args.media_type:
        payload["media_type"] = args.media_type

    with _client() as c:
        resp = c.post(
            _url(f"/api/instances/{args.instance}/send"),
            json=payload,
            headers=_tenant_headers(args),
        )
        data = _handle_response(resp)

    print(f"Message sent via '{args.instance}' to {args.number}")
    msg_id = data.get("key", {}).get("id")
    if msg_id:
        print(f"  Message ID: {msg_id}")


# -- Parser ------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="manage",
        description="WhatsApp-Odoo middleware manager",
    )
    parser.add_argument("--url", default=BASE_URL, help=f"Middleware URL (default: {BASE_URL})")
    sub = parser.add_subparsers(dest="command", required=True)

    # health
    p_health = sub.add_parser("health", help="Check middleware health")
    p_health.set_defaults(func=cmd_health)

    # tenants
    p_tenants = sub.add_parser("tenants", help="Manage tenants (admin)")
    p_tenants.add_argument("--admin-key", help="Admin API key (or $ADMIN_API_KEY)")
    tsub = p_tenants.add_subparsers(dest="tenant_action", required=True)

    # tenants list
    p_tl = tsub.add_parser("list", help="List all tenants")
    p_tl.set_defaults(func=cmd_tenants_list)

    # tenants create
    p_tc = tsub.add_parser("create", help="Create a tenant")
    p_tc.add_argument("slug", help="URL-safe slug (e.g. acme)")
    p_tc.add_argument("display_name", help="Display name (e.g. 'Acme Corp')")
    p_tc.add_argument("odoo_url", help="Odoo webhook URL")
    p_tc.add_argument("odoo_key", help="Odoo API key")
    p_tc.add_argument("--max-instances", type=int, default=10, help="Max instances (default: 10)")
    p_tc.set_defaults(func=cmd_tenants_create)

    # tenants get
    p_tg = tsub.add_parser("get", help="Get tenant details")
    p_tg.add_argument("slug")
    p_tg.set_defaults(func=cmd_tenants_get)

    # tenants update
    p_tu = tsub.add_parser("update", help="Update tenant config")
    p_tu.add_argument("slug")
    p_tu.add_argument("--display-name")
    p_tu.add_argument("--odoo-url")
    p_tu.add_argument("--odoo-key")
    p_tu.add_argument("--max-instances", type=int)
    p_tu.add_argument("--activate", action="store_true", help="Reactivate tenant")
    p_tu.add_argument("--deactivate", action="store_true", help="Deactivate tenant")
    p_tu.set_defaults(func=cmd_tenants_update)

    # tenants deactivate
    p_td = tsub.add_parser("deactivate", help="Deactivate a tenant")
    p_td.add_argument("slug")
    p_td.set_defaults(func=cmd_tenants_deactivate)

    # tenants rotate-key
    p_tr = tsub.add_parser("rotate-key", help="Rotate tenant API key")
    p_tr.add_argument("slug")
    p_tr.set_defaults(func=cmd_tenants_rotate_key)

    # instances
    p_inst = sub.add_parser("instances", help="Manage instances (tenant-scoped)")
    p_inst.add_argument("--tenant-key", help="Tenant API key (or $TENANT_API_KEY)")
    isub = p_inst.add_subparsers(dest="instance_action", required=True)

    # instances list
    p_il = isub.add_parser("list", help="List tenant instances")
    p_il.set_defaults(func=cmd_instances_list)

    # instances create
    p_ic = isub.add_parser("create", help="Create an instance")
    p_ic.add_argument("name", help="Instance name (without tenant prefix)")
    p_ic.set_defaults(func=cmd_instances_create)

    # instances status
    p_is = isub.add_parser("status", help="Get instance status")
    p_is.add_argument("name")
    p_is.set_defaults(func=cmd_instances_status)

    # instances qr
    p_iq = isub.add_parser("qr", help="Get QR code for pairing")
    p_iq.add_argument("name")
    p_iq.add_argument("--save", metavar="FILE", help="Save QR as image file (e.g. qr.png)")
    p_iq.set_defaults(func=cmd_instances_qr)

    # instances delete
    p_idel = isub.add_parser("delete", help="Delete an instance")
    p_idel.add_argument("name")
    p_idel.set_defaults(func=cmd_instances_delete)

    # instances restart
    p_ir = isub.add_parser("restart", help="Restart an instance")
    p_ir.add_argument("name")
    p_ir.set_defaults(func=cmd_instances_restart)

    # instances logout
    p_ilo = isub.add_parser("logout", help="Logout an instance")
    p_ilo.add_argument("name")
    p_ilo.set_defaults(func=cmd_instances_logout)

    # send
    p_send = sub.add_parser("send", help="Send a message (tenant-scoped)")
    p_send.add_argument("--tenant-key", help="Tenant API key (or $TENANT_API_KEY)")
    p_send.add_argument("instance", help="Instance name")
    p_send.add_argument("number", help="Phone number (e.g. 502XXXXXXXX)")
    p_send.add_argument("text", help="Message text")
    p_send.add_argument("--media-url", help="Media URL for image/document")
    p_send.add_argument("--media-type", choices=["image", "document", "video", "audio"], help="Media type")
    p_send.set_defaults(func=cmd_send)

    return parser


def main():
    global BASE_URL
    parser = build_parser()
    args = parser.parse_args()

    if args.url:
        BASE_URL = args.url

    args.func(args)


if __name__ == "__main__":
    main()
