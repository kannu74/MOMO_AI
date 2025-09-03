import os
import sys
import subprocess
from dotenv import load_dotenv
from github import Github, Auth, InputFileContent, UnknownObjectException
import pyperclip
import re
\

# --- Setup to find other project files and .env ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")
from backend.core import get_gpt_response

# --- Centralized GitHub Client Initialization ---
# Initialize the client once and reuse it in all functions
auth = Auth.Token(GITHUB_PAT)
g = Github(auth=auth)

# --- Action Functions ---

def list_repositories():
    """Fetches and lists your 10 most recently updated repositories."""
    if not GITHUB_PAT: return "Error: GITHUB_PAT not found."
    try:
        user = g.get_user()
        repos = user.get_repos(type='owner', sort='updated')
        repo_list = [f"{i+1}. {repo.name}" for i, repo in enumerate(repos[:10])]
        return "Here are your 10 most recently updated repositories:\n" + "\n".join(repo_list)
    except Exception as e:
        return f"Could not fetch repositories: {e}"

def create_github_gist(description: str, filename: str, content: str, is_public: bool = False):
    """Creates a new public or private Gist from provided text."""
    if not GITHUB_PAT: return "Error: GITHUB_PAT not found."
    try:
        user = g.get_user()
        files = {filename: InputFileContent(content)}
        gist = user.create_gist(public=is_public, files=files, description=description)
        return f"Success! Your Gist was created at {gist.html_url}"
    except Exception as e:
        return f"Could not create Gist: {e}"

def suggest_commit_message(project_path: str, session_id: str):
    """Uses git diff and an LLM to suggest a commit message."""
    if not os.path.isdir(project_path): return "Error: Project path doesn't exist."
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--staged"], cwd=project_path, check=True, 
            capture_output=True, text=True, encoding='utf-8'
        )
        diff = diff_result.stdout
        if not diff: return "There are no staged changes to suggest a message for."
        
        prompt = f"Based on this git diff, suggest a concise, conventional commit message:\n\n{diff}"
        
        # Pass the session_id to the LLM call
        suggestion = get_gpt_response(prompt, session_id, mode="developer")
        return f"Based on the changes, how about this: {suggestion}"
    except Exception as e:
        return f"Error suggesting message: {e}"

def explain_clipboard_code(session_id: str):
    """Sends the clipboard's content to the LLM for a high-quality explanation."""
    try:
        code = pyperclip.paste()
        if not code: 
            return "Your clipboard is empty. Please copy some code first."
        
        # A much more detailed and specific prompt
        prompt = f"""
        You are an expert code reviewer. Your task is to explain the following code snippet from the user's clipboard.
        Ignore any confusion from the user's voice command and focus ONLY on the code.

        **Instructions:**
        1.  Provide a brief, one-sentence summary of the code's main purpose.
        2.  Then, provide a simple, bullet-point explanation of what the key parts of the code do.
        3.  Keep the explanation concise and easy to understand.

        **Code to Explain:**
        ```python
        {code}
        ```
        """
        
        # We call the LLM in "normal" mode to get a conversational response
        explanation = get_gpt_response(prompt, session_id, mode="normal")
        return explanation
        
    except Exception as e:
        return f"Sorry, I couldn't get an explanation. Error: {e}"

def create_github_repo(repo_name: str, is_private: bool):
    if not GITHUB_PAT: return "Error: GITHUB_PAT not found."
    try:
        user = g.get_user()
        repo = user.create_repo(name=repo_name, private=is_private)
        return f"Success! Repository '{repo.full_name}' created at {repo.html_url}"
    except Exception as e:
        return f"Error creating repository: {e}"

