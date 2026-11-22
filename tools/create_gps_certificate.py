
"""Create a local lab CA and an HTTPS certificate for the driver's LAN IPv4 address."""

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


def validate_lan_ip(value, parser):
    """Accept a private, usable LAN IPv4 address."""

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


def generate_certificates(address):
    """Generate a local CA certificate and its HTTPS server certificate."""

    now = datetime.now(timezone.utc)

    # Generate independent CA and server private keys.
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    ca_name = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME,
            "Fleet Guardian Lab GPS CA",
        )
    ])

    # Create the local certificate authority.
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(
            x509.BasicConstraints(
                ca=True,
                path_length=0,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Create the HTTPS certificate for the driver's PC.
    server_name = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME,
            str(address),
        )
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=89))
        .add_extension(
            x509.BasicConstraints(
                ca=False,
                path_length=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                server_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(address)
            ]),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH
            ]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return ca, cert, server_key


def write_certificates(output, ca, cert, server_key):
    """Write certificate files safely without overwriting existing files."""

    output = Path(output)

    if output.exists():
        raise FileExistsError(
            f"Output already exists: {output}. "
            "Choose a new directory to avoid replacing trusted certificates."
        )

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)

    temporary_dir = Path(
        tempfile.mkdtemp(
            prefix="fleet-gps-cert-",
            dir=str(parent),
        )
    )

    try:
        (temporary_dir / "phone-ca.crt").write_bytes(
            ca.public_bytes(serialization.Encoding.PEM)
        )

        (temporary_dir / "server.crt").write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
        )

        key_path = temporary_dir / "server.key"

        key_path.write_bytes(
            server_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        # Restrict private-key permissions where the OS supports chmod.
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass

        # Rename the completed directory into place.
        # This avoids exposing a partially generated certificate set.
        os.rename(temporary_dir, output)

    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "ip",
        help="Driver PC private LAN IPv4 address",
    )

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
            "Output already exists; use a new directory "
            "to avoid replacing trusted certificates."
        )

    try:
        ca, cert, server_key = generate_certificates(address)

        write_certificates(
            args.output,
            ca,
            cert,
            server_key,
        )

    except (OSError, ValueError) as error:
        parser.error(f"Certificate generation failed: {error}")

    print(f"Created certificates in: {args.output}")
    print("Transfer only phone-ca.crt to your phone.")
    print("Keep server.key private and on the driver PC.")
    print("See README.md for the phone setup.")


if __name__ == "__main__":
    main()
