#!/usr/bin/env bash

set -eu
set -o pipefail


cd "$(dirname "$0")" || exit 1

PYTHONPATH="$PWD/pool" mypy --ignore-missing-imports -- pool/*.py pool/**/*.py

mypy --ignore-missing-imports -- rplugin/python3/fast_comp/*.py
