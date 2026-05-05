#!/usr/bin/env python3
"""
Run a complete Neo-reGeorg soak session in one command.

Flow:
1) Start neoreg.py client.
2) Wait for startup.
3) Run scripts/soak_runner.py with provided target and thresholds.
4) Save JSON report with timestamp.
5) Stop neoreg.py process.
"""

import argparse
import datetime
import os
import subprocess
import sys
import time


def build_neoreg_command(args):
    cmd = [
        args.python_bin,
        args.neoreg_path,
        "-k",
        args.key,
        "-l",
        args.listen_on,
        "-p",
        str(args.listen_port),
    ]
    for url in args.url:
        cmd.extend(["-u", url])
    for extra in args.neoreg_extra_arg:
        cmd.append(extra)
    return cmd


def build_soak_command(args, report_json):
    cmd = [
        args.python_bin,
        args.soak_runner_path,
        "--proxy-host",
        args.listen_on,
        "--proxy-port",
        str(args.listen_port),
        "--target-host",
        args.target_host,
        "--target-port",
        str(args.target_port),
        "--duration",
        str(args.duration),
        "--interval",
        str(args.interval),
        "--timeout",
        str(args.timeout),
        "--max-consecutive-failures",
        str(args.max_consecutive_failures),
        "--min-success-rate",
        str(args.min_success_rate),
        "--report-json",
        report_json,
    ]

    if args.send_data:
        cmd.extend(["--send-data", args.send_data])
    if args.expect_substring:
        cmd.extend(["--expect-substring", args.expect_substring])
    if args.read_bytes:
        cmd.extend(["--read-bytes", str(args.read_bytes)])

    return cmd


def ensure_report_path(report_dir):
    os.makedirs(report_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(report_dir, "soak-report-%s.json" % ts)


def stop_process(proc):
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Run Neo-reGeorg + soak_runner in one command")
    parser.add_argument("--python-bin", default=sys.executable, help="Python executable")
    parser.add_argument("--neoreg-path", default="neoreg.py", help="Path to neoreg.py")
    parser.add_argument("--soak-runner-path", default=os.path.join("scripts", "soak_runner.py"), help="Path to soak_runner.py")

    parser.add_argument("-k", "--key", required=True, help="Neo-reGeorg key")
    parser.add_argument("-u", "--url", action="append", required=True, help="Tunnel URL (repeat for multiple)")
    parser.add_argument("-l", "--listen-on", default="127.0.0.1", help="Local SOCKS5 bind host")
    parser.add_argument("-p", "--listen-port", type=int, default=1080, help="Local SOCKS5 bind port")
    parser.add_argument("--neoreg-extra-arg", action="append", default=[], help="Extra raw arg for neoreg.py (repeatable)")

    parser.add_argument("--target-host", required=True, help="Target host for soak probes")
    parser.add_argument("--target-port", type=int, required=True, help="Target port for soak probes")
    parser.add_argument("--duration", type=int, default=1800, help="Soak duration seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between probes")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per probe timeout")
    parser.add_argument("--max-consecutive-failures", type=int, default=5, help="Fail threshold")
    parser.add_argument("--min-success-rate", type=float, default=0.95, help="Fail threshold")

    parser.add_argument("--send-data", default="", help="Optional payload for each probe")
    parser.add_argument("--expect-substring", default="", help="Optional response substring")
    parser.add_argument("--read-bytes", type=int, default=1024, help="Receive size")

    parser.add_argument("--startup-wait", type=float, default=3.0, help="Seconds to wait before starting soak")
    parser.add_argument("--report-dir", default="reports", help="Directory for JSON reports")
    args = parser.parse_args()

    report_json = ensure_report_path(args.report_dir)
    neoreg_cmd = build_neoreg_command(args)
    soak_cmd = build_soak_command(args, report_json)

    print("[session] starting neoreg: %s" % " ".join(neoreg_cmd))
    proc = subprocess.Popen(neoreg_cmd)

    try:
        time.sleep(max(0.0, args.startup_wait))

        if proc.poll() is not None:
            print("[session] neoreg exited early with code %s" % proc.returncode)
            return 3

        print("[session] running soak: %s" % " ".join(soak_cmd))
        soak_rc = subprocess.call(soak_cmd)
        print("[session] soak exit code: %s" % soak_rc)
        print("[session] report: %s" % report_json)
        return soak_rc
    finally:
        print("[session] stopping neoreg")
        stop_process(proc)


if __name__ == "__main__":
    sys.exit(main())
