"""Run the lecture-prism ChatGPT OAuth proxy server.

This module exists so a coding agent can start the bundled proxy with the
standard Python module runner. Student-facing docs still ask learners to paste
prompts into their coding agent instead of typing shell commands manually.
"""

from .run_proxy import main


if __name__ == "__main__":
    main()
