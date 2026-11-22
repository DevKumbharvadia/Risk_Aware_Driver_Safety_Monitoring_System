
"""Create a local lab CA and HTTPS certificate for a driver's LAN IPv4 address."""

import argparse
import ipaddress
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


CA_NAME = "Fleet Guardian Lab GPS CA"


def validate_lan_ip(value, parser):
    """Accept a usable private LAN IPv4 address."""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        parser.error("Invalid IP address.")

    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        parser.error(
            "Provide a valid private LAN IPv4 address, "
            "such as 192.168.1.10."
        )

    return address


def _create_certificate(
    subject,
    issuer,
    public_key,
    signing_key,
    now,
    days,
    is_ca,
    address=None,
):
    """Build and sign a CA or HTTPS server certificate."""

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.BasicConstraints(ca=is_ca, path_length=0 if is_ca else None),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                signing_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=not is_ca,
                content_commitment=False,
                key_encipherment=not is_ca,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=is_ca,
                crl_sign=is_ca,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
    )

    if address is not None:
        builder = (
            builder
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(address)]),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
        )

    return builder.sign(signing_key, hashes.SHA256())


def generate_certificates(address):
    """Generate a local CA and its HTTPS server certificate."""

    address = ipaddress.ip_address(address)

    if address.version != 4 or not address.is_private or address.is_reserved:
        raise ValueError("A usable private LAN IPv4 address is required.")

    now = datetime.now(timezone.utc)

    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)
    ])
    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, str(address))
    ])

    ca = _create_certificate(
        ca_name, ca_name, ca_key.public_key(),
        ca_key, now, 90, True,
    )

    cert = _create_certificate(
        server_name, ca_name, server_key.public_key(),
        ca_key, now, 89, False, address,
    )

    return ca, cert, server_key


def write_certificates(output, ca, cert, server_key):
    """Write certificates atomically without replacing existing output."""

    output = Path(output)

    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_dir = Path(
        tempfile.mkdtemp(prefix="fleet-gps-cert-", dir=output.parent)
    )

    try:
        files = {
            "phone-ca.crt": ca.public_bytes(serialization.Encoding.PEM),
            "server.crt": cert.public_bytes(serialization.Encoding.PEM),
            "server.key": server_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        }

        for name, content in files.items():
            path = temporary_dir / name
            path.write_bytes(content)

            if name == "server.key":
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass

        # Refuse to replace an existing directory.
        if output.exists():
            raise FileExistsError(f"Output already exists: {output}")

        os.rename(temporary_dir, output)

    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="Driver PC private LAN IPv4 address")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/gps-cert"),
        help="Output directory (default: data/gps-cert)",
    )

    args = parser.parse_args()
    address = validate_lan_ip(args.ip, parser)

    if args.output.exists():
        parser.error(
            "Output already exists; choose a new directory."
        )

    try:
        ca, cert, server_key = generate_certificates(address)
        write_certificates(args.output, ca, cert, server_key)
    except (OSError, ValueError) as error:
        parser.error(f"Certificate generation failed: {error}")

    print(f"Created certificates in: {args.output}")
    print("Transfer only phone-ca.crt to your phone.")
    print("Keep server.key private and on the driver PC.")
    print("See README.md for the phone setup.")


if __name__ == "__main__":
    main()
