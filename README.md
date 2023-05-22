

# LLM From Here [repo is WIP]

This repository contains code for the LLM From Here project.
The primary goal is to produce an automated podcast generator that can use LLMs to
- produce shows scripts
- produce guest lists
- produce intros

The realization this script into audio is achieved through the main script, named "ShowRunner", which is a dynamic plugin execution system designed to execute a series of plugin scripts defined in a YAML configuration file. The configuration file should contain the name of the show, global parameters, and a list of plugin specifications. Each plugin is executed in order and its results are stored in a global dictionary. To optimize performance, plugin results can be cached in a SQLite database and reloaded in subsequent runs if their specifications haven't changed, unless the cache is explicitly cleared. The plugin execution can be retried in case of validation or assertion errors. The system manages logging of activities and errors, and organizes outputs in unique folders named after the show and run count. Finally, the merged global results from all plugins are dumped into a YAML file in the output folder.


## Getting Started

These instructions will help you set up the project environment using Conda.

### Prerequisites

- [Anaconda](https://www.anaconda.com/) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html) should be installed on your system.

### Setup

1. Clone the repository:

    ```
    git clone https://github.com/mibass/llm_from_here.git
    ```
1. Change into the project directory:
    ```
    cd llm_from_here
    ```
1. Create a new Conda environment from the provided YAML file:
    ```
    conda env create -f environment.yml
    ```
    This will create a new environment with the required dependencies specified in environment.yml.

1. Activate the newly created environment:

    ```
    conda activate environment-name
    ```
    Replace environment-name with the name of the environment specified in environment.yml.

1. Start using the project!

### Configuration

*.env*

This project uses dotenv to set environment variables. Keys are needed for:
* google v3 youtube api `YT_API_KEY`
* freesound api `FREESOUND_API_KEY`
* openai `OPENAI_API_KEY`


### TODO

*Bugs:*
* mismatched intros to segments

*showrunner:*
* add YAML schema validation


*Audio:*
* Add continuous audience background noise
* Improve applause overlaps and tail
* Investigate aubio for onset detection and detecting music starts: https://github.com/aubio/aubio/tree/master/python/demos
* Investigate compression in pydub
* in the intro, after the spoken intro is done, ramp the gain of the background music back up
* add room tone (e.g. audience in theater like this one https://www.youtube.com/watch?v=7Yyy-coFMGc)

*TTS:*
* reduce uhhs in bark
* optimize bark parameters


*Segment ideas:*
* story
* interview
* improv scene
* outro

*prompts:*


*YT search*:
* for search, add support for topicId filters https://developers.google.com/youtube/v3/docs/search/list#topicId
* add sorting by rating or viewCount https://developers.google.com/youtube/v3/docs/search/list#order
* add support for videoDuration filters: https://developers.google.com/youtube/v3/docs/search/list#videoDuration


