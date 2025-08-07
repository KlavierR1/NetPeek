# scanner.py
#
# Copyright 2025 ZingyTomato
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import ipaddress
import socket
from ping3 import ping
from concurrent.futures import ThreadPoolExecutor
from gi.repository import GLib

class NetworkScanner:
    """Network scanning functionality"""

    def __init__(self):
        self.common_ports = [22, 80, 443, 3389, 53, 21, 23, 8080, 8443, 8006, 5000]
        self.is_scanning = False
        self.hosts_scanned = 0
        self.total_hosts = 0
        self.partial_results = []  # Store partial results for when scan is stopped

    def validate_ip_range(self, ip_range):
        if not ip_range:
            return False, _("Please enter an IP range")

        try:
            if '/' in ip_range:
                ipaddress.ip_network(ip_range, strict=False)
            elif '-' in ip_range:
                base_ip, range_part = ip_range.rsplit('-', 1)
                base_parts = base_ip.split('.')

                if len(base_parts) == 4:
                    ipaddress.IPv4Address(base_ip)
                    int(range_part)
                elif len(base_parts) == 3:
                    ipaddress.IPv4Address(f"{base_ip}.1")
                    int(range_part)
                else:
                    raise ValueError(_("Invalid range format!"))
            else:
                ipaddress.IPv4Address(ip_range)

            return True, _("Valid IP range")

        except Exception as e:
            return False, _("Invalid IP range: ") + str(e)

    def is_port_open(self, ip, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((ip, port)) == 0
        except:
            return False

    def scan_single_ip(self, ip_str, lock, devices, progress_callback=None):
        # Check if scanning should continue
        if not self.is_scanning:
            return

        alive = False
        open_ports = []

        for port in self.common_ports:
            if not self.is_scanning:  # Check again before each port scan
                return
            if self.is_port_open(ip_str, port):
                alive = True
                open_ports.append(port)

        if not alive and self.is_scanning:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    if s.connect_ex((ip_str, 80)) == 0:
                        alive = True
                    elif ping(ip_str):
                        alive = True
            except:
                pass

        if alive and self.is_scanning:
            hostname = ip_str
            try:
                hostname = socket.gethostbyaddr(ip_str)[0]
            except:
                pass

            device = {
                "hostname": hostname,
                "ip": ip_str,
                "ports": ", ".join(map(str, open_ports)) if open_ports else _("Host alive (no open ports detected)")
            }

            with lock:
                devices.append(device)
                self.partial_results.append(device)  # Store partial result

        # Update progress counter
        with lock:
            self.hosts_scanned += 1
            if progress_callback:
                GLib.idle_add(progress_callback, self.hosts_scanned, self.total_hosts)

    def parse_ip_range(self, ip_range):
        hosts = []

        if '/' in ip_range:
            net = ipaddress.ip_network(ip_range, strict=False)
            hosts = list(net.hosts())
        elif '-' in ip_range:
            base_ip, range_part = ip_range.rsplit('-', 1)
            base_parts = base_ip.split('.')

            if len(base_parts) == 4:
                base_network = '.'.join(base_parts[:3])
                start_ip = int(base_parts[3])
                end_ip = int(range_part)
            elif len(base_parts) == 3:
                base_network = base_ip
                start_ip = 1
                end_ip = int(range_part)
            else:
                raise ValueError(_("Invalid range format!"))

            hosts = [ipaddress.IPv4Address(f"{base_network}.{i}")
                     for i in range(start_ip, end_ip + 1)]
        else:
            hosts = [ipaddress.IPv4Address(ip_range)]

        return hosts

    def scan_network(self, ip_range, callback, error_callback, progress_callback=None):
        def do_scan():
            try:
                self.is_scanning = True
                self.partial_results = []  # Clear previous partial results
                self.hosts_scanned = 0  # Reset counter every scan

                devices = []
                lock = threading.Lock()

                hosts = self.parse_ip_range(ip_range)
                self.total_hosts = len(hosts)  # Store total for progress tracking

                # Initialize progress
                if progress_callback:
                    GLib.idle_add(progress_callback, 0, self.total_hosts)

                with ThreadPoolExecutor(max_workers=100) as executor:
                    futures = []
                    for host in hosts:
                        if not self.is_scanning:
                            break
                        future = executor.submit(self.scan_single_ip, str(host), lock, devices, progress_callback)
                        futures.append(future)

                    # Wait for all futures or until scanning is stopped
                    for future in futures:
                        if not self.is_scanning:
                            # Cancel remaining futures if scan was stopped
                            for remaining_future in futures:
                                remaining_future.cancel()
                            break
                        try:
                            future.result(timeout=1)  # Short timeout to allow checking scan status
                        except:
                            pass

                # Only call callback if scan completed normally (not stopped)
                if self.is_scanning:
                    self.is_scanning = False
                    devices_sorted = sorted(devices, key=lambda x: ipaddress.IPv4Address(x['ip']))
                    GLib.idle_add(callback, devices_sorted)

            except Exception as e:
                self.is_scanning = False
                GLib.idle_add(error_callback, _("Scan failed: ") + str(e))

        if not self.is_scanning:
            threading.Thread(target=do_scan, daemon=True).start()

    def stop_scan(self):
        """Stop the current scan"""
        self.is_scanning = False

    def get_partial_results(self):
        """Get the partial results from a stopped scan"""
        return sorted(self.partial_results, key=lambda x: ipaddress.IPv4Address(x['ip']))

    def get_local_ip_range():
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        # Default to a /24 subnet to scan the whole network
        network = ipaddress.IPv4Network(local_ip + '/24', strict=False)
        return str(network)
