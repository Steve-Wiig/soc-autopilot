"""
simulator/mock_wazuh.py
~~~~~~~~~~~~~~~~~~~~~~~
Generates realistic, continuous fake Wazuh JSON logs.

Features:
  - Three event categories: auth failures, firewall drops, general syslog
  - Configurable output: stdout (pipeable), local file, or UDP socket
  - Adjustable rate (logs per second)
  - Timestamps in Wazuh-standard ISO format
  - Realistic source IPs, destinations, rule IDs, and messages

Usage:
  # Generate to stdout at 1 log/second (pipe to Wazuh manager or consumer)
  python simulator/mock_wazuh.py --output stdout --rate 1

  # Generate to a file
  python simulator/mock_wazuh.py --output file --rate 0.5 > /tmp/wazuh_test.log

  # Send via UDP to a local listener
  python simulator/mock_wazuh.py --output udp --host 127.0.0.1 --port 514 --rate 2
"""

import json
import random
import time
import argparse
import uuid
from datetime import datetime, timezone

# Predefined sets of realistic data for generating fake Wazuh events
AUTH_FAILURES = [
    {
        "rule_id": 4001,
        "name": "Authentication failure",
        "description": "Failed login attempt",
        "location": "sshd",
    },
    {
        "rule_id": 4002,
        "name": "Multiple authentication failures",
        "description": "Too many failed login attempts",
        "location": "sshd",
    },
]

FIREWALL_DROPS = [
    {
        "rule_id": 5701,
        "name": "Firewall drop",
        "description": "Packet dropped by firewall rule",
        "location": "firewall",
    },
    {
        "rule_id": 5702,
        "name": "Outbound drop",
        "description": "Outbound connection blocked",
        "location": "firewall",
    },
]

GENERAL_EVENTS = [
    {
        "rule_id": 31000,
        "name": "System event",
        "description": "General system notification",
        "location": "syslog",
    },
    {
        "rule_id": 31001,
        "name": "Service start",
        "description": "Service started",
        "location": "syslog",
    },
]

SOURCES = ["192.168.1.10", "10.0.0.45", "172.16.0.10", "192.168.1.55"]
DESTINATIONS = ["10.0.0.1", "192.168.1.1", "172.16.0.254"]
USERS = ["admin", "root", "user1", "service_account", "unknown"]


def generate_auth_failure():
    event = random.choice(AUTH_FAILURES)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": str(uuid.uuid4()),
        "agent": {
            "id": random.randint(1, 10000),
            "name": "wazuh-agent",
            "ip": random.choice(SOURCES),
        },
        "rule": event,
        "sourceip": random.choice(SOURCES),
        "srcip": random.choice(SOURCES),
        "srcuser": random.choice(USERS),
        "data": {"event": "auth_fail"},
    }


def generate_firewall_drop():
    event = random.choice(FIREWALL_DROPS)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": str(uuid.uuid4()),
        "agent": {"id": random.randint(1, 10000), "name": "wazuh-agent", "ip": random.choice(SOURCES)},
        "rule": event,
        "sourceip": random.choice(SOURCES),
        "destinationip": random.choice(DESTINATIONS),
        "data": {"event": "firewall_drop", "proto": random.choice(["tcp", "udp", "icmp"])},
    }


def generate_general_event():
    event = random.choice(GENERAL_EVENTS)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": str(uuid.uuid4()),
        "agent": {"id": random.randint(1, 10000), "name": "wazuh-agent", "ip": random.choice(SOURCES)},
        "rule": event,
        "data": {"event": "general"},
    }


def main():
    parser = argparse.ArgumentParser(description="Mock Wazuh log generator")
    parser.add_argument(
        "--output", choices=["stdout", "file", "udp"], default="stdout",
        help="Output destination for generated logs"
    )
    parser.add_argument(
        "--rate", type=float, default=1.0,
        help="Number of logs to generate per second"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for UDP output (ignored for stdout/file)"
    )
    parser.add_argument(
        "--port", type=int, default=514,
        help="Port for UDP output (ignored for stdout/file)"
    )
    args = parser.parse_args()

    interval = 1.0 / args.rate if args.rate > 0 else 0

    try:
        while True:
            choice = random.choice(["auth", "firewall", "general"])
            if choice == "auth":
                log = generate_auth_failure()
            elif choice == "firewall":
                log = generate_firewall_drop()
            else:
                log = generate_general_event()

            print(json.dumps(log))

            if interval > 0:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping mock Wazuh generator.", file=sys.stderr)


if __name__ == "__main__":
    main()
