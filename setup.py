from setuptools import setup

setup(
    name="git-doctor",
    version="1.0.0",
    py_modules=["git_doctor"],
    entry_points={
        "console_scripts": [
            "git-doctor=git_doctor:main",
        ],
    },
)
