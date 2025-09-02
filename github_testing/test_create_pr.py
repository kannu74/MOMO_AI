import os
import sys
import subprocess
from dotenv import load_dotenv
from github import Github

# --- Setup for running from a subfolder ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")
from backend.core import get_gpt_response # Import Momo's brain

def create_ai_powered_pr():
    """Tests creating a PR with an AI-generated summary."""
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found in .env file.")
        return
        
    try:
        # --- CONFIG: Change these values for your test ---
        target_repo_name = "kannu74/momo-test-repo-from-script"
        project_path = "C:/Users/aksha/Downloads/samplegithub for pr/momo-test-repo-from-script" # Local path
        head_branch = "my-feature-branch" # The branch with your changes
        base_branch = "main" # The branch you want to merge into
        # ----------------------------------------------------
        
        print(f"Generating PR for {head_branch} -> {base_branch}...")

        # 1. Get code differences from local git
        diff_result = subprocess.run(
            ["git", "diff", f"origin/{base_branch}...{head_branch}"], 
            cwd=project_path, check=True, capture_output=True, text=True, encoding='utf-8'
        )
        diff_text = diff_result.stdout

        if not diff_text:
            print("No differences found between the branches. Exiting.")
            return

        # 2. Use LLM to generate title and body
        print("Asking Momo to summarize the changes...")
        prompt = f"""
        Based on the following git diff, generate a suitable Pull Request title and a markdown-formatted summary of the changes.
        Format your response ONLY as:
        Title: <Your PR Title>
        Body: <Your PR Body in markdown>

        Git Diff:
        ---
        {diff_text}
        """
        llm_response = get_gpt_response(prompt)
        
        title = llm_response.split("Title:")[1].split("Body:")[0].strip()
        body = llm_response.split("Body:")[1].strip()

        # 3. Create the PR using the GitHub API
        print("Creating Pull Request on GitHub...")
        g = Github(GITHUB_PAT)
        repo = g.get_repo(target_repo_name)
        
        pr = repo.create_pull(title=title, body=body, head=head_branch, base=base_branch)
        
        print("\n--- SUCCESS! ---")
        print(f"AI-Powered Pull Request #{pr.number} created at {pr.html_url}")

    except Exception as e:
        print(f"\n--- ERROR --- \nCould not create PR: {e}")

if __name__ == "__main__":
    create_ai_powered_pr()