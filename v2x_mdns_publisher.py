#!/usr/bin/env python3
"""
V2X mDNS Address Publisher — Dynamic IPv6 Discovery for V2X Ecosystem

This daemon monitors a network interface for IPv6 address changes and
publishes/updates mDNS (Avahi) records so that V2X peers can resolve
each other by hostname (e.g., rsu-v2x.local, obu-v2x.local) instead
of hardcoded addresses.

Usage:
    # On RSU container:
    python3 v2x_mdns_publisher.py --hostname rsu-v2x --interface eth0

    # On OBU/UE container:
    python3 v2x_mdns_publisher.py --hostname obu-v2x --interface uesimtun1

    # With fallback static address:
    python3 v2x_mdns_publisher.py --hostname obu-v2x --interface uesimtun1 --fallback fd00:5678::2

Dependencies:
    - avahi-daemon (apt install avahi-daemon)
    - avahi-utils  (apt install avahi-utils)  — for avahi-publish-address
    - libnss-mdns  (apt install libnss-mdns)  — for getaddrinfo() .local resolution
"""

import argparse
import ipaddress
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL_SEC = 5       # How often to check for address changes
ANNOUNCE_RETRIES  = 3       # Retry count for avahi-publish-address
ULA_PREFIX        = "fd00:5678::/64"   # Our V2X ULA overlay prefix
MULTICAST_GROUP   = "ff02::1"          # All-nodes link-local multicast
ANNOUNCE_PORT     = 5353               # mDNS port

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("v2x-mdns")


