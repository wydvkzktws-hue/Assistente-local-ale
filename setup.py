from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="personal-assistant-cli",
    version="0.1.0",
    author="Assistant",
    author_email="assistant@example.com",
    description="A local personal assistant CLI application with desktop notifications",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/example/personal-assistant",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: News/Diary",
        "Topic :: Utilities"
    ],
    python_requires=">=3.6",
    install_requires=[
        "schedule>=1.2.0",
    ],
    entry_points={
        "console_scripts": [
            "assistant=main:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)