from faster_whisper import WhisperModel
import queue
import threading
import numpy as np
import sounddevice as sd

samplerate = 16000
block_duration = 0.5
chunk_duration = 2
channels = 1

frames_per_block = (int)(samplerate * block_duration)
frames_per_chunk = (int)(samplerate * chunk_duration)
audio_queue = queue.Queue()
audio_buffer = []

model= WhisperModel("tiny.en", device="cpu",compute_type="int8")
#print(info.language, info.language_probability)
def audio_callback(indata,frames,time,status):
    if status:
        print(status)
    audio_queue.put(indata.copy())
def reorder():
    with sd.InputStream(samplerate=samplerate,channels=channels,callback=audio_callback, blocksize=frames_per_block):
        print("listening")
        while True:
            sd.sleep(100)
def transcribe():
    global audio_buffer
    while True:
        block = audio_queue.get()
        audio_buffer.append(block)
        total_frames = sum(len(b) for b in audio_buffer)
        if total_frames >= frames_per_chunk:
            audio_data = np.concatenate(audio_buffer)[:frames_per_chunk]
            audio_buffer = []
            audio_data = audio_data.flatten().astype(np.float32)
            segments,_ = model.transcribe(audio_data,language='en',beam_size=1)
            for degment in segments:
                print(degment.text)


threading.Thread(target=reorder,daemon=True).start()
transcribe()
