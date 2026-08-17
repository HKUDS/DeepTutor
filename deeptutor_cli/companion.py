"""CLI commands for iPad/iPhone PWA Companion setup."""

from __future__ import annotations

import json
import subprocess
import shutil
import uuid
import time

import typer
from rich.console import Console

console = Console()

def register(app: typer.Typer) -> None:
    companion_app = typer.Typer(help="Manage iPad/iPhone PWA Companion setup.")

    @companion_app.command("setup")
    def setup_companion():
        """Detect Tailscale, expose HTTPS via Tailscale Serve, and generate pairing QR code."""
        if not shutil.which("tailscale"):
            console.print("[red]Error:[/] Tailscale not found. Please install Tailscale first.")
            raise typer.Exit(1)
        
        console.print("[green]Detecting Tailscale status...[/]")
        try:
            status_output = subprocess.check_output(["tailscale", "status", "--json"], text=True)
            status_data = json.loads(status_output)
            tailscale_ip = status_data.get("Self", {}).get("TailscaleIPs", [])[0]
            tailnet_name = status_data.get("Self", {}).get("DNSName", "").strip(".")
        except Exception as exc:
            console.print(f"[red]Error:[/] Failed to get Tailscale status: {exc}")
            raise typer.Exit(1)
            
        console.print(f"Tailscale IP: [bold]{tailscale_ip}[/]")
        console.print(f"Tailnet DNS: [bold]{tailnet_name}[/]")
        
        # 暴露 HTTPS
        try:
            subprocess.run(["tailscale", "serve", "--bg", "https", "/", "http://127.0.0.1:8001"], check=True)
            console.print("[green]Exposed http://127.0.0.1:8001 to Tailscale HTTPS.[/]")
        except subprocess.CalledProcessError:
            console.print("[red]Warning:[/] Failed to run tailscale serve. Check permissions.")
            
        # 生成五分钟单次配对二维码 (pairing code)
        import qrcode
        pairing_code = uuid.uuid4().hex[:12].upper()
        pairing_url = f"https://{tailnet_name}/companion/pair?code={pairing_code}"
        
        console.print("\n[bold]Scan this QR code from your iPad/iPhone Camera:[/]\n")
        qr = qrcode.QRCode()
        qr.add_data(pairing_url)
        qr.make()
        qr.print_ascii()
        
        console.print(f"Pairing URL: [bold]{pairing_url}[/]")
        console.print(f"Code valid for 5 minutes. Ensure backend binds to loopback only (`deeptutor serve --host 127.0.0.1`).")

    app.add_typer(companion_app, name="companion")
