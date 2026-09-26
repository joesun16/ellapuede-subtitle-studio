"""Build the small native frame-comparison helper on the current platform."""
from setuptools import setup,Extension
import os
from version import VERSION
setup(name='ellapuede-glyph-features',version=VERSION,ext_modules=[Extension('glyph_features',['glyph_features.c'],extra_compile_args=['/O2'] if os.name=='nt' else ['-O3'])])
