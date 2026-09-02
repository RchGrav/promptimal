try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup
from codecs import open
import sys

if sys.version_info[:3] < (3, 0, 0):
    sys.stdout.write("Requires Python 3 to run.")
    sys.exit(1)

with open("README.md", encoding="utf-8") as file:
    readme = file.read()

setup(
    name="promptimal",
    version="2.0.0",
    description="Optimize your prompts in the terminal",
    url="https://github.com/shobrook/promptimal",
    author="shobrook",
    author_email="shobrookj@gmail.com",
    keywords="prompt optimizer openrouter prompt-tuning prompt-engineering prompt-optimization genetic-algorithms",
    include_package_data=True,
    packages=find_packages(),
    entry_points={"console_scripts": ["promptimal = promptimal.promptimal:main"]},
    install_requires=["json-repair", "pyperclip", "openai", "urwid"],
    python_requires=">=3",
    license="MIT",
)
