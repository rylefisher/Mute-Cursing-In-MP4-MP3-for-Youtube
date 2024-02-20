import stable_whisper
import numpy as np
import json
import soundfile as sf
import csv
from tkinter import Tk, messagebox, filedialog
import csv
import random
from audio_extract import extract_audio
from pathlib import Path
import torch
from progress.bar import Bar
import wave
from os import remove
from file_utils import *
from process_files import remove_clicks


# Define paths and file names
CURSE_WORD_FILE = 'curse_words.csv'
sample_audio_path = 'looperman.wav'

 

def load_transcript():
    # Ask the user if they want to load an existing transcript
    if messagebox.askyesno('Load Transcript', 'If this program crashed, this saves the transcript to ensure it doesn\'t require restarting.\n\nDo you want to load an existing transcript?'):
        # File dialog to select a transcript JSON file
        transcript_path = filedialog.askopenfilename(
            title='Select Transcript File',
            filetypes=[('JSON files', '*.json')]
        )
        if transcript_path:
            print(f'Transcript file selected: {transcript_path}')
            return transcript_path
    return None


def select_audio_or_video():
    # File dialog to select an audio file
    av_path = filedialog.askopenfilename(
        title='Select A/V files',
        filetypes=[('A/V files', '*.mp3 *.wav *.mp4')]
    )
    if av_path:
        print(f'Audio/Video file selected: {av_path}')
        return av_path
    return None



def read_curse_words_from_csv(CURSE_WORD_FILE):
    curse_words_list = []
    with open(CURSE_WORD_FILE, newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            # Assuming curse words are in column A
            curse_words_list.append(row[0])
    return curse_words_list
# Function to mute curse words in the audio
# Function to check if the base form of a word is in the curse words set


def load_wav_as_np_array(wav_file_path):
    # Open the audio file
    try:
        with wave.open(wav_file_path, "rb") as wav_file:
            # Ensure that the audio file is mono
            if wav_file.getnchannels() != 1:
                raise ValueError("Only mono audio files are supported.")

            # Extract audio frames
            frames = wav_file.readframes(wav_file.getnframes())

            # Convert audio frames to float32 NumPy array
            audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)

            # Normalize the audio data
            audio_data /= np.iinfo(np.int16).max

            # Return the audio data and the sample rate
            return audio_data, wav_file.getframerate()
    except wave.Error as e:
        print(f"An error occurred while reading the WAV file: {wav_file_path}")
        print(e)
    return sf.read(wav_file_path, dtype='float64')



def get_word_samples(word, sample_rate):

    # Extract start and end times from the word timestamps, assume they are in seconds
    start_time = word['start']
    end_time = word['end']

    # Convert the start and end times to sample indices
    start_sample = int(start_time * sample_rate)
    end_sample = int(end_time * sample_rate)

    return (start_sample, end_sample)


def apply_fade(audio_data, start_sample, end_sample, sample_rate, fade_duration=0.001):
    # Calculate the number of samples for the fade duration
    fade_samples = int(fade_duration * sample_rate)

    # Apply an exponential fade-in
    for i in range(fade_samples):
        # Calculate the exponential fade-in factor
        fade_in_factor = 1 - np.exp(-i / fade_samples)
        # Apply fade-in to the starting sample
        audio_data[start_sample + i] *= fade_in_factor

    # Apply an exponential fade-out
    for i in range(fade_samples):
        # Calculate the exponential fade-out factor
        fade_out_factor = np.exp(-(fade_samples - i) / fade_samples)
        # Apply fade-out to the ending sample
        audio_data[end_sample - i] *= fade_out_factor

    return audio_data


def split_silence(sample_rate, word):
    # Calculate the start and end sample indices
    start_sample = int(word['start'] * sample_rate)
    end_sample = int(word['end'] * sample_rate)
    if (end_sample - start_sample) < 3000:
        start_sample = start_sample - 1000
        end_sample = end_sample + 1000
    return start_sample, end_sample


