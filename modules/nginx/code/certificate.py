import datetime
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

DAYS = 3650


def junk_subject() -> x509.Name:
    # Random on purpose: the default server must not name the host it answers for.
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, secrets.token_hex(1).upper()),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, secrets.token_hex(1).upper()),
        x509.NameAttribute(NameOID.LOCALITY_NAME, secrets.token_hex(3)),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, secrets.token_hex(2)),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, secrets.token_hex(2)),
        x509.NameAttribute(NameOID.COMMON_NAME, f'{secrets.token_hex(2)}.example.com'),
    ])


def junk_certificate(bits: int) -> tuple[str, str]:
    """A throwaway RSA key and the self-signed certificate over it, both PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    subject = junk_subject()
    now = datetime.datetime.now(datetime.timezone.utc)

    certificate = (x509.CertificateBuilder()
                   .subject_name(subject)
                   .issuer_name(subject)
                   .public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now)
                   .not_valid_after(now + datetime.timedelta(days=DAYS))
                   .sign(key, hashes.SHA256()))

    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())

    return key_pem.decode(), certificate.public_bytes(serialization.Encoding.PEM).decode()
