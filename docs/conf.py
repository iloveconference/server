"""Sphinx configuration."""

project = "Server"
author = "Dallan Quass"
copyright = "2023, Dallan Quass"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "myst_parser",
]
autodoc_typehints = "description"
html_theme = "furo"
