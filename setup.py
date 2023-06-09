from setuptools import setup, find_packages

with open("src/llm_from_here/__init__.py") as f:
    version_line = next(line for line in f if line.startswith("__version__"))
    version = version_line.split("=")[-1].strip().strip("'\"")
    
setup(
    name='llm_from_here',
    version=version,
    description='A project for generating podcasts with LLMs',
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={
        'llm_from_here': ['resources/*'],
    },
    install_requires=[
        'gTTS',
        'pydub',
        'google_auth_oauthlib',
        'google-api-python-client',
        'openai',
        'jsonschema',
        'sqlitedict',
        'isodate',
        'pathvalidate',
        'fuzzywuzzy',
        'python-Levenshtein',
        'python-dotenv',
        'feedparser',
        'retry',
        'supabase',
        'youtube-dl',
        'pyyaml',
        'appdirs',
        'numpy',
        'scipy',
        'jinja2',
        'scikit-learn',
        'librosa',
        'plotly',
        'matplotlib',
        'pandas',
        'freesound-python @ git+https://github.com/MTG/freesound-python.git#egg=freesound',
        'pyyaml-include',
        'pytest'
    ],
    python_requires=">=3.10"
)