#!/bin/bash
unset YT_API_KEY
unset OPENAI_API_KEY
unset FREESOUND_API_KEY
unset PODBEAN_API_KEY
unset PODBEAN_CLIENT_SECRET
unset SUPASET_URL
unset SUPASET_KEY

# create a new venv
python3 -m venv lfh_test_env

# activate the venv
source lfh_test_env/bin/activate

# install the package
pip install .

# discover and run the unit tests
pytest tests/test*.py

# # deactivate the venv
# deactivate

# # optionally, remove the venv
# rm -rf lfh_test_env
