#!/usr/bin/env python3
"""
Setup script for Signal Quality Engine (SQE)
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
if readme_file.exists():
    with open(readme_file, "r", encoding="utf-8") as f:
        long_description = f.read()
else:
    long_description = "Signal Quality Engine for SCADA Simulation Stack"

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, "r") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
else:
    requirements = ["numpy>=1.20.0", "pyyaml>=5.4.0"]

setup(
    name="signal-quality-engine",
    version="1.0.0",
    description="DSP-style signal conditioning and diagnostics for SCADA telemetry",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="SCADA Systems",
    author_email="support@example.com",
    url="https://github.com/yourusername/rtu",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "sqe": ["config/*.yaml"],
    },
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "flake8>=4.0.0",
            "mypy>=0.950",
        ],
        "plot": [
            "matplotlib>=3.5.0",
        ],
        "all": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "matplotlib>=3.5.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "sqe=sqe.cli.sqe_cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    keywords="scada dsp signal-processing telemetry rtu plc",
    project_urls={
        "Documentation": "https://github.com/yourusername/rtu/tree/main/sqe/docs",
        "Source": "https://github.com/yourusername/rtu",
        "Tracker": "https://github.com/yourusername/rtu/issues",
    },
)
