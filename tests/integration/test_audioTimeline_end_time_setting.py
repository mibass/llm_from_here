import os
from pydub import AudioSegment
import tempfile
import pytest
from llm_from_here.plugins.audioTimeline import AudioTimeline, SegmentLabel
from tabulate import tabulate
from conftest import generate_noisy_audio

@pytest.mark.parametrize(
    "entries,durations,labels,expected_start_times,expected_end_times",
    [
        (
            [2000],  # Entries (duration of generated noisy audio)
            [None],  # Durations (to slice or loop to)
            [SegmentLabel.BACKGROUND],  # Labels
            [0],  # Expected start times
            [0],  # Expected end times
        ),
        (
            [2000], 
            [None], 
            [SegmentLabel.FOREGROUND],  
            [0],  
            [2000], 
        ),
        (
            [1000, 3000],  
            [None, None],
            [SegmentLabel.FOREGROUND, SegmentLabel.BACKGROUND],
            [0, 1000],
            [1000, 1000],
        ),
        (
            [2000, 3000, 4000, 1000],  
            [None, None, None, None],
            [SegmentLabel.BACKGROUND, SegmentLabel.FOREGROUND, SegmentLabel.BACKGROUND, SegmentLabel.FOREGROUND],
            [0   ,    0, 3000, 3000],
            [3000, 3000, 4000, 4000],
        ),
        (
            [2000, 3000, 4000],  
            [1000, 1000, 1000],
            [SegmentLabel.BACKGROUND, SegmentLabel.FOREGROUND, SegmentLabel.BACKGROUND],
            [0, 0, 1000],
            [1000, 1000, 1000],
        ),
    ],
)
def test_integration_add_entries_and_render(
    entries,
    durations,
    labels,
    expected_start_times,
    expected_end_times
):
    # Create a temporary output folder
    with tempfile.TemporaryDirectory() as temp_dir:
        output_folder = temp_dir

        # Create an instance of AudioTimeline
        audio_timeline = AudioTimeline(global_results={"output_folder": output_folder})

        # Add the entries to the timeline
        for entry, duration, label in zip(entries, durations, labels):
            audio_segment = generate_noisy_audio(entry)
            audio_timeline.add_after_previous(
                audio_segment, label=label, duration=duration
            )

        # Render the timeline
        output_filename = os.path.join(output_folder, "output.wav")
        audio_timeline.render(output_filename, format="wav")

        # Verify the start and end times of the entries
        timeline = audio_timeline.timeline
        # Print the timeline as formatted tabular data
        print(tabulate(timeline, headers="keys", tablefmt="github"))

        assert len(timeline) == len(entries)

        for i, entry in enumerate(timeline):
            assert entry["start_time"] == expected_start_times[i]
            assert entry["end_time"] == expected_end_times[i]



        # Verify that the rendered audio file exists
        if timeline[-1]["end_time"] > 0:
            assert os.path.isfile(output_filename)