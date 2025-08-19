from gui.avatar import AvatarController
import time

print("--- Starting Avatar Expression Test ---")

# Initialize the controller
avatar = AvatarController()

# Give a moment to switch to the VSeeFace window to watch
print("Test will begin in 3 seconds...")
time.sleep(3)

# --- Triggering each hotkey in sequence ---

print("\nTesting Hotkey 1 (e.g., Joy/Wave)...")
avatar.trigger_hotkey_1()
time.sleep(3) # Wait 3 seconds to see the animation

print("\nTesting Hotkey 2 (e.g., Blush/Fun)...")
avatar.trigger_hotkey_2()
time.sleep(3)

print("\nTesting Hotkey 3 (e.g., Angry)...")
avatar.trigger_hotkey_3()
time.sleep(3)

print("\nTesting Hotkey 4 (e.g., Sorrow)...")
avatar.trigger_hotkey_4()
time.sleep(3)

print("\nTesting Hotkey 5 (e.g., a Custom Expression)...")
avatar.trigger_hotkey_5()
time.sleep(3)

print("\n--- Test Complete ---")