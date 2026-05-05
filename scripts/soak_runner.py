#!/usr/bin/env python3
"""
Simple SOCKS5 soak checker for Neo-reGeorg.

This script repeatedly opens a SOCKS5 connection through the local Neo-reGeorg
client and records stability metrics (success rate, consecutive failures,
latency). It is intentionally dependency-free (stdlib only).
"""

import argparse
import json
import socket
import struct
import sys
import time
from ipaddress import ip_address


def is_ipv4(host):
    try:
        return ip_address(host).version == 4
    except ValueError:
        return False


def socks5_connect(proxy_host, proxy_port, target_host, target_port, timeout):
    s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    s.settimeout(timeout)

    # Greeting: SOCKS5, 1 auth method, no-auth.
    s.sendall(b"\x05\x01\x00")
    resp = s.recv(2)
    if len(resp) != 2 or resp[0] != 0x05 or resp[1] != 0x00:
        raise RuntimeError("SOCKS5 auth negotiation failed")

    if is_ipv4(target_host):
        atyp = b"\x01"
        addr = socket.inet_aton(target_host)
    else:
        host_bytes = target_host.encode("utf-8")
        if len(host_bytes) > 255:
            raise ValueError("target host is too long for SOCKS5 domain mode")
        atyp = b"\x03"
        addr = bytes([len(host_bytes)]) + host_bytes

    req = b"\x05\x01\x00" + atyp + addr + struct.pack(">H", target_port)
    s.sendall(req)

    # Reply: VER, REP, RSV, ATYP, BND.ADDR, BND.PORT
    head = s.recv(4)
    if len(head) != 4 or head[0] != 0x05:
        raise RuntimeError("SOCKS5 connect reply malformed")
    if head[1] != 0x00:
        raise RuntimeError("SOCKS5 connect rejected, REP=0x%02x" % head[1])

    atyp_reply = head[3]
    if atyp_reply == 0x01:
        _ = s.recv(4)
    elif atyp_reply == 0x03:
        n = s.recv(1)
        if not n:
            raise RuntimeError("SOCKS5 connect reply missing domain length")
        _ = s.recv(n[0])
    elif atyp_reply == 0x04:
        _ = s.recv(16)
    else:
        raise RuntimeError("SOCKS5 connect reply has unknown ATYP")

    _ = s.recv(2)
    return s


def run_probe(args):
    started = time.time()
    s = socks5_connect(
        args.proxy_host,
        args.proxy_port,
        args.target_host,
        args.target_port,
        args.timeout,
    )
    try:
        if args.send_data:
            s.sendall(args.send_data.encode("utf-8"))
            if args.expect_substring:
                data = s.recv(args.read_bytes)
                if args.expect_substring.encode("utf-8") not in data:
                    raise RuntimeError("expected substring not found in response")
    finally:
        s.close()
    return time.time() - started


def summarize(samples):
    if not samples:
        return {"min": 0.0, "avg": 0.0, "max": 0.0}
    return {
        "min": min(samples),
        "avg": sum(samples) / float(len(samples)),
        "max": max(samples),
    }


def main():
    parser = argparse.ArgumentParser(description="SOCKS5 soak checker for Neo-reGeorg")
    parser.add_argument("--proxy-host", default="127.0.0.1", help="SOCKS5 proxy host")
    parser.add_argument("--proxy-port", type=int, default=1080, help="SOCKS5 proxy port")
    parser.add_argument("--target-host", required=True, help="Remote target host to connect")
    parser.add_argument("--target-port", type=int, required=True, help="Remote target port")
    parser.add_argument("--duration", type=int, default=1800, help="Test duration in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between probes")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout per probe")
    parser.add_argument("--send-data", default="", help="Optional data to send after CONNECT")
    parser.add_argument("--expect-substring", default="", help="Optional substring expected in response")
    parser.add_argument("--read-bytes", type=int, default=1024, help="Receive size when checking response")
    parser.add_argument("--max-consecutive-failures", type=int, default=5, help="Fail if exceeded")
    parser.add_argument("--min-success-rate", type=float, default=0.95, help="Fail if below threshold")
    parser.add_argument("--report-json", default="", help="Optional path to write JSON report")
    args = parser.parse_args()

    total = 0
    success = 0
    failures = 0
    consecutive_failures = 0
    max_consecutive_failures = 0
    latencies = []
    first_error = ""

    deadline = time.time() + max(1, args.duration)
    print("[soak] starting for %ds" % args.duration)

    while time.time() < deadline:
        total += 1
        try:
            latency = run_probe(args)
            success += 1
            consecutive_failures = 0
            latencies.append(latency)
            print("[soak] probe=%d status=ok latency=%.3fs" % (total, latency))
        except Exception as ex:
            failures += 1
            consecutive_failures += 1
            if not first_error:
                first_error = str(ex)
            if consecutive_failures > max_consecutive_failures:
                max_consecutive_failures = consecutive_failures
            print("[soak] probe=%d status=fail error=%s" % (total, ex))

        if consecutive_failures > args.max_consecutive_failures:
            print("[soak] exceeded max consecutive failures (%d)" % args.max_consecutive_failures)
            break

        time.sleep(max(0.0, args.interval))

    success_rate = (float(success) / float(total)) if total else 0.0
    latency_stats = summarize(latencies)
    passed = (
        success_rate >= args.min_success_rate
        and max_consecutive_failures <= args.max_consecutive_failures
    )

    report = {
        "passed": passed,
        "total_probes": total,
        "success": success,
        "failures": failures,
        "success_rate": success_rate,
        "max_consecutive_failures": max_consecutive_failures,
        "latency": latency_stats,
        "first_error": first_error,
        "proxy": {"host": args.proxy_host, "port": args.proxy_port},
        "target": {"host": args.target_host, "port": args.target_port},
        "duration_seconds": args.duration,
        "interval_seconds": args.interval,
    }

    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print("[soak] summary: %s" % json.dumps(report, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
