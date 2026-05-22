# Installation

qpubench's only mandatory runtime dependency is `pydantic>=2.0`. All quantum backends are optional.

---

## pip

```sh
# Editable local install (development)
pip install -e .

# Specific extras
pip install -e ".[qiskit]"     # Qiskit Aer + IBM Quantum Runtime V2 + qiskit-nature
pip install -e ".[qrack]"      # PyQrack GPU/CPU simulator
pip install -e ".[storage]"    # Parquet store (pyarrow + pandas)
pip install -e ".[all]"        # all PyPI-available extras

# From PyPI (once published)
pip install qpubench
pip install "qpubench[qiskit,storage]"
```

---

## uv

uv reads `pyproject.toml` natively — no extra configuration needed.

```sh
# Sync the environment (installs package + dev dependency group)
uv sync

# Include optional extras
uv sync --all-extras

# Bare pip-style install (no lockfile)
uv pip install .
uv pip install ".[qiskit,storage]"

# Add qpubench as a dependency inside another project
uv add qpubench
uv add "qpubench[qiskit]"

# Generate a lockfile for reproducible installs
uv lock
uv sync          # installs from lock
```

The `[tool.uv]` section in `pyproject.toml` declares dev tools (pytest, ruff, mypy) as `dev-dependencies`; `uv sync` includes them automatically.

---

## Poetry 2

Poetry 2+ reads the standard `[project]` table directly — no `[tool.poetry]` section required.

```sh
# Install from the local directory (development)
poetry install
poetry install --all-extras

# Add qpubench as a dependency inside another project
poetry add qpubench
poetry add "qpubench[qiskit]"
poetry add --group dev qpubench   # as a dev dependency

# Build a distributable wheel
poetry build
```

> **Poetry 1.x is not supported.** The build backend is `hatchling`, which requires Poetry 2.  
> Upgrade with `pip install --upgrade poetry`.

---

## conda

### Option 1 — development environment (recommended)

Creates a named conda environment with Python 3.12, pydantic from conda-forge, and the package installed in editable mode via pip.

```sh
conda env create -f environment.yml
conda activate qpubench
```

To update after pulling changes:

```sh
conda env update -f environment.yml --prune
```

To add optional quantum backends after activation:

```sh
# Qiskit stack (conda-forge build)
conda install -c conda-forge qiskit qiskit-aer

# Storage extras
conda install -c conda-forge pyarrow pandas

# PyPI-only packages
pip install pyqrack
pip install qiskit-ibm-runtime "qiskit-nature>=0.7"
```

CUDA-Q must be installed per [NVIDIA's instructions](https://nvidia.github.io/cuda-quantum/).

### Option 2 — conda-build package

Builds a relocatable `noarch: python` conda package from the `conda-recipe/` directory.

```sh
conda install conda-build         # one-time setup
conda build conda-recipe/
conda install --use-local qpubench
```

The built package depends only on `python>=3.11` and `pydantic>=2.0` (from conda-forge). Install quantum backends separately after activation (see Option 1 above).

---

## Credentials

Copy `.env.example` to `.env` in the project root and fill in your tokens:

```sh
cp .env.example .env
```

```ini
# IBM Quantum
ibm_channel="ibm_quantum"
ibm_api_token="YOUR_TOKEN"
ibm_instance="ibm-q/open/main"

# IQM
iqm_api_token="YOUR_TOKEN"
iqm_server_url="https://cocos.resonance.meetiqm.com/your-device"

# Qibo cloud
qibo_api_token="YOUR_TOKEN"
qibo_platform="YOUR_PLATFORM"

# Cebule (MQS SDK)
EMAIL="your@email.com"
PASSWORD="your_password"

# Qrack precision: 5 = float32, 6 = float64
QRACK_FPPOW="6"
```

---

## Python version support

| Python | Status |
|--------|--------|
| 3.13 | Supported |
| 3.12 | Supported (recommended) |
| 3.11 | Supported (minimum) |
| ≤ 3.10 | Not supported (`match` statements, PEP 604 `X \| Y` annotations) |
