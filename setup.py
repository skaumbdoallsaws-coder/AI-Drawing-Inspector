"""Setup script for ai_inspector package."""

from setuptools import setup, find_packages

setup(
    name="ai_inspector",
    version="4.0.0",
    description="AI-powered engineering drawing inspection system",
    author="Continental Machines Inc.",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pymupdf>=1.23.0",
        "pillow>=9.0.0",
        "openai>=1.0.0",
    ],
    extras_require={
        "colab": [
            "transformers>=4.40.0",
            "accelerate>=0.25.0",
            "qwen-vl-utils",
            "bitsandbytes",
        ],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov",
        ],
    },
    entry_points={
        "console_scripts": [
            "ai-inspector=ai_inspector.cli:main",
        ],
    },
)
