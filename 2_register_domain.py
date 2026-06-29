#!/usr/bin/env python3
"""Step 2 (standalone): suggest/register a cheap domain on Porkbun and point its
mail DNS at a VPS. Adds A, MX, SPF and DMARC records (DKIM is added later, after
the mail server generates its key -- see Step 3 output).

Run standalone (reads the target IP from the environment):
    VPS_IP=203.0.113.10 python 2_register_domain.py

Fill in API_KEY / SECRET_KEY below first. Registration spends Porkbun account
credit and asks you to type "yes" to confirm.
"""

import os
import sys
import time
import uuid

import requests

# ---------------------------------------------------------------- CONFIG ----
API_KEY    = "YOUR_PORKBUN_API_KEY"        # starts with pk1_
SECRET_KEY = "YOUR_PORKBUN_SECRET_KEY"     # starts with sk1_

DESIRED_DOMAIN = None                      # e.g. "mycoolmail.xyz", or None to suggest
BASE_NAME      = "autocheapmail"           # used only when DESIRED_DOMAIN is None
MAX_PRICE_USD  = 5.00

CANDIDATE_TLDS  = ["xyz", "click", "online", "site", "top", "store", "space", "fun"]
MAX_SUGGESTIONS = 4

MAIL_SUBDOMAIN = "mail"
MX_PRIORITY    = 10
DNS_TTL        = 600
DMARC_POLICY   = "quarantine"              # none | quarantine | reject

DRY_RUN_ONLY   = False                     # True = never charge/register

API_BASE = "https://api.porkbun.com/api/json/v3"

# ------------------------------------------------------------- PLUMBING ----
session = requests.Session()
session.headers.update({
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
    "X-Secret-API-Key": SECRET_KEY,
})


def api_post(path, payload=None, extra_headers=None) -> dict:
    body = {"apikey": API_KEY, "secretapikey": SECRET_KEY}
    if payload:
        body.update(payload)
    resp = session.post(f"{API_BASE}{path}", json=body, headers=extra_headers or {}, timeout=30)
    try:
        return resp.json()
    except ValueError:
        return {"status": "ERROR", "message": f"Non-JSON ({resp.status_code}): {resp.text[:200]}"}


def api_get(path) -> dict:
    resp = session.get(f"{API_BASE}{path}", timeout=30)
    try:
        return resp.json()
    except ValueError:
        return {"status": "ERROR", "message": f"Non-JSON ({resp.status_code}): {resp.text[:200]}"}


def ok(d): return str(d.get("status", "")).upper() == "SUCCESS"


def fail(msg):
    print(f"\n[ABORT] {msg}")
    sys.exit(1)


# --------------------------------------------------------------- API ----
def validate_credentials():
    print("Validating credentials...")
    d = api_post("/ping")
    if not ok(d):
        fail(f"Auth check failed: {d.get('message', d)}")
    print(f"  OK (your IP as seen by Porkbun: {d.get('yourIp', 'unknown')})")


def get_pricing():
    d = api_post("/pricing/get")
    return d.get("pricing", {}) if ok(d) else {}


def reg_price(pricing, tld):
    try:
        return float(pricing.get(tld, {}).get("registration"))
    except (TypeError, ValueError):
        return None


def check_domain(domain):
    d = api_post(f"/domain/checkDomain/{domain}")
    wait = int(d.get("ttlRemaining", 10) or 10)
    if not ok(d):
        return {"available": False, "price": None, "premium": False,
                "wait": wait, "error": d.get("message", "check failed")}
    r = d.get("response", {}) or {}
    avail = str(r.get("avail", r.get("available", ""))).lower() in ("yes", "available", "true", "1")
    price = r.get("price") or r.get("regularPrice")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    premium = str(r.get("premium", "no")).lower() in ("yes", "true", "1")
    return {"available": avail, "price": price, "premium": premium, "wait": wait}


def tld_api_registerable(tld):
    d = api_get(f"/domain/getRegistrationRequirements/{tld}")
    return bool(d.get("apiRegisterable", True)) if ok(d) else True


