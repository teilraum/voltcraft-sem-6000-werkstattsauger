import subprocess
import json
import threading
import time
import logging
import sys

# Define the command to execute
status_command = "./sem-6000.exp B3:00:00:00:0E:B3 0000 --sync --status --json"
action_command_on = "./sem-6000.exp B3:00:00:00:20:D4 0000 --sync --on"
action_command_off = "./sem-6000.exp B3:00:00:00:20:D4 0000 --sync --off"

# Define the threshold for watts
WATTS_THRESHOLD = 4.0  # Adjusted to 1 watt

# Maximum number of retries for turning on/off
MAX_RETRIES = 3
RETRY_DELAY = 0.1  # Reduced delay to make retries happen quickly

# Shared variable to store the latest watts value
current_watts = None
watts_lock = threading.Lock()  # Lock to protect the shared variable

# Set up logging
def setup_logging(verbosity):
    log_level = logging.WARNING
    if verbosity >= 1:
        log_level = logging.INFO
    if verbosity >= 2:
        log_level = logging.DEBUG

    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

# Parse verbosity from command line arguments (default to 0)
verbosity = 0
if len(sys.argv) > 1 and sys.argv[1] == '-v':
    verbosity = 1
if len(sys.argv) > 2 and sys.argv[2] == '-v':
    verbosity = 2

setup_logging(verbosity)

def run_command_with_retry(command):
    """ Run a command with retries in case of failure. """
    for attempt in range(MAX_RETRIES):
        try:
            logging.debug(f"Attempting to run command: {command}")
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            
            # Check for errors in the command execution
            if result.returncode != 0:
                logging.debug(f"ERROR: Command failed (Attempt {attempt + 1}/{MAX_RETRIES})")
            else:
                # Successfully executed command
                logging.debug(f"Command succeeded: {command}")
                return True
        except Exception as e:
            logging.debug(f"ERROR: An exception occurred while running the command: {e}")

        # Wait before retrying
        time.sleep(RETRY_DELAY)
    
    # If we exhaust all retries, return False
    logging.debug(f"ERROR: Command failed after {MAX_RETRIES} attempts.")
    return False

def poll_watts():
    """ Poll the status command as fast as possible to get the latest watts value. """
    global current_watts
    global poll_timestemp
    while True:
        logging.debug("Polling watts...")  # Debug statement to track polling
        try:
            # Use subprocess.Popen to prevent blocking
            process = subprocess.Popen(status_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(timeout=2)  # Timeout to avoid hanging indefinitely

            if process.returncode != 0:
                logging.debug(f"ERROR: Connection failed with error: {stderr}")
            else:
                # Try to parse the JSON output
                try:
                    data = json.loads(stdout)
                    
                    # Extract the watts value from the JSON
                    watts = data.get("status", {}).get("watts", None)
                    
                    if watts is not None:
                        # Update the current watts value in a thread-safe manner
                        with watts_lock:
                            old_watts = current_watts
                            current_watts = watts
                            if (watts > WATTS_THRESHOLD) != (old_watts > WATTS_THRESHOLD):
                                poll_timestemp = time.time()
                        logging.info(f"Received watts: {watts}")
                    else:
                        logging.debug("ERROR: 'watts' value not found in the response.")

                except json.JSONDecodeError:
                    logging.debug("ERROR: Failed to parse JSON")

        except subprocess.TimeoutExpired:
            logging.debug("ERROR: The command timed out. Retrying...")
        except Exception as e:
            logging.debug(f"ERROR: An error occurred while polling watts: {e}")
        
        time.sleep(0.001)  # Ensure the loop continues

def execute_action_commands():
    """ Continuously execute action commands based on the watts value. """
    switch_state = False
    while True:
        with watts_lock:
            if current_watts is None:
                logging.debug("Current watts is None, skipping action.")  # Debugging
                continue  # Skip if watts value is not yet available

            # Compare watts with the threshold
            if (current_watts > WATTS_THRESHOLD) == switch_state:
                continue
            else:
                logging.info(f"Consumer state changed.")
                if current_watts > WATTS_THRESHOLD:
                    logging.debug(f"Watts {current_watts} is greater than threshold, attempting to turn on.")
                    # Run the command to turn on with retry logic
                    if run_command_with_retry(action_command_on):
                        logging.info("Successfully turned on.")
                        switch_state = True
                    else:
                        logging.debug("Failed to turn on after retries.")
                else:
                    logging.debug(f"Watts {current_watts} is less than or equal to threshold, attempting to turn off.")
                    # Run the command to turn off with retry logic
                    if run_command_with_retry(action_command_off):
                        logging.info("Successfully turned off.")
                        switch_state = False
                    else:
                        logging.debug("Failed to turn off after retries.")
                if poll_timestemp is not None:
                    logging.info(f"Took {time.time() - poll_timestemp} seconds.")
        time.sleep(0.001)

# Create and start threads
polling_thread = threading.Thread(target=poll_watts)
action_thread = threading.Thread(target=execute_action_commands)

# Start threads
polling_thread.start()
action_thread.start()

# Keep the main thread alive while background threads do the work
try:
    while True:
        time.sleep(0.1)  # Keep the main thread running without blocking
except KeyboardInterrupt:
    logging.debug("Polling and action threads terminated.")
