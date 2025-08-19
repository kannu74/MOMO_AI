from pythonosc import udp_client

# VSeeFace default IP and Port
VSEEFACE_IP = "127.0.0.1"
VSEEFACE_PORT = 39539

class AvatarController:
    def __init__(self):
        """Initializes the OSC client to send messages to VSeeFace."""
        try:
            self.client = udp_client.SimpleUDPClient(VSEEFACE_IP, VSEEFACE_PORT)
            print("AvatarController: Connected to VSeeFace.")
        except Exception as e:
            print(f"AvatarController: Could not connect to VSeeFace. Error: {e}")
            self.client = None

    def _trigger_hotkey(self, key_name: str):
        """Sends a message to VSeeFace to trigger a hotkey."""
        if not self.client:
            return
            
        address = "/VMC/Ext/Key"
        # 1 means key down (press), 0 would mean key up (release)
        self.client.send_message(address, (1, key_name))
        print(f"Sent command to trigger hotkey: {key_name}")

    def trigger_hotkey_1(self):
        """Triggers the expression on NumPad 1."""
        self._trigger_hotkey("Numpad1")

    def trigger_hotkey_2(self):
        """Triggers the expression on NumPad 2."""
        self._trigger_hotkey("Numpad2")

    def trigger_hotkey_3(self):
        """Triggers the expression on NumPad 3."""
        self._trigger_hotkey("Numpad3")

    def trigger_hotkey_4(self):
        """Triggers the expression on NumPad 4."""
        self._trigger_hotkey("Numpad4")
        
    def trigger_hotkey_5(self):
        """Triggers the expression on NumPad 5."""
        self._trigger_hotkey("Numpad5")