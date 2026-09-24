import os
import sys

# Tests import the gateway modules by their top-level names (gateway.py runs from its own dir).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
