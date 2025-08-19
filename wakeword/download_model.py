# A simple script to download a pre-trained openwakeword model.
from openwakeword.utils import download_models

print("Starting the model download process...")
print("This may take a moment depending on your internet connection.")

# We will download the 'hey_jarvis_v0.1' model
# The library will handle finding and downloading it from the correct, current location.
try:
    download_models(["hey_jarvis_v0.1"])
    print("\nDownload complete!")
    print("The model has been saved to the openwakeword cache directory.")
    print("Please follow the instructions to find it and copy it to your project.")
except Exception as e:
    print(f"\nAn error occurred during download: {e}")
    print("Please check your internet connection and make sure the 'openwakeword' library is installed correctly.")