import importlib
import yaml
import yamlinclude
import os
import logging
from dotenv import load_dotenv
import hashlib
import argparse
from jsonschema.exceptions import ValidationError
from json.decoder import JSONDecodeError
from retry import retry
from llm_from_here.pickleDict import PickleDict
import appdirs
import llm_from_here.plugins as plugins
from llm_from_here.common import is_production

# load env variables
load_dotenv()  # take environment variables from .env.

# Set up logging
logging.basicConfig(filename='showRunner.log', level=logging.INFO,
                    format='%(asctime)s:%(name)s:%(levelname)s:%(message)s')
logger = logging.getLogger(__name__)

# Global dictionary to store merged results
global_results = {}

# Cache dictionary to store cached plugin results
cache_dir = appdirs.user_cache_dir(appname=os.path.basename(__file__))
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
plugin_cache = PickleDict(os.path.join(cache_dir , 'cache.pickle'), autocommit=True)

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

def load_yaml(yaml_file):
    base_dir = os.path.dirname(yaml_file)
    yamlinclude.YamlIncludeConstructor.add_to_loader_class(loader_class=yaml.FullLoader, 
                                                           base_dir=base_dir)
    with open(yaml_file) as file:
        data = yaml.load(file, Loader=yaml.FullLoader)
    return data

def execute_plugins(yaml_file, clear_cache=False, outputs_dir=None):
    global global_results
    if clear_cache:
        plugin_cache.clear()
        logger.info("Cache cleared.")

    data = load_yaml(yaml_file)

    # Create unique outputs folder based on show parameter
    show_name = data.get('show_name', 'show')
    global_results = data.get('global_parameters', {})

    # Determine the run count based on previous folder
    last_run_count = get_last_run_count(show_name, outputs_dir)
    run_count = last_run_count + 1

    # create the folder, if it doesn't exist
    output_folder = os.path.join(outputs_dir, f"{show_name}_run{run_count}")
    os.makedirs(output_folder, exist_ok=True)
    global_results['output_folder'] = output_folder
    
    # list of objects that need to be finalized at the end of a successful run
    to_be_finalized = []

    # Execute plugins
    for entry in data.get('plugins', []):
        plugin_name = entry.get('plugin')
        plugin_class = entry.get('class')
        plugin_params = entry.get('params', {})
        name_key = entry.get('name', '')
        cache_plugin = entry.get('cache', False)
        plugin_retries = entry.get('retries', 1)
        only_in_prod = entry.get('only_in_prod', False)
        
        if plugin_retries > 1:
            logger.info(
                f"Retries enabled for plugin '{plugin_name}:{name_key}'.")
        if cache_plugin:
            logger.info(
                f"Cache enabled for plugin '{plugin_name}:{name_key}'.")
        if only_in_prod and not is_production():
            logger.info(
                f"Skipping plugin '{plugin_name}:{name_key}' because it is only enabled in production.")
            continue

        # Generate hash of the plugin entry
        entry_hash = hashlib.md5(str(entry).encode()).hexdigest()

        # Check if cache is enabled and entry is in cache
        from_cache = False
        if cache_plugin and entry_hash in plugin_cache:
            from_cache = True
            plugin_results = plugin_cache[entry_hash]
            logger.info(
                f"Plugin '{plugin_name}' results retrieved from cache.")
        else:
            # Import the plugin if it exists
            try:
                module = importlib.import_module(f'llm_from_here.plugins.{plugin_name}')
                plugin_class = getattr(module, plugin_class)
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
            
            # If the plugin has a finalize method, add it to the list of objects to be finalized
            if not from_cache and hasattr(value, 'finalize'):
                to_be_finalized.append(value)
            
        logger.info(f"Plugin '{plugin_name}' results: {prepended_results}")

        # Merge prepended results into global results
        global_results.update(prepended_results)
        
    #finalize
    for obj in to_be_finalized:
        obj.finalize()

def get_last_run_count(show_name, outputs_dir):
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
    parser.add_argument('--output-dir', dest='outputs_dir',
                        type=str, help='Output folder')

    args = parser.parse_args()
    return args

def create_outputs_dir(args):
    #ensure outputs_dir is set, create it if it doesn't exist
    if not args.outputs_dir:
        #set to current directory with "outputs" appended
        outputs_dir = os.path.join(os.getcwd(), "outputs")
    else:
        outputs_dir = args.outputs_dir
        
    try:
        if not os.path.exists(outputs_dir):
            os.makedirs(outputs_dir)
    except Exception as e:
        logger.error(f"Error creating outputs directory: {e}")
        raise e
    
    return outputs_dir

if __name__ == "__main__":
    args = parse_arguments()
    
    outputs_dir = create_outputs_dir(args)
        
    execute_plugins(args.yaml_file, args.clear_cache, outputs_dir)
    
    logger.info(f"Global results keys at end of run: {global_results.keys()}")
    logger.info("ShowRunner completed successfully.")
