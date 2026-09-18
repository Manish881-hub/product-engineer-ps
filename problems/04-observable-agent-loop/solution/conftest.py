"""Make `solution/` importable as the reviewer runs pytest from here."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
