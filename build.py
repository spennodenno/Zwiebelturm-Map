"""Build the map data:  python build.py   (see README.md for options)"""
import sys

if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required.")

from pipeline.run import main

sys.exit(main())
