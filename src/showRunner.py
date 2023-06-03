import importlib
import yaml
import os
import logging
import sys
from dotenv import load_dotenv
import hashlib
import argparse
from jsonschema.exceptions import ValidationError
from json.decoder import JSONDecodeError
import time
from retry import retry
from pickleDict import PickleDict

# load env variables

load_dotenv()  # take environment variables from .env.

# Set up logging
logging.basicConfig(filename='showRunner.log', level=logging.INFO,
                    format='%(asctime)s:%(name)s:%(levelname)s:%(message)s')
logger = logging.getLogger(__name__)

# Define the plugins directory
# Get the absolute path of the directory containing this script
script_dir = os.path.dirname(os.path.abspath(__file__))
plugins_dir = os.path.join(script_dir, 'plugins')
outputs_dir = os.path.join(script_dir, '../outputs')
src_dir = os.path.join(script_dir, '/src')

# Create the output directory if it doesn't exist
if not os.path.exists(outputs_dir):
    os.makedirs(outputs_dir)

sys.path.append(plugins_dir)
sys.path.append(src_dir)

# Global dictionary to store merged results
global_results = {}

# Cache dictionary to store cached plugin results
plugin_cache = PickleDict('cache.pickle', autocommit=True)

def execute_plugin(plugin_class, plugin_params, global_results, plugin_instance_name, retries=1):
    retry_count = 0

    @retry((AssertionError, ValidationError, JSONDecodeError), tries=retries, delay=2)
    def exec():
        nonlocal retry_count
        retry_count += 1
        try:
            plugin_instance = plugin_class(
                plugin_params, global_results, plugin_instance_name)
            plugin_results = plugin_instance.execute()
            return plugin_results
        except Exception as e:
            logger.exception(
                f"Exception while executing plugin '{plugin_instance_name}': {e}")
            if retry_count < retries:
                logger.info(f"Retrying plugin '{plugin_instance_name}'")
                raise e
            raise e
    return exec()


def execute_plugins(yaml_file, clear_cache=False):
    if clear_cache:
        plugin_cache.clear()
        logger.info("Cache cleared.")

    with open(yaml_file) as file:
        data = yaml.load(file, Loader=yaml.Loader)

    # Create unique outputs folder based on show parameter
    show_name = data.get('show_name', 'show')
    global_results = data.get('global_parameters', {})

    # Determine the run count based on previous folder
    last_run_count = get_last_run_count(show_name)
    run_count = last_run_count + 1

    # create the folder, if it doesn't exist
    output_folder = os.path.join(outputs_dir, f"{show_name}_run{run_count}")
    os.makedirs(output_folder, exist_ok=True)
    global_results['output_folder'] = output_folder

    # Execute plugins
    for entry in data.get('plugins', []):
        plugin_name = entry.get('plugin')
        plugin_class = entry.get('class')
        plugin_params = entry.get('params', {})
        name_key = entry.get('name', '')
        cache_plugin = entry.get('cache', False)
        plugin_retries = entry.get('retries', 1)
        if cache_plugin:
            logger.info(
                f"Cache enabled for plugin '{plugin_name}:{name_key}'.")

        # Generate hash of the plugin entry
        entry_hash = hashlib.md5(str(entry).encode()).hexdigest()

        # Check if cache is enabled and entry is in cache
        if cache_plugin and entry_hash in plugin_cache:
            plugin_results = plugin_cache[entry_hash]
            logger.info(
                f"Plugin '{plugin_name}' results retrieved from cache.")
        else:
            # Import the plugin if it exists
            try:
                module = importlib.import_module(f'{plugin_name}')
                plugin_class = getattr(module, plugin_class)
                #plugin_instance = plugin_class()
                logger.info(
                    f"Plugin '{plugin_name}' has been imported successfully.")
            except AttributeError:
                logger.critical(f"Plugin '{plugin_name}' not found.")
                raise
            except ModuleNotFoundError:
                logger.critical(f"Module '{plugin_name}' not found.")
                raise

            plugin_results = execute_plugin(
                plugin_class, plugin_params, global_results, plugin_instance_name=name_key, retries=plugin_retries)
            # if enabled, attempt to execute the plugin until there are no validation or assertion errors
            # retries = 0
            # while retries < plugin_retries:
            #     try:
            #         #plugin_results = plugin_instance.execute(
            #         #    plugin_params, global_results, plugin_instance_name=name_key)
            #         plugin_instance = plugin_class(plugin_params, global_results, plugin_instance_name=name_key)
            #         plugin_results = plugin_instance.execute()
            #         break
            #     except (ValidationError, AssertionError) as e:
            #         if plugin_retries > 1:
            #             logger.error("Caught exception:", str(e))
            #             retries += 1
            #             logger.info(f"Retry {retries} of {plugin_retries}")
            #             time.sleep(1)  # Wait for 1 second before retrying
            #         else:
            #             raise e

            # if retries == plugin_retries:
            #     raise Exception(
            #         f"Exceeded maximum retries of {plugin_retries}. Function failed.")

            logger.info(
                f"Plugin '{plugin_name}' has been executed successfully.")

            # Store results in cache
            if cache_plugin:
                plugin_cache[entry_hash] = plugin_results

        # Prepend plugin's results with name key
        prepended_results = {}
        for key, value in plugin_results.items():
            prepended_key = f'{name_key}_{key}' if name_key else key
            prepended_results[prepended_key] = value

        # Merge prepended results into global results
        global_results.update(prepended_results)

    # dump the full global_results to yaml file in the output folder
    # with open(os.path.join(output_folder, 'global_results.yaml'), 'w') as f:
    #     yaml.dump(global_results, f)


def get_last_run_count(show_name):
    global outputs_dir
    folders = [folder for folder in os.listdir(
        outputs_dir) if os.path.isdir(os.path.join(outputs_dir, folder))]
    matching_folders = [
        folder for folder in folders if folder.startswith(show_name)]
    matching_folders.sort(key=lambda x: int(x.split('_run')[-1]), reverse=True)

    if matching_folders:
        last_folder = matching_folders[0]
        run_count = last_folder.split('_run')[-1]
        try:
            return int(run_count)
        except ValueError:
            pass

    return 0


def parse_arguments():
    parser = argparse.ArgumentParser(description='ShowRunner')
    parser.add_argument('yaml_file', metavar='config.yaml',
                        type=str, help='Path to YAML configuration file')
    parser.add_argument('--clear-cache', dest='clear_cache',
                        action='store_true', help='Clear cache')

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_arguments()

    execute_plugins(args.yaml_file, args.clear_cache)
