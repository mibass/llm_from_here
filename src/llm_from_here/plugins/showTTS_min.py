
import numpy as np

from bark import SAMPLE_RATE, generate_audio, preload_models
from scipy.io.wavfile import write as write_wav

    
    
#are we in main?
if __name__ == "__main__":
    import sys
    #get command line args
    text = sys.argv[1]
    speed = sys.argv[2]
    output_file = sys.argv[3]
    
    
    MODEL_SETTINGS = {'text_use_small':True,
                'coarse_use_small':True,
                'fine_use_small':True,
                'text_use_gpu':False,
                'coarse_use_gpu':False,
                'fine_use_gpu':False,
                }
    preload_models(**MODEL_SETTINGS)
    
    GEN_TEMP = 0.5
    SPEAKER = "v2/en_speaker_6"
    audio_array = generate_audio(text, history_prompt=SPEAKER, text_temp=GEN_TEMP)
    write_wav(output_file, SAMPLE_RATE, audio_array)
