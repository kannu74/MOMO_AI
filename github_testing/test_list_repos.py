import os
from dotenv import load_dotenv
from github import Github

# --- Setup ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")

def list_repositories():
    """Tests fetching your repositories."""
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found in .env file.")
        return

    try:
        print("Fetching your 10 most recently updated repositories...")
        g = Github(GITHUB_PAT)
        user = g.get_user()
        repos = user.get_repos(type='owner', sort='updated')
        
        print("\n--- REPOSITORIES ---")
        for i, repo in enumerate(repos[:10]):
            print(f"{i+1}. {repo.full_name}")

    except Exception as e:
        print(f"\n--- ERROR --- \nCould not fetch repositories: {e}")

if __name__ == "__main__":
    list_repositories()