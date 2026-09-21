#!/usr/bin/env python3
"""Resolve one joint device's explicitly selected URDF chain."""
import argparse
import json
import sys
from kinex.urdf import read_chain

parser = argparse.ArgumentParser()
parser.add_argument("--urdf", required=True)
parser.add_argument("--base-link", required=True)
parser.add_argument("--tip-link", required=True)
parser.add_argument("--stdin", action="store_true")
args = parser.parse_args()
print(json.dumps(read_chain(args.urdf, args.base_link, args.tip_link, sys.stdin.read() if args.stdin else None), allow_nan=False))
