
**Setup**

*.env*

This uses dotenv to set environment variables. Keys are needed for:
* google v3 youtube api
* freesound api
* openai


**TODO:**

*Bugs:*
* mismatched intros to segments

*showrunner:*
* add YAML schema validation


*Audio:*
* Add continuous audience background noise
* Improve applause overlaps and tail
* Investigate aubio for onset detection and detecting music starts: https://github.com/aubio/aubio/tree/master/python/demos
* Investigate compression in pydub
* in the intro, after the spoken intro is done, ramp the gain of the background music back up

*TTS:*
* reduce uhhs in bark
* optimize bark parameters


*Segment ideas:*
* story
* interview
* improv scene

*prompts:*

*segment intros:*
* use gpt to parse search query and YT title to generate one sentence intro using a prompt like this:
```
Given a youtube search query  and a title for a video found using it, formatted like "query:::title", come up with a one sentence introduction for a host to read before the video plays. An example is:

 Cheryl Strayed (monologue|story|reading|"live from here"):::Interview Cheryl Strayed Reese Witherspoon WILD

and the generated introduction would look like:

"Ladies and gentleman, and interview with Cheryl Strayed and Reese Witherspoon about the movie Wild"

Now make an introduction for this one:
John Mulaney ("stand up"|"live from here"):::John Mulaney Stand-Up Monologue - SNL
```


*YT search*:
* for search, add support for topicId filters https://developers.google.com/youtube/v3/docs/search/list#topicId
* add sorting by rating or viewCount https://developers.google.com/youtube/v3/docs/search/list#order
* add support for videoDuration filters: https://developers.google.com/youtube/v3/docs/search/list#videoDuration


