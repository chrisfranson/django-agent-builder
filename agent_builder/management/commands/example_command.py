"""
Example management command for agent_builder.

Usage:
    python manage.py example_command [options]
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser


class Command(BaseCommand):
    """Example management command with modern patterns."""

    help = "Example management command for agent_builder"

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Add command-line arguments.

        Args:
            parser: The argument parser
        """
        parser.add_argument(
            "--example-arg",
            type=str,
            help="Example string argument",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Enable verbose output",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """
        Execute the command.

        Args:
            *args: Positional arguments
            **options: Command options
        """
        verbose = options.get("verbose", False)
        example_arg = options.get("example_arg")

        if verbose:
            self.stdout.write(self.style.SUCCESS("Starting agent_builder example command..."))

        # Your command logic here
        if example_arg:
            self.stdout.write(f"Received argument: {example_arg}")

        # Example: Process some data
        self.process_data(verbose=verbose)

        if verbose:
            self.stdout.write(self.style.SUCCESS("Command completed successfully!"))

    def process_data(self, verbose: bool = False) -> None:
        """
        Example method to process data.

        Args:
            verbose: Whether to print verbose output
        """
        # Add your processing logic here
        if verbose:
            self.stdout.write("Processing data...")
