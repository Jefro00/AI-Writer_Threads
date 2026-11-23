"""Generate a self-signed certificate for local HTTPS OAuth callbacks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from OpenSSL import crypto

ROOT = Path(__file__).resolve().parent.parent
CERT = ROOT / "localhost_cert.pem"
KEY = ROOT / "localhost_key.pem"

key = crypto.PKey()
key.generate_key(crypto.TYPE_RSA, 2048)
cert = crypto.X509()
cert.get_subject().CN = "localhost"
cert.set_serial_number(int(datetime.now().timestamp()))
cert.gmtime_adj_notBefore(0)
cert.gmtime_adj_notAfter(int(timedelta(days=365).total_seconds()))
cert.set_issuer(cert.get_subject())
cert.set_pubkey(key)
cert.sign(key, "sha256")
CERT.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
KEY.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))
print("created:", CERT.name, KEY.name)
