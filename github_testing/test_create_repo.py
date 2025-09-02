import os
from dotenv import load_dotenv
from github import Github, Auth

# Load token
load_dotenv()
GITHUB_PAT = os.getenv("GITHUB_PAT")

def create_new_repository():
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found.")
        return

    try:
        new_repo_name = "momo-test-repo-from-script"
        is_private = True

        print(f"Attempting to create a repository named '{new_repo_name}'...")

        auth = Auth.Token(GITHUB_PAT)
        g = Github(auth=auth)
        user = g.get_user()
        repo = user.create_repo(name=new_repo_name, private=is_private)
        
        print("\n--- SUCCESS! ---")
        print(f"URL: {repo.html_url}")

    except Exception as e:
        print(f"\n--- ERROR --- \nCould not create repository: {e}")

if __name__ == "__main__":
    create_new_repository()
