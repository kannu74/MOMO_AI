import os
import sys
from dotenv import load_dotenv
from github import Github, InputFileContent

# --- Setup ---
# Add the project root to the Python path to find the .env file
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")

def create_github_gist():
    """Tests creating a new private GitHub Gist."""
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found in .env file.")
        return

    try:
        # --- CONFIG: Change these values for your test ---
        gist_description = "A code snippet shared by Momo AI"
        gist_filename = "hello_momo.py"
        gist_content = "def hello_momo():\n    print('Hello from your AI assistant!')"
        is_public = False  # Set to True for a public Gist
        # ----------------------------------------------------

        print(f"Attempting to create a new Gist named '{gist_filename}'...")
        g = Github(GITHUB_PAT)
        user = g.get_user()

        # The Gist content must be wrapped in InputFileContent
        files = {gist_filename: InputFileContent(gist_content)}
        
        gist = user.create_gist(
            public=is_public,
            files=files,
            description=gist_description
        )
        
        print("\n--- SUCCESS! ---")
        print(f"Gist created successfully.")
        print(f"URL: {gist.html_url}")

    except Exception as e:
        print(f"\n--- ERROR ---")
        print(f"Could not create Gist. Check your token's 'gist' permissions.")
        print(f"GitHub API said: {e}")

if __name__ == "__main__":
    create_github_gist()