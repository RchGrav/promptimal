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
    description="Refine and behaviorally verify prompts across OpenRouter models",
    url="https://github.com/RchGrav/promptimal",
    author="shobrook",
    author_email="shobrookj@gmail.com",
    keywords="prompt optimizer openrouter prompt-tuning prompt-engineering prompt-optimization genetic-algorithms",
    include_package_data=True,
    package_data={"promptimal.sheet": ["prompt-sheet.schema.json"]},
    packages=find_packages(),
    entry_points={"console_scripts": ["promptimal = promptimal.promptimal:main"]},
    install_requires=["json-repair", "jsonschema>=4.18", "pyperclip", "openai", "urwid"],
    python_requires=">=3.8",
    license="MIT",
)
