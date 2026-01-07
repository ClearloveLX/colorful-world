#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test if program can start normally"""

import sys

print("=" * 50)
print("Checking dependencies...")
print("=" * 50)

errors = []

# Check basic packages
try:
    import tkinter
    print("OK - tkinter")
except ImportError:
    errors.append("tkinter not installed")
    print("FAIL - tkinter not installed")

try:
    import cv2
    print("OK - opencv-python")
except ImportError:
    errors.append("opencv-python not installed")
    print("FAIL - opencv-python not installed")

try:
    import numpy
    print("OK - numpy")
except ImportError:
    errors.append("numpy not installed")
    print("FAIL - numpy not installed")

try:
    import PIL
    print("OK - Pillow")
except ImportError:
    errors.append("Pillow not installed")
    print("FAIL - Pillow not installed")

 

 

print("\n" + "=" * 50)
print("Checking module imports...")
print("=" * 50)

 

 

try:
    from file_manager import FileManager
    print("OK - file_manager")
except Exception as e:
    errors.append(f"file_manager import failed: {e}")
    print(f"FAIL - file_manager: {e}")

print("\n" + "=" * 50)
if errors:
    print("Found issues:")
    for error in errors:
        print(f"  - {error}")
    print("\nPlease run: pip install -r requirements.txt")
    print("Or run: install_dependencies.bat")
    sys.exit(1)
else:
    print("All checks passed! Program should start normally.")
    print("\nYou can run: python main.py")
    print("Or double-click: run.bat")
print("=" * 50)