# ---------------------------------------------------------------------------
# Address Discovery
# ---------------------------------------------------------------------------
def get_ipv6_addresses(interface: str) -> list[str]:
    """Get all IPv6 addresses assigned to a network interface."""
    addrs = []
    try:
        result = subprocess.run(
            ["ip", "-6", "addr", "show", "dev", interface, "scope", "global"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            match = re.search(r'inet6\s+([0-9a-f:]+)/\d+', line)
            if match:
                addrs.append(match.group(1))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning(f"Failed to query interface {interface}: {e}")
    return addrs


def select_best_address(addresses: list[str], ula_prefix: str = ULA_PREFIX) -> Optional[str]:
    """
    Select the best IPv6 address for mDNS publication.
    Priority:
        1. ULA address (fd00:5678::/64) — our V2X overlay
        2. GUA address (2000::/3)       — global unicast
        3. Any non-link-local address
    """
    ula_net = ipaddress.IPv6Network(ula_prefix)

    ula_addrs = []
    gua_addrs = []
    other_addrs = []

    for addr_str in addresses:
        try:
            addr = ipaddress.IPv6Address(addr_str)
        except ValueError:
            continue

        if addr.is_link_local:
            continue  # Skip fe80:: addresses (not routable)

        if addr in ula_net:
            ula_addrs.append(addr_str)
        elif addr.is_global:
            gua_addrs.append(addr_str)
        else:
            other_addrs.append(addr_str)

    if ula_addrs:
        return ula_addrs[0]
    if gua_addrs:
        return gua_addrs[0]
    if other_addrs:
        return other_addrs[0]
    return None


# ---------------------------------------------------------------------------
# Avahi mDNS Publishing
# ---------------------------------------------------------------------------
class AvahiPublisher:
    """Manages an avahi-publish-address subprocess for dynamic mDNS updates."""

    def __init__(self, hostname: str):
        self.hostname = hostname
        self.fqdn = f"{hostname}.local"
        self._process: Optional[subprocess.Popen] = None
        self._current_address: Optional[str] = None

    @property
    def current_address(self) -> Optional[str]:
        return self._current_address

    def publish(self, address: str) -> bool:
        """Publish or update the mDNS address record."""
        if self._current_address == address and self._is_alive():
            return True  # Already publishing this address

        # Kill existing publisher if running
        self.stop()

        for attempt in range(1, ANNOUNCE_RETRIES + 1):
            try:
                log.info(f"Publishing {self.fqdn} → {address} (attempt {attempt})")
                self._process = subprocess.Popen(
                    ["avahi-publish-address", "-R", self.fqdn, address],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                # Give it a moment to register
                time.sleep(0.5)

                if self._is_alive():
                    self._current_address = address
                    log.info(f"✓ Successfully publishing {self.fqdn} → {address}")
                    return True
                else:
                    stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                    log.warning(f"avahi-publish-address exited early: {stderr.strip()}")

            except FileNotFoundError:
                log.error("avahi-publish-address not found. Install: apt install avahi-utils")
                return False
            except Exception as e:
                log.warning(f"Attempt {attempt} failed: {e}")

            time.sleep(1)

        log.error(f"Failed to publish {self.fqdn} after {ANNOUNCE_RETRIES} attempts")
        return False

    def stop(self):
        """Stop the avahi-publish-address subprocess."""
        if self._process and self._is_alive():
            log.debug(f"Stopping publisher for {self.fqdn}")
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._current_address = None

    def _is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None


# ---------------------------------------------------------------------------
# Multicast Announcement (Supplementary)
# ---------------------------------------------------------------------------
def send_multicast_announcement(hostname: str, address: str, interface: str):
    """
    Send a UDP multicast announcement to notify peers of an address change.
    This is a supplementary mechanism — mDNS (Avahi) is the primary.
    """
    try:
        # Find interface index for IPv6 multicast
        if_index = socket.if_nametoindex(interface)

        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, if_index.to_bytes(4, 'native'))
        sock.settimeout(1)

        message = f"V2X-ADDR-UPDATE|{hostname}|{address}".encode()
        sock.sendto(message, (MULTICAST_GROUP, ANNOUNCE_PORT, 0, if_index))
        sock.close()
        log.debug(f"Multicast announcement sent: {hostname} → {address}")
    except Exception as e:
        log.debug(f"Multicast announcement failed (non-critical): {e}")


# ---------------------------------------------------------------------------
# Watchdog Loop
# ---------------------------------------------------------------------------
class V2XAddressPublisher:
    """
    Main watchdog daemon that monitors an interface for IPv6 changes
    and keeps the mDNS record updated.
    """

    def __init__(self, hostname: str, interface: str, fallback: Optional[str] = None):
        self.hostname = hostname
        self.interface = interface
        self.fallback = fallback
        self.publisher = AvahiPublisher(hostname)
        self._running = True

        # Handle graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def run(self):
        """Main monitoring loop."""
        log.info(f"V2X mDNS Publisher started")
        log.info(f"  Hostname:  {self.hostname}.local")
        log.info(f"  Interface: {self.interface}")
        log.info(f"  Fallback:  {self.fallback or 'none'}")
        log.info(f"  Poll:      every {POLL_INTERVAL_SEC}s")

        while self._running:
            try:
                # Discover current IPv6 addresses
                addresses = get_ipv6_addresses(self.interface)
                best_addr = select_best_address(addresses)

                if best_addr:
                    if best_addr != self.publisher.current_address:
                        log.info(f"Address change detected: "
                                 f"{self.publisher.current_address} → {best_addr}")
                        if self.publisher.publish(best_addr):
                            send_multicast_announcement(
                                self.hostname, best_addr, self.interface
                            )
                elif self.fallback:
                    if self.fallback != self.publisher.current_address:
                        log.warning(f"No IPv6 on {self.interface}, using fallback: {self.fallback}")
                        self.publisher.publish(self.fallback)
                else:
                    log.warning(f"No IPv6 address found on {self.interface}")

            except Exception as e:
                log.error(f"Error in monitoring loop: {e}")

            time.sleep(POLL_INTERVAL_SEC)

        # Cleanup
        self.publisher.stop()
        log.info("V2X mDNS Publisher stopped")


# ---------------------------------------------------------------------------
# Utility: Resolve a V2X mDNS hostname
# ---------------------------------------------------------------------------
def resolve_v2x_host(hostname: str, port: int = 0) -> Optional[str]:
    """
    Resolve a V2X mDNS hostname to an IPv6 address using getaddrinfo.
    Returns the first IPv6 address found, or None.

    Requires libnss-mdns and avahi-daemon running on the system.
    """
    fqdn = hostname if hostname.endswith(".local") else f"{hostname}.local"
    try:
        results = socket.getaddrinfo(fqdn, port, socket.AF_INET6, socket.SOCK_STREAM)
        if results:
            # results[0] = (family, type, proto, canonname, sockaddr)
            addr = results[0][4][0]
            log.info(f"Resolved {fqdn} → {addr}")
            return addr
    except socket.gaierror as e:
        log.warning(f"Failed to resolve {fqdn}: {e}")
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="V2X mDNS Address Publisher — Dynamic IPv6 Discovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # RSU container:
  %(prog)s --hostname rsu-v2x --interface eth0

  # OBU/UE container:
  %(prog)s --hostname obu-v2x --interface uesimtun1 --fallback fd00:5678::2

  # Just resolve a hostname (no daemon):
  %(prog)s --resolve obu-v2x.local
        """
    )

    parser.add_argument("--hostname", type=str, default="v2x-node",
                        help="mDNS hostname to publish (without .local)")
    parser.add_argument("--interface", type=str, default="eth0",
                        help="Network interface to monitor")
    parser.add_argument("--fallback", type=str, default=None,
                        help="Fallback static IPv6 address if interface has none")
    parser.add_argument("--resolve", type=str, default=None,
                        help="Just resolve a .local hostname and exit")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SEC,
                        help=f"Polling interval in seconds (default: {POLL_INTERVAL_SEC})")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve mode: just resolve and exit
    if args.resolve:
        addr = resolve_v2x_host(args.resolve)
        if addr:
            print(addr)
            sys.exit(0)
        else:
            print(f"Could not resolve {args.resolve}", file=sys.stderr)
            sys.exit(1)

    # Daemon mode: monitor and publish
    global POLL_INTERVAL_SEC
    POLL_INTERVAL_SEC = args.poll_interval

    daemon = V2XAddressPublisher(
        hostname=args.hostname,
        interface=args.interface,
        fallback=args.fallback
    )
    daemon.run()


if __name__ == "__main__":
    main()
