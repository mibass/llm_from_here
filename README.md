

# LLM From Here

This repository contains code for the LLM From Here project.
The primary goal is to produce an automated podcast generator that can use LLMs to
- produce shows scripts
- produce guest lists
- produce intros

The realization this script into audio is achieved through the main script, named "ShowRunner", which is a dynamic plugin execution system designed to execute a series of plugin scripts defined in a YAML configuration file. The configuration file should contain the name of the show, global parameters, and a list of plugin specifications. Each plugin is executed in order and its results are stored in a global dictionary. To optimize performance, plugin results can be cached in a SQLite database and reloaded in subsequent runs if their specifications haven't changed, unless the cache is explicitly cleared. The plugin execution can be retried in case of validation or assertion errors. The system manages logging of activities and errors, and organizes outputs in unique folders named after the show and run count. Finally, the merged global results from all plugins are dumped into a YAML file in the output folder.


## Getting Started

These instructions will help you set up the project environment using Conda.

### Prerequisites

- Python 3.10
- pip

### Setup

1. Clone the repository:

    ```
    git clone https://github.com/mibass/llm_from_here.git
    ```
1. Change into the project directory:
    ```
    cd llm_from_here
    ```
1. Create a virtual environment (optional but recommended):
    ```
    python -m venv venv
    ```

1. Activate the newly created environment:
    ```
    source venv/bin/activate
    ```
    (Replace `venv` with the name of the environment)

1. Install the project dependencies:
    ```
    pip install -r requirements.txt
    ```

### Configuration

*.env*

This project uses dotenv to set environment variables. Keys are needed for:
* google v3 youtube api `YT_API_KEY`
* freesound api `FREESOUND_API_KEY`
* openai `OPENAI_API_KEY`

### Usage

To run the script, execute the following command:

```python script_name.py config.yaml [--clear-cache]```

Optional flag:

    --clear-cache: Use this flag to clear the plugin cache before execution.

Make sure to provide the path to your YAML configuration file. The script will execute plugins defined in the YAML file, store results in the output folder, and log the execution details.


