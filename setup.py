from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="pinterest-scraper",
    version="2.0.0",
    description="High-performance Pinterest content scraper",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Pinterest Scraper Team",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.100.0",
        "uvicorn>=0.22.0",
        "requests>=2.31.0",
        "pydantic>=2.0.0",
        "openpyxl>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "pinterest-scraper=cli.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