def suggest_domains():
    pricing = get_pricing()
    tlds = sorted(CANDIDATE_TLDS,
                  key=lambda t: (reg_price(pricing, t) is None, reg_price(pricing, t) or 9e9))
    print(f"\nLooking for available domains under ${MAX_PRICE_USD:.2f} for '{BASE_NAME}'...")
    print("(checkDomain is rate-limited, so this pauses ~10s between names.)\n")

    hits = []
    for i, tld in enumerate(tlds):
        if len(hits) >= MAX_SUGGESTIONS:
            break
        domain = f"{BASE_NAME}.{tld}"
        print(f"  checking {domain} ...", end=" ", flush=True)
        res = check_domain(domain)
        if res.get("error"):
            print(f"skip ({res['error']})")
        elif res["premium"]:
            print("skip (premium)")
        elif not res["available"]:
            print("taken")
        elif res["price"] is None:
            print("skip (no price)")
        elif res["price"] > MAX_PRICE_USD:
            print(f"available but ${res['price']:.2f} (over budget)")
        else:
            print(f"AVAILABLE  ${res['price']:.2f}")
            hits.append((domain, res["price"]))
        if i < len(tlds) - 1 and len(hits) < MAX_SUGGESTIONS:
            time.sleep(min(res["wait"] + 1, 12))
    return sorted(hits, key=lambda x: x[1])


def choose_domain():
    if DESIRED_DOMAIN:
        print(f"\nChecking your requested domain: {DESIRED_DOMAIN}")
        res = check_domain(DESIRED_DOMAIN)
        if res.get("error"):
            fail(f"Could not check {DESIRED_DOMAIN}: {res['error']}")
        if not res["available"]:
            fail(f"{DESIRED_DOMAIN} is not available.")
        if res["premium"]:
            fail(f"{DESIRED_DOMAIN} is premium and can't be registered via API.")
        if res["price"] is None:
            fail("No price returned for that domain.")
        if res["price"] > MAX_PRICE_USD:
            print(f"  Note: ${res['price']:.2f}, above your ${MAX_PRICE_USD:.2f} budget.")
        return DESIRED_DOMAIN, res["price"]

    options = suggest_domains()
    if not options:
        fail("No available domains under budget. Try another BASE_NAME or more TLDs.")
    print("\nAvailable options within budget:")
    for idx, (dom, price) in enumerate(options, 1):
        print(f"  {idx}. {dom}  -  ${price:.2f}/yr")
    while True:
        choice = input(f"\nPick a domain [1-{len(options)}] (or 'q' to quit): ").strip()
        if choice.lower() in ("q", "quit", "exit"):
            fail("Cancelled by user.")
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        print("  Invalid choice, try again.")


def dry_run_register(domain, price_usd):
    tld = domain.rsplit(".", 1)[-1]
    if not tld_api_registerable(tld):
        fail(f".{tld} can't be registered through the API. Register it on porkbun.com, "
             f"then run the DNS step only.")
    cents = int(round(price_usd * 100))
    print(f"\nDry run (no charge) for {domain} at ${price_usd:.2f} ({cents} cents)...")
    d = api_post(f"/domain/create/{domain}", {"cost": cents, "agreeToTerms": "yes", "dryRun": True})
    if not ok(d):
        fail(f"Dry run rejected: {d.get('message', d)}")
    print(f"  wouldSucceed : {d.get('wouldSucceed')}")
    print(f"  cost         : {d.get('costDisplay', f'{cents}c')}")
    print(f"  balance      : ${(d.get('balance', 0) or 0) / 100:.2f}")
    print(f"  funds ok     : {d.get('sufficientFunds')}")
    if "withinMonthlySpendLimit" in d:
        print(f"  within cap   : {d.get('withinMonthlySpendLimit')}")
    if not d.get("wouldSucceed"):
        fail(f"Registration would NOT succeed: {d.get('message', 'see above')}")
    return d


def register(domain, cents):
    d = api_post(f"/domain/create/{domain}", {"cost": cents, "agreeToTerms": "yes"},
                 extra_headers={"Idempotency-Key": str(uuid.uuid4())})
    if not ok(d):
        fail(f"Registration failed: {d.get('message', d)}")
    return d


