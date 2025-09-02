import os
import sys
from dotenv import load_dotenv
from github import Github

# --- Setup ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)
GITHUB_PAT = os.getenv("GITHUB_PAT")
# Import Momo's brain
from backend.core import get_gpt_response

def ai_comment_on_issue():
    """
    Fetches the latest issue, uses the Gemini LLM to draft a comment,
    and handles the case where no issues exist.
    """
    if not GITHUB_PAT:
        print("FATAL ERROR: GITHUB_PAT not found in .env file.")
        return

    try:
        # --- CONFIG: Change these values for your test ---
        target_repo_name = "kannu74/momo-test-repo-from-script"
        # Your simple instruction for the AI for the latest issue
        instruction = "Acknowledge this issue and state that I will look into it."
        # ----------------------------------------------------

        print(f"Checking for open issues in '{target_repo_name}'...")
        g = Github(GITHUB_PAT)
        repo = g.get_repo(target_repo_name)
        
        # --- THIS IS THE FIX ---
        # 1. Get a list of all open issues
        open_issues = repo.get_issues(state='open')
        
        # 2. Check if any issues exist
        if open_issues.totalCount == 0:
            print("\n--- INFO ---")
            print("There are no open issues in this repository.")
            return
            
        # 3. If issues exist, get the latest one (first in the list)
        latest_issue = open_issues[0]
        print(f"Found latest issue: #{latest_issue.number} - '{latest_issue.title}'")
        
        # 4. Create a detailed prompt for the LLM
        prompt = f"""
        You are an AI assistant helping a developer manage a GitHub project.
        Based on the following user instruction and GitHub issue details, draft a professional and friendly comment.

        **My Instruction:** "{instruction}"

        **GitHub Issue Details:**
        - **Title:** "{latest_issue.title}"
        - **Body:** "{latest_issue.body}"
        """
        
        # 5. Use Gemini to generate the comment
        print("Asking Momo to draft the comment...")
        comment_body = get_gpt_response(prompt)
        
        # 6. Post the AI-generated comment
        print(f"Posting AI-generated comment: '{comment_body}'")
        comment = latest_issue.create_comment(comment_body)
        
        print("\n--- SUCCESS! ---")
        print(f"Intelligent comment successfully posted.")
        print(f"URL: {comment.html_url}")

    except Exception as e:
        print(f"\n--- ERROR ---")
        print(f"Could not process issue: {e}")

if __name__ == "__main__":
    ai_comment_on_issue()