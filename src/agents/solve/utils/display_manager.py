"""
Display Manager - Terminal display manager
Uses rich library to implement beautiful terminal interface, including fixed header (status/statistics) and scrolling log area
"""

from datetime import datetime
import sys
from typing import Any

try:
    from rich import box
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.logging import RichHandler
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class DisplayManager:
    """
    Terminal display manager

    If rich is available, use TUI interface:
    - Top: Agent status checklist + Token/Cost statistics
    - Bottom: Scrolling logs

    If rich is not available, fall back to standard stdout output
    """

    def __init__(self):
        self.rich_available = RICH_AVAILABLE

        self.agents_status = {
            "InvestigateAgent": "pending",
            "NoteAgent": "pending",
            "ManagerAgent": "pending",
            "SolveAgent": "pending",
            "ToolAgent": "pending",
            "ResponseAgent": "pending",
            "PrecisionAnswerAgent": "pending",
        }

        self.stats = {
            "model": "Unknown",
            "calls": 0,
            "tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
        }

        # Log buffer
        self.log_buffer = []
        self.max_log_lines = 20

        # Early return if rich not available (but after initializing core attributes)
        if not self.rich_available:
            self.console = None
            self.layout = None
            self.live = None
            return

        # Explicitly use raw stdout, bypass logger redirection
        self.console = Console(file=sys.__stdout__)

        # Layout
        self.layout = self._make_layout()

        # Live update context
        self.live = None

    def start(self):
        """Start Live Display"""
        if self.rich_available and self.live is None:
            self.live = Live(
                self.layout,
                refresh_per_second=4,
                console=self.console,
                transient=True,  # Remove interface on exit to avoid blocking subsequent input
            )
            self.live.start()

    def stop(self):
        """Stop Live Display"""
        if self.rich_available and self.live:
            self.live.stop()
            self.live = None

    def _make_layout(self) -> "Layout":
        """Create layout"""
        layout = Layout()

        # Split into upper part (fixed info) and lower part (logs)
        layout.split_column(Layout(name="header", size=10), Layout(name="body"))

        # Split upper part into left (Agents) and right (Stats)
        layout["header"].split_row(Layout(name="agents", ratio=1), Layout(name="stats", ratio=2))

        return layout

    def update(self):
        """Update interface content"""
        if not self.rich_available:
            return

        # Update Agents status panel
        agents_table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        agents_table.add_column("Status", width=2)
        agents_table.add_column("Name")

        for name, status in self.agents_status.items():
            if status == "done":
                icon = "✓"
                style = "green"
            elif status == "running":
                icon = "…"
                style = "yellow"
            elif status == "error":
                icon = "✗"
                style = "red"
            else:
                icon = " "
                style = "dim"

            agents_table.add_row(Text(icon, style=style), Text(name, style=style))

        self.layout["agents"].update(
            Panel(
                agents_table,
                title="📦 Agents Status",
                border_style="blue",
                padding=(0, 1),  # Increase panel padding
            )
        )

        # Update statistics panel
        stats_content = (
            f"[bold]{self.stats['model']}[/bold]\n"
            f"Calls: {self.stats['calls']}\n"
            f"Tokens: {self.stats['tokens']:,} "
            f"(Input: {self.stats['input_tokens']:,}, Output: {self.stats['output_tokens']:,})\n"
            f"[bold yellow]Cost: ${self.stats['cost']:.6f} USD[/bold yellow]"
        )

        self.layout["stats"].update(
            Panel(
                stats_content,
                title="📊 Performance & Cost",
                border_style="green",
                padding=(0, 1),  # Increase panel padding
            )
        )

        # Update log panel
        log_text = "\n".join(self.log_buffer[-self.max_log_lines :])
        self.layout["body"].update(
            Panel(
                log_text,
                title="📝 Activity Log",
                border_style="white",
                padding=(0, 1),  # Increase panel padding
            )
        )

    def set_agent_status(self, agent_name: str, status: str):
        """Set Agent status (pending, running, done, error)"""
        self.agents_status[agent_name] = status
        self.update()

    def update_token_stats(self, summary: dict[str, Any]):
        """Update Token statistics"""
        self.stats["calls"] = summary.get("total_calls", 0)
        self.stats["tokens"] = summary.get("total_tokens", 0)
        self.stats["input_tokens"] = summary.get("total_prompt_tokens", 0)
        self.stats["output_tokens"] = summary.get("total_completion_tokens", 0)
        self.stats["cost"] = summary.get("total_cost_usd", 0.0)

        # Try to get the main model used
        by_model = summary.get("by_model", {})
        if by_model:
            # Find the most called model
            top_model = max(by_model.items(), key=lambda x: x[1]["calls"])[0]
            self.stats["model"] = top_model

        self.update()

    def log(self, message: str):
        """Add log"""
        if not self.rich_available:
            print(message)
            return

        # Simple cleaning
        clean_msg = message.rstrip()
        if not clean_msg:
            return

        # Add timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {clean_msg}"

        self.log_buffer.append(formatted_msg)
        # Maintain buffer size
        if len(self.log_buffer) > 100:
            self.log_buffer = self.log_buffer[-50:]

        self.update()


# Global instance
_display_manager = None


def get_display_manager() -> DisplayManager:
    global _display_manager
    if _display_manager is None:
        _display_manager = DisplayManager()
    return _display_manager
