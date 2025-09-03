import os
import sys
import subprocess
from dotenv import load_dotenv
from github import Github

# --- Setup to find other project files and .env ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")
from backend.core import get_gpt_response

def create_github_repo(repo_name: str, is_private: bool):
    """Creates a new repository on your GitHub account."""
    if not GITHUB_PAT:
        return "Error: GITHUB_PAT not found in .env file."
    try:
        g = Github(GITHUB_PAT)
        user = g.get_user()
        print(f"Creating new repository on GitHub named '{repo_name}'...")
        repo = user.create_repo(name=repo_name, private=is_private)
        return f"Success! Repository '{repo.full_name}' created at {repo.html_url}"
    except Exception as e:
        return f"Error creating repository: {e}"

def suggest_commit_message(project_path: str):
    """Uses git diff and an LLM to suggest a commit message."""
    if not os.path.isdir(project_path):
        return "Error: That project path doesn't exist."
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--staged"], cwd=project_path, check=True, 
            capture_output=True, text=True, encoding='utf-8'
        )
        diff = diff_result.stdout
        if not diff:
            return "There are no staged changes to suggest a message for."

        prompt = f"Based on this git diff, suggest a concise, conventional commit message:\n\n{diff}"
        suggestion = get_gpt_response(prompt, mode="developer")
        return f"Based on the changes, how about this: {suggestion}"
    except Exception as e:
        return f"Error suggesting message: {e}"

# Add other developer actions here in the future...