"""Generates a local test image and synthetic .wav audio clip for immediate testing."""
import os
import wave
import numpy as np
from PIL import Image, ImageDraw

os.makedirs("test_samples", exist_ok=True)

img = Image.new("RGB", (512, 384), color=(35, 50, 75))
draw = ImageDraw.Draw(img)
draw.rectangle([140, 90, 370, 290], fill=(210, 180, 140), outline=(255, 255, 255), width=3)
draw.text((165, 180), "CivicPulse Sample", fill=(20, 20, 20))
img.save("test_samples/sample_image.png")

sr = 16000
t = np.linspace(0, 4.0, int(sr * 4.0), endpoint=False)
signal = 0.4 * np.sin(2 * np.pi * 440 * t) + 0.15 * np.sin(2 * np.pi * 1200 * t)
pcm = (signal * 32767).astype(np.int16)

with wave.open("test_samples/sample_voice.wav", "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(pcm.tobytes())

print("Created test_samples/sample_image.png and test_samples/sample_voice.wav")
