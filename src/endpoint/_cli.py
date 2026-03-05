"""TBA"""
import subprocess
import inspect
import shutil
import sys
import os

try:
    from argumint import Interface
except ImportError:
    print("Please install the dev dependencies before using this command.")
    sys.exit(1)


def _change_working_dir_to_script_location():  # Duplicate code
    try:
        if getattr(sys, "frozen", False):
            # If the script is running as a bundled executable created by PyInstaller
            script_dir = os.path.dirname(sys.executable)
        else:
            # Get the path of the caller of this function
            frame = inspect.currentframe()
            caller_frame = frame.f_back
            caller_file = caller_frame.f_globals["__file__"]
            script_dir = os.path.dirname(os.path.abspath(caller_file))

        # Change the current working directory to the script directory
        os.chdir(script_dir)
        print(f"Working directory changed to {script_dir}")
    except Exception as e:
        print(f"An error occurred while changing the working directory: {e}")
        raise


def _execute_silent_python_command(command):  # Duplicate code
    with open(os.devnull, "w") as devnull:
        result = subprocess.run(
            [sys.executable] + command, stdout=devnull, stderr=devnull
        )
    return result


def _cli():
    def _run_tests(tests: str = None, debug: bool = False, minimal: bool = False):
        def _debug(*args, **kwargs):
            if debug:
                print(*args, **kwargs)

        if tests is None:
            tests = "tests"
        _change_working_dir_to_script_location()
        os.chdir("../")  # To make the imports work properly
        _debug("Ensuring pytest is installed...")
        _execute_silent_python_command(["-m", "pip", "install", "pytest"])

        dir_name = "test_data"
        if os.path.exists(dir_name):
            _debug(f"Clearing directory {dir_name}...")
            shutil.rmtree(dir_name)
        _debug(f"Creating directory {dir_name}...")
        os.mkdir(dir_name)

        _debug("Running tests...")
        test = os.path.join("endpoint", tests)
        if not minimal:
            result = subprocess.run(
                [
                    "pytest",
                    "-s",
                    "-q",
                    "--tb=short",
                    #"--maxfail=1",
                    "-p",
                    "no:warnings",
                ]
                + [test]
            )  # "-vv",
        else:
            result = subprocess.run(
                ["pytest", "--tb=short", "--maxfail=1", "-p", "no:warnings"]
                + [test]
            )
        if result.returncode != 0:
            _debug(f"Tests failed for {test}.")
        else:
            _debug(f"Tests passed for {test}.")
        _debug("Tests completed.")

    parser = Interface("endpoint-cli")
    parser.path("tests.run", _run_tests)
    parser.path("help", lambda: print("Please use this command like this:\nautocli --> tests -> run {tests} "
                                      "{-debug} {-minimal}\n    |\n     -> help"))
    parser.parse_cli()


if __name__ == "__main__":
    _cli()
