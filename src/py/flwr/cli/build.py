# Copyright 2024 Flower Labs GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Flower command line interface `build` command."""

import os
import zipfile
from pathlib import Path
from typing import Optional

import pathspec
import tomli_w
import typer
from typing_extensions import Annotated

from .config_utils import load_and_validate
from .utils import get_sha256_hash, is_valid_project_name


# pylint: disable=too-many-locals
def build(
    directory: Annotated[
        Optional[Path],
        typer.Option(help="Path of the Flower project to bundle into a FAB"),
    ] = None,
) -> str:
    """Build a Flower project into a Flower App Bundle (FAB).

    You can run ``flwr build`` without any arguments to bundle the current directory,
    or you can use ``--directory`` to build a specific directory:
    ``flwr build --directory ./projects/flower-hello-world``.
    """
    if directory is None:
        directory = Path.cwd()

    directory = directory.resolve()
    if not directory.is_dir():
        typer.secho(
            f"❌ The path {directory} is not a valid directory.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    if not is_valid_project_name(directory.name):
        typer.secho(
            f"❌ The project name {directory.name} is invalid, "
            "a valid project name must start with a letter or an underscore, "
            "and can only contain letters, digits, and underscores.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    conf, errors, warnings = load_and_validate(directory / "pyproject.toml")
    if conf is None:
        typer.secho(
            "Project configuration could not be loaded.\npyproject.toml is invalid:\n"
            + "\n".join([f"- {line}" for line in errors]),
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)

    if warnings:
        typer.secho(
            "Project configuration is missing the following "
            "recommended properties:\n" + "\n".join([f"- {line}" for line in warnings]),
            fg=typer.colors.RED,
            bold=True,
        )

    # Load .gitignore rules if present
    ignore_spec = _load_gitignore(directory)

    # Set the name of the zip file
    fab_filename = (
        f"{conf['tool']['flwr']['app']['publisher']}"
        f".{directory.name}"
        f".{conf['project']['version'].replace('.', '-')}.fab"
    )
    list_file_content = ""

    allowed_extensions = {".py", ".toml", ".md"}

    # Remove the 'federations' field from 'tool.flwr' if it exists
    if (
        "tool" in conf
        and "flwr" in conf["tool"]
        and "federations" in conf["tool"]["flwr"]
    ):
        del conf["tool"]["flwr"]["federations"]

    toml_contents = tomli_w.dumps(conf)

    with zipfile.ZipFile(fab_filename, "w", zipfile.ZIP_DEFLATED) as fab_file:
        fab_file.writestr("pyproject.toml", toml_contents)

        # Continue with adding other files
        for root, _, files in os.walk(directory, topdown=True):
            files = [
                f
                for f in files
                if not ignore_spec.match_file(Path(root) / f)
                and f != fab_filename
                and Path(f).suffix in allowed_extensions
                and f != "pyproject.toml"  # Exclude the original pyproject.toml
            ]

            for file in files:
                file_path = Path(root) / file
                archive_path = file_path.relative_to(directory)
                fab_file.write(file_path, archive_path)

                # Calculate file info
                sha256_hash = get_sha256_hash(file_path)
                file_size_bits = os.path.getsize(file_path) * 8  # size in bits
                list_file_content += f"{archive_path},{sha256_hash},{file_size_bits}\n"

        # Add CONTENT and CONTENT.jwt to the zip file
        fab_file.writestr(".info/CONTENT", list_file_content)

    typer.secho(
        f"🎊 Successfully built {fab_filename}", fg=typer.colors.GREEN, bold=True
    )

    return fab_filename


def _load_gitignore(directory: Path) -> pathspec.PathSpec:
    """Load and parse .gitignore file, returning a pathspec."""
    gitignore_path = directory / ".gitignore"
    patterns = ["__pycache__/"]  # Default pattern
    if gitignore_path.exists():
        with open(gitignore_path, encoding="UTF-8") as file:
            patterns.extend(file.readlines())
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
