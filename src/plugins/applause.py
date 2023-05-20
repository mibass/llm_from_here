from pydub import AudioSegment
import random
import sys
import os


def generate_applause(duration, start, end, variation):
    """
    Generate an AudioSegment containing applause of a specified duration.

    The function works by looping over a segment of a pre-existing applause sound file,
    adding some variation to the start and end points of the loop to make the sound more natural.
    It also applies a fade-out effect over the last 10% of the duration.

    Parameters:
    duration (int): The duration of the applause in milliseconds.
    start (int): The start point of the segment to loop in the sound file, in milliseconds.
    end (int): The end point of the segment to loop in the sound file, in milliseconds.
    variation (int): The maximum amount of variation, in milliseconds, for the start and end points of each loop.

    Returns:
    AudioSegment: The generated applause sound.
    """
    # Load a applause sample
    script_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    applause_file_path = os.path.join(
        script_path, "../resources/277021__sandermotions__applause-2.wav")
    with open(applause_file_path, 'rb') as f:
        applause = AudioSegment.from_wav(f)

    # Initialize an empty AudioSegment for the final sound
    extended_applause = AudioSegment.empty()

    while len(extended_applause) < duration:
        # Choose random start and end points within the specified boundaries
        random_start = random.randint(
            max(start - variation, 0), start + variation)
        random_end = random.randint(
            end - variation, min(end + variation, len(applause)))

        # Extract the desired portion of the applause
        applause_portion = applause[random_start:random_end]

        # Add this portion to the final sound
        extended_applause += applause_portion

    # If the sound is longer than the specified duration, trim it
    if len(extended_applause) > duration:
        extended_applause = extended_applause[:duration]

    # Calculate the fade-out duration as 10% of the total duration
    fade_duration = duration // 10

    # Apply a fade-out effect
    extended_applause = extended_applause.fade_out(fade_duration)

    # Return the final sound
    return extended_applause

    # # Export to a new file
    # extended_applause.export(filename, format="wav")