def verify(domain):
    d = api_get(f"/domain/get/{domain}")
    if ok(d):
        print(f"  Verified: {domain} is in your account.")
    else:
        print(f"  (Couldn't verify yet: {d.get('message', 'unknown')} -- may need a moment.)")


def _create_record(domain, rec, label):
    r = api_post(f"/dns/create/{domain}", rec)
    if ok(r):
        print(f"  {label}  (id {r.get('id')})")
    else:
        print(f"  [!] {label} failed: {r.get('message', r)}")
    return ok(r)


def configure_dns(domain, vps_ip):
    """A (mail) + MX (apex) + SPF + DMARC. Returns True if all succeeded."""
    print(f"\nConfiguring DNS for {domain} -> {vps_ip} ...")
    results = []

    results.append(_create_record(domain,
        {"name": MAIL_SUBDOMAIN, "type": "A", "content": vps_ip, "ttl": str(DNS_TTL)},
        f"A    {MAIL_SUBDOMAIN}.{domain} -> {vps_ip}"))
    time.sleep(1)

    results.append(_create_record(domain,
        {"name": "", "type": "MX", "content": f"{MAIL_SUBDOMAIN}.{domain}",
         "prio": str(MX_PRIORITY), "ttl": str(DNS_TTL)},
        f"MX   {domain} -> {MAIL_SUBDOMAIN}.{domain} (prio {MX_PRIORITY})"))
    time.sleep(1)

    results.append(_create_record(domain,
        {"name": "", "type": "TXT", "content": "v=spf1 mx ~all", "ttl": str(DNS_TTL)},
        "SPF  (TXT) v=spf1 mx ~all"))
    time.sleep(1)

    dmarc = f"v=DMARC1; p={DMARC_POLICY}; rua=mailto:postmaster@{domain}; fo=1"
    results.append(_create_record(domain,
        {"name": "_dmarc", "type": "TXT", "content": dmarc, "ttl": str(DNS_TTL)},
        f"DMARC (TXT) p={DMARC_POLICY}"))

    if not all(results):
        print("\n  If records failed with a permission error, enable 'API Access' for this")
        print("  domain under Account > Domain Management at porkbun.com/account.")
    print("\n  NOTE: DKIM is NOT set here -- the mail server generates the key in Step 3.")
    print("  Add the DKIM TXT record it prints once the container is running.")
    return all(results)


# ---------------------------------------------------- ORCHESTRATION HOOKS ----
def select_and_register():
    """Pick + register a domain (no DNS, no IP needed). Returns (domain, price)."""
    if "YOUR_" in API_KEY or "YOUR_" in SECRET_KEY:
        fail("Set API_KEY and SECRET_KEY at the top of the script first.")
    validate_credentials()
    domain, price = choose_domain()
    cents = int(round(price * 100))
    preview = dry_run_register(domain, price)
    if DRY_RUN_ONLY:
        print("\nDRY_RUN_ONLY is on -- not registering. Set it False to register for real.")
        sys.exit(0)
    print(f"\n>>> This registers {domain} and charges "
          f"{preview.get('costDisplay', f'{cents} cents')} from your Porkbun credit. <<<")
    if input("Type 'yes' to confirm: ").strip().lower() != "yes":
        fail("Not confirmed -- nothing was registered or charged.")
    print(f"\nRegistering {domain} ...")
    result = register(domain, cents)
    charged = (result.get("cost", cents) or cents) / 100
    print(f"  Registered. Charged ${charged:.2f}. "
          f"Balance: ${(result.get('balance', 0) or 0) / 100:.2f}")
    verify(domain)
    return domain, price


def main():
    vps_ip = os.environ.get("VPS_IP")
    if not vps_ip:
        fail("Set VPS_IP in the environment (the droplet's public IP) before running.")
    domain, _ = select_and_register()
    configure_dns(domain, vps_ip)
    print(f"\nDone. {MAIL_SUBDOMAIN}.{domain} points at {vps_ip}. DNS needs time to propagate.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
