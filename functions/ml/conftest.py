"""Lets every test under functions/ml import ecoguard_ml, the package tagging
and search_by_file share (ecoguard_common comes from pytest.ini)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
