import os
import sys
import time
import pyperclip

# --- Setup to find other project files ---
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)
import commands.actions as actions

def run_all_tests():
    """Runs a series of tests for each function in the actions module."""
    print("--- Starting actions.py Test Suite ---")
    
    # --- Test 1: Set Working Directory ---
    print("\n[1/5] Testing: set_working_directory...")
    # --- CONFIG: Change 'momo-pr-test' to a real project folder name in your search paths ---
    response, project_path = actions.set_working_directory("momo-pr-test")
    print(f"Response: {response}")
    time.sleep(1)

    # --- Test 2: Explain Clipboard Code ---
    print("\n[2/5] Testing: explain_clipboard_code...")
    # --- CONFIG: Copy some code to your clipboard before running! ---
    print("Please copy a snippet of code to your clipboard now...")
    time.sleep(5)
    response = actions.explain_clipboard_code()
    print(f"Response: {response}")
    time.sleep(1)
    
    # --- Test 3: Create GitHub Repo ---
    print("\n[3/5] Testing: create_github_repo...")
    # --- CONFIG: The script will try to create this repo. It will fail if it already exists. ---
    repo_name = f"momo-action-test-{int(time.time())}"
    response = actions.create_github_repo(repo_name, is_private=True)
    print(f"Response: {response}")
    time.sleep(1)

    # --- Test 4: Suggest Commit Message ---
    print("\n[4/5] Testing: suggest_commit_message...")
    if project_path:
        print(f"NOTE: Make sure you have staged changes in '{project_path}' for this to work.")
        response = actions.suggest_commit_message(project_path)
        print(f"Response: {response}")
    else:
        print("Skipping test: Project path not set.")
    time.sleep(1)

    # --- Test 5: Comment on Issue ---
    print("\n[5/5] Testing: comment_on_issue...")
    # --- CONFIG: Set your username/repo and a real issue number ---
    repo_name_for_comment = "kannu74/momo-pr-test" 
    issue_number_for_comment = 1
    comment_text = "This is an automated test comment from Momo's actions.py script."
    response = actions.comment_on_issue(repo_name_for_comment, issue_number_for_comment, comment_text)
    print(f"Response: {response}")
    
    print("\n--- All Tests Complete ---")

if __name__ == "__main__":
    run_all_tests()