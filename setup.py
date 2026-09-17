from setuptools import setup, find_packages

setup(
    name="blockchain-experiment-distributed",
    version="0.1.0",
    description="Experimental distributed post-quantum blockchain with 3-node PoA consensus",
    packages=find_packages(),
    python_requires=">=3.12,<3.13",
)