def mute_curse_words(audio_data, sample_rate, transcription_result, curse_words_list):
    # Create a copy of the audio data to avoid modifying the original
    audio_data_muted = np.copy(audio_data)
    # Create a set for faster membership testing
    curse_words_set = set(word.lower() for word in curse_words_list)
    bar = Bar('Processing', max=len(transcription_result))

    # Initialize an empty list to store the start and end sample indices for muting
    mute_indices = []
    # Go through each segment in the transcription result
    for word in transcription_result:
        bar.next()
        if word['word'] in curse_words_set:
            # Check if the word is in the curse words set
            start_sample, end_sample = split_silence(sample_rate, word)
            # Apply fade-in before muting
            audio_data_muted = apply_fade(audio_data_muted, start_sample,
                        end_sample, sample_rate)
            # Mute the curse words by setting the amplitude to zero
            audio_data_muted[start_sample:end_sample] = 0
            # Apply fade-out after muting
            audio_data_muted = apply_fade(audio_data_muted, start_sample,
                        end_sample, sample_rate)
    bar.finish()
    return audio_data_muted


def convert_stereo(f):
    # Read the stereo audio file
    data, sample_rate = sf.read(f)
    # Check if the file is indeed stereo
    if data.ndim > 1 and data.shape[1] == 2:
        # Average the stereo channels to convert to mono
        mono_data = data.mean(axis=1)
    else:
        # If it's already mono, just assign it as is
        mono_data = data
    # Ensure the data is in float32 format
    mono_data = mono_data.astype('float32')
    # Write the mono data to a new audio file
    sf.write(f, mono_data, sample_rate,
             format='WAV', subtype='FLOAT')


def transcribe_audio(audio_file, device_type):
    model = stable_whisper.load_faster_whisper(
        'large-v3', device=device_type)
    # model = stable_whisper.load_model('large-v3', device=device_type)
    result = model.transcribe_stable(
        audio_file, word_timestamps=True)
    transcript_path = f'transcript{random.randint(0, 100)}.json'
    result.save_as_json(transcript_path)
    return transcript_path


def find_curse_words(audio_content, sample_rate, transcript_file, CURSE_WORD_FILE=CURSE_WORD_FILE):
    results = process_json(transcript_file)
    curses = read_curse_words_from_csv(CURSE_WORD_FILE)
    curse_words_set = set(curses)
    return mute_curse_words(audio_content, sample_rate, results, curse_words_set)


def process_audio(audio_file, transcript_file=None):
    device_type = "cuda" if torch.cuda.is_available() else "cpu"
    if not transcript_file:
        transcript_file = transcribe_audio(audio_file, device_type)
    convert_stereo(audio_file)
    audio_data, sample_rate = sf.read(audio_file, samplerate=None, dtype='float64')

    muted_audio = find_curse_words(
        audio_data, sample_rate, transcript_file)
    outfile = Path(audio_file).parent / \
        str(Path(audio_file).name + '_muted_audio.wav')
    # @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    remove_clicks(muted_audio, sample_rate, 0.5)
    # @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
    sf.write(outfile, muted_audio, sample_rate)
    return outfile


def process_video(input_video_path, transcript_file):
    # Define output paths
    output_audio_path = Path(input_video_path).with_suffix('.wav')
    suf = str(Path(output_audio_path).suffix)
    audio_out = Path(Path(input_video_path).parent / "audio.wav")
    output_video_path = str(output_audio_path).replace(suf, "clean_video.mp4")
    remove(str(audio_out))
    extract_audio(input_path=input_video_path,
                  output_path=str(audio_out), output_format="wav")
    remove_clicks
    # Process audio (assuming process_audio returns a path to the processed audio file)
    return process_audio(
        str(audio_out), transcript_file)


def main():
    root = Tk()
    root.withdraw()  # Hide the main window
    root.attributes('-topmost', True)
    transcript_file = load_transcript()
    input_video_path = select_audio_or_video()
    cwd = Path(input_video_path).parent

    if Path(input_video_path).suffix == '.mp4':
        result = process_video(input_video_path, transcript_file)
        song = Path(input_video_path).parent / result

    else:
        # Process audio only
        process_audio(input_video_path, transcript_file)


if __name__ == "__main__":
    make_dirs()
    main()
