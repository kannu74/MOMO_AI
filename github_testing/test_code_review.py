import os
import sys
import requests
from dotenv import load_dotenv
from github import Github

# --- Setup ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")
from backend.core import get_gpt_response

def perform_ai_code_review():
    """Tests performing an AI code review on an existing PR."""
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found in .env file.")
        return
        
    try:
        # --- CONFIG: Change these values for your test ---
        target_repo_name = "your_github_username/your_repo_name"
        target_pr_number = 2 # Use a real PR number from the repo
        # ----------------------------------------------------

        print(f"Performing AI code review on PR #{target_pr_number}...")
        g = Github(GITHUB_PAT)
        repo = g.get_repo(target_repo_name)
        pr = repo.get_pull(number=target_pr_number)

        # 1. Get the diff content of the PR
        headers = {'Authorization': f'token {GITHUB_PAT}', 'Accept': 'application/vnd.github.v3.diff'}
        response = requests.get(pr.diff_url, headers=headers)
        response.raise_for_status()
        diff_text = response.text
        
        # 2. Use LLM to review the code
        print("Asking Momo to review the code...")
        prompt = f"""
        You are a senior software developer performing a code review.
        Analyze the following git diff from a pull request.
        Provide constructive feedback on potential bugs, style issues, and suggest improvements.
        Format your review in markdown. If there are no issues, simply say "LGTM! (Looks Good To Me)".

        Git Diff:
        ---
        {diff_text}
        """
        review_comment = get_gpt_response(prompt)
        
        # 3. Post the review as a comment on the PR
        print("Posting review comment to GitHub...")
        pr.create_issue_comment(f"**Momo's AI Code Review:**\n\n{review_comment}")
        
        print("\n--- SUCCESS! ---")
        print(f"AI code review posted to PR #{target_pr_number} at {pr.html_url}")

    except Exception as e:
        print(f"\n--- ERROR --- \nCould not perform code review: {e}")

if __name__ == "__main__":
    perform_ai_code_review()