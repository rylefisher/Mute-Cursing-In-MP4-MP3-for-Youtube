import csv
import numpy as np
import wave
import soundfile as sf
from pathlib import Path
from read_ import *
import noisereduce as nr
import threading
import os
import shutil
import json
from scipy.io import wavfile


segment_duration = 3000
buff_ratio = 0.95
CURSE_WORD_FILE = 'curse_words.csv'

sample_audio_path = 'looperman.wav'
transcripts = ""
exports = ""
new_trans_path = Path.cwd()
new_trans_path = Path(str(new_trans_path) + "\\transcripts")

# 0.4 IS 0.2 ADDITIONAL SECONDS BEFORE AND AFTER CURSE ON TOP OF EXISTING SILENCE.
ADJUST_SILENCE = 1.25


class PortableNoiseReduction:
    def __init__(self, array: np.ndarray, start_time: float, end_time: float, sample_rate: int):
        """
        Initialize with a numpy array and specified start & end times for noise reduction.
        :param array: numpy array containing audio data.
        :param start_time: start time in seconds to apply noise reduction.
        :param end_time: end time in seconds to apply noise reduction.
        :param sample_rate: sample rate of the audio data in Hz.
        """
        self.array = array
        self.start_time = (start_time - 1) if start_time > 0 else 0
        self.end_time = end_time + 1
        self.sample_rate = sample_rate

    def apply_noise_reduction(self):
        """
        Apply noise reduction to the specified segment of the audio.
        Returns a new numpy array with noise reduction applied to the specified segment.
        """
        # Calculate the start and end indices
        start_sample = int(self.start_time * self.sample_rate)
        end_sample = int(self.end_time * self.sample_rate)

        # Extract segment for noise reduction
        segment = self.array[:,
                             start_sample:end_sample] if self.array.ndim == 2 else self.array[start_sample:end_sample]

        # Apply noise reduction
        reduced_noise_segment = nr.reduce_noise(y=segment, sr=self.sample_rate)

        # Replace original segment with reduced noise segment
        if self.array.ndim == 2:  # Multi-channel
            self.array[:, start_sample:end_sample] = reduced_noise_segment
        else:  # Single channel
            self.array[start_sample:end_sample] = reduced_noise_segment

        return self.array


def read_curse_words_from_csv(CURSE_WORD_FILE):
    """
     Read curse words from CSV file. This is a list of words that are part of CURIE's word list

     @param CURSE_WORD_FILE - Path to file to read

     @return List of words in CURIE's word list ( column A ) as defined in CSV file
    """
    curse_words_list = []
    with open(CURSE_WORD_FILE, newline='') as csvfile:
        lines = [line for line in csvfile.readlines() if line != ""]
    lines_update = [line.lower().strip() for line in lines if line != ""]
    return lines_update


def load_wav_as_np_array(wav_file_path):
    """
     Load a WAV file and return the audio data as NumPy array. This function is used to load mono wav files that are stored in a file system.

     @param wav_file_path - The path to the WAV file

     @return A tuple containing the audio data and the sample
    """
    try:
        with wave.open(wav_file_path, "rb") as wav_file:
            # Ensure that the audio file is mono
            if wav_file.getnchannels() != 1:
                raise ValueError("Only mono audio files are supported.")

            # Extract audio frames
            frames = wav_file.readframes(wav_file.getnframes())

            # Convert audio frames to float64 NumPy array
            audio_data = np.frombuffer(
                frames, dtype=np.int16).astype(np.float32)

            # Normalize the audio data
            audio_data /= np.iinfo(np.int16).max

            # Return the audio data and the sample rate
            return audio_data, wav_file.getframerate()
    except wave.Error as e:
        print(f"An error occurred while reading the WAV file: {wav_file_path}")
        print(e)
    return sf.read(wav_file_path, dtype='float32')


def get_word_samples(word, sample_rate):
    """
    Get start and end sample indices from a word. This is a helper function for get_word_samples and get_word_samples_with_time_range.

    @param word - The word to get samples from. Should have'start'and'end'fields.
    @param sample_rate - The sample rate in Hz.

    @return A tuple of start and end sample indices for the word in time units of the sample_rate passed
    """
    start_time = word['start']
    end_time = word['end']

    # Convert the start and end times to sample indices
    start_sample = int(start_time * sample_rate)
    end_sample = int(end_time * sample_rate)

    return (start_sample, end_sample)


def apply_combined_fades(audio, sample_rate, start_time, stop_time, fade_duration=0.01):
    """
    Apply combined fades to the audio.

    Args:
        audio (ndarray): The audio data.
        sample_rate (int): The sample rate of the audio.
        start_time (float): The start time of the fade in seconds.
        stop_time (float): The stop time of the fade in seconds.
        fade_duration (float, optional): The duration of the fade in seconds. Defaults to 0.01.

    Returns:
        ndarray: The audio data with the combined fades applied.
    """
    # Convert times to samples
    global buff_ratio
    original_start = 0
    original_start = start_time
    diff = stop_time - start_time
    start_time = (stop_time - (diff * buff_ratio))
    # stop_time = (original_start + (diff * buff_ratio))

    fade_length = int(fade_duration * sample_rate)
    start_sample = int(start_time * sample_rate)
    stop_sample = int(stop_time * sample_rate)

    # Apply fade out
    fade_out_end = start_sample + fade_length
    if fade_out_end > audio.shape[0]:
        fade_out_end = audio.shape[0]
    fade_out_curve = np.linspace(1.0, 0.0, fade_out_end - start_sample)
    audio[start_sample:fade_out_end] *= fade_out_curve

    # Apply fade in
    fade_in_start = stop_sample - fade_length
    if fade_in_start < 0:
        fade_in_start = 0
    fade_in_curve = np.linspace(0.0, 1.0, stop_sample - fade_in_start)
    audio[fade_in_start:stop_sample] *= fade_in_curve

    # Ensure silence between the fades
    audio[fade_out_end:fade_in_start] = 0
    return audio


def logger(message):
    with open('log.txt', "w") as f:
        f.write(message + "\n")


def mute_curse_words(audio_data, sample_rate, transcription_result, curse_words_list, log=True):
    """
    Mute curse words in the audio data.
    """
    audio_data_muted = np.copy(audio_data)
    # curse_words_set = set(word.lower() for word in curse_words_list)

    for word in transcription_result:
        if len(word['word']) < 3:
            continue
        matched_curse = next(
            (curse for curse in curse_words_list if curse in word['word'].lower()), None)
        if matched_curse:
            if log == True:
                print(
                    f"curse:{matched_curse} -> transcript word:{word['word']} -> prob {word['probability']}")
            audio_data_muted = apply_combined_fades(
                audio_data_muted, sample_rate, word['start'], word['end'])
            """
            potential
            take word['probability'] look at ratio, and if it is below a certain threshold, then mute the word"""
    return audio_data_muted


def convert_stereo(f):
    """
    Reads an audio file (.wav or .mp3) and returns it in a mono format.
    """
    return NumpyMono(f)


def find_curse_words(audio_content, sample_rate, results, CURSE_WORD_FILE=CURSE_WORD_FILE):
    """
     Find Curse words in audio content. This is a wrapper around mute_curse_words that takes into account the sample rate in order to get an accurate set of cursors and returns a set of words that are present in the audio

     @param audio_content - The audio content to search
     @param sample_rate - The sample rate in Hz
     @param transcript_file - The file containing the transcripts.
     @param CURSE_WORD_FILE - The path to the CSV file containing curse words.

     @return The set of words that are present in the audio content and are not present in the transcript. This set is used to make sure that we don't accidentally miss a word
    """
    curses = read_curse_words_from_csv(CURSE_WORD_FILE)
    curse_words_set = set(curses)
    return mute_curse_words(audio_content, sample_rate, results, curse_words_set)


def process_audio_batch(trans_audio):
    max_threads = 5
    threads = []
    processed_paths = {}

    def wait_for_threads(threads):
        for thread in threads:
            thread.join()
        threads.clear()

    threadnumb = 0
    for trans, audio in trans_audio.items():
        threadnumb += 1

        if len(threads) >= max_threads:
            wait_for_threads(threads)

        # Sample way to track processed paths. Implement according to the actual process_audio
        processed_paths[threadnumb] = f"{audio}_processed"

        thread = threading.Thread(
            target=process_audio, args=(audio, threadnumb, trans))
        threads.append(thread)
        thread.start()

    # Wait for the remaining threads
    wait_for_threads(threads)
    return processed_paths


def combine_wav_files(segment_paths):
    """
    Combines multiple .wav files into a single .wav file, ensuring the header information is correct.

    :param segment_paths: List of paths to .wav files to be combined.
    """
    if not segment_paths:
        print("No paths provided!")
        return

    output_nam = Path(segment_paths[0]).name
    output_path = Path(segment_paths[0]).parent.parent / \
        f"{output_nam}combined.wav"
    print(f'\n\ncombining!\n\n{segment_paths}\n\n')
    with wave.open(str(output_path), 'w') as outfile:
        # Initialize parameters
        for _, segment_path in enumerate(segment_paths):
            with wave.open(segment_path, 'r') as infile:
                if not outfile.getnframes():
                    outfile.setparams(infile.getparams())
                outfile.writeframes(infile.readframes(infile.getnframes()))

    home = os.path.expanduser("~")
    # Construct the path to the user's download folder based on the OS
    download_folder = os.path.join(home, "Downloads")
    outfile_finished = os.path.join(
        download_folder, f"{output_nam}combined_output.wav")
    shutil.copyfile(output_path, outfile_finished)
    return outfile_finished


def convert_json_format(input_filename, output_filename):
    """
    Converts a JSON file from a complex nested structure to a simplified
    structure focusing on words, their start, and end times.

    @param input_filename: Path to the input JSON file.
    @param output_filename: Path where the converted JSON is saved.
    """
    with open(input_filename, 'r', encoding='utf-8') as infile:
        data = json.load(infile)

    simplified_data = []
    for segment in data.get('segments', []):
        for word_info in segment.get('words', []):
            simplified_data.append({
                "word": word_info['word'].strip(r"',.\"-_/`?!; ").lower(),
                "start": word_info['start'],
                "end": word_info['end'],
                'probability': word_info['probability']
            })

    with open(output_filename, 'w', encoding='utf-8') as outfile:
        json.dump(simplified_data, outfile, indent=4)

    print(
        f'The data has been successfully converted and saved to: {output_filename}')
    return simplified_data, output_filename


def process_audio(audio_file, transcript_file=None):
    """
     Process audio and transcribe it to wav. This is the main function of the program. It takes the audio file and transcribes it using transcript_file if it is not provided.

     @param audio_file - path to audio file to be transcribed
     @param transcript_file - path to transcript file. If not provided it will be transcribed

     @return path to audio file with processed
    """
    global processed_paths
    print('converting to stereo')
    print('reading audio')
    audio_obj = NumpyMono(audio_file)
    print('process json')
    results, clean_json = convert_json_format(
        transcript_file, f'{transcript_file}_new.json')
    print('find curse words')
    audio_obj.np_array = find_curse_words(
        audio_obj.np_array, audio_obj.sample_rate, results)
    print('exporting file now....')
    audio_obj.numpy_to_wav()
    return audio_obj.output_file_name, clean_json