def comment_on_issue(issue_num: int, comment: str, repo_name: str = None):
    """
    Posts a comment to a GitHub issue.
    Uses the provided repo_name, otherwise requires a repo to be set as context.
    """
    if not GITHUB_PAT: 
        return "Error: GITHUB_PAT not found in .env file."
    
    # Use the explicitly provided repo_name, otherwise this function can't run
    if not repo_name:
        return "Error: You need to specify a repository name or set a working directory first."
        
    try:
        g = Github(GITHUB_PAT)
        # The repo_name must be in "username/reponame" format
        repo = g.get_repo(repo_name)
        issue = repo.get_issue(number=issue_num)
        issue.create_comment(comment)
        return f"Done. I've posted your comment to issue number {issue_num} in the {repo_name} repository."
    except Exception as e:
        return f"Could not post comment. Please check the repository name and issue number. Error: {e}"

def git_commit_and_push(project_path: str, message: str):
    if not project_path: return "Error: Please set a working directory first."
    try:
        subprocess.run(["git", "add", "."], cwd=project_path, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=project_path, check=True)
        subprocess.run(["git", "push"], cwd=project_path, check=True)
        return "Okay, I've successfully committed and pushed your changes."
    except Exception as e:
        return f"A Git command failed: {e}"
    
def set_working_directory(path_query: str) -> tuple[str, str]:
    """
    Finds a project directory in a case-insensitive way and sets it as the context.
    This version searches only the top level of the specified search_paths.
    """
    print(f"Searching for a project directory named '{path_query}'...")
    
    # Add common parent folders where you store your projects
    search_paths = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        # You can add more, e.g., "C:/Projects"
    ]
    
    path_query_lower = path_query.lower()

    for path in search_paths:
        # Skip any search paths that don't exist
        if not os.path.isdir(path):
            continue
            
        try:
            # --- THIS IS THE FIX ---
            # os.listdir() gets all files and folders directly inside a path
            for item_name in os.listdir(path):
                # Check if the item is a directory and its name matches
                item_path = os.path.join(path, item_name)
                if os.path.isdir(item_path) and path_query_lower == item_name.lower():
                    print(f"Working directory found: {item_path}")
                    # Return the original directory name to preserve its casing
                    return f"Okay, my working directory is now set to {item_name}.", item_path
        except PermissionError:
            print(f"Warning: Permission denied to search in {path}. Skipping.")
            continue
    
    # If the loop finishes without finding the directory
    return f"Sorry, I couldn't find a project folder named '{path_query}' in my search paths.", None

def get_git_status(project_path: str):
    if not project_path: return "Error: Please set a working directory first."
    result = subprocess.run(["git", "status", "-s"], cwd=project_path, capture_output=True, text=True, encoding='utf-8')
    if not result.stdout: return "Your working directory is clean."
    return f"Here is your current status:\n{result.stdout}"

def git_pull_updates(project_path: str, branch: str = "main"):
    if not project_path: return "Error: Please set a working directory first."
    try:
        subprocess.run(["git", "pull", "origin", branch], cwd=project_path, check=True)
        return f"Successfully pulled the latest changes from the '{branch}' branch."
    except Exception as e: return f"Error pulling changes: {e}"

def git_revert_last_commit(project_path: str):
    if not project_path: return "Error: Please set a working directory first."
    try:
        subprocess.run(["git", "revert", "HEAD", "--no-edit"], cwd=project_path, check=True)
        return "Okay, I've reverted the last commit. You may need to push this change."
    except Exception as e: return f"Error reverting commit: {e}"
    
def set_repo_context(repo_name_query: str, username: str):
    """
    Checks if a repository exists on GitHub and sets it as the context.
    Returns a specific message if the repository is not found.
    """
    if not GITHUB_PAT or not username:
        return "Error: GitHub credentials are not set.", None

    full_repo_name = f"{username}/{repo_name_query}"
    
    try:
        g = Github(GITHUB_PAT)
        # This line will fail if the repo doesn't exist
        repo = g.get_repo(full_repo_name)
        
        # If the line above succeeds, the repo exists.
        print(f"Repository context set to: {repo.full_name}")
        return f"Okay, I'm now focused on the {repo.full_name} repository.", repo.full_name
        
    except UnknownObjectException:
        # This is the specific error for a repo that doesn't exist
        return "not_found", None
    except Exception as e:
        # Handle other potential errors like network issues
        return f"An error occurred while checking the repository: {e}", None