# FILE: src/generator.py
# Autonomous Video & Content Generator for Personal Finance & Wealth Psychology

import os
import json
import time
import random
import requests
from io import BytesIO
from google import genai
from gtts import gTTS
from gtts.tts import gTTSError
from moviepy.editor import AudioFileClip, ImageClip, CompositeAudioClip, concatenate_videoclips, vfx
from moviepy.config import change_settings
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
from pydub import AudioSegment

# --- Configuration ---
ASSETS_PATH = Path("assets")
FONT_FILE = ASSETS_PATH / "fonts/arial.ttf"
BACKGROUND_MUSIC_PATH = ASSETS_PATH / "music/bg_music.mp3"
FALLBACK_THUMBNAIL_FONT = ImageFont.load_default()

CHANNEL_BRAND = os.getenv("CHANNEL_BRAND", "Wealth Blueprint")
PRESENTER_NAME = os.getenv("PRESENTER_NAME", "Alex")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Google's TTS endpoint rate-limit protection
TTS_MAX_ATTEMPTS = 5
TTS_BACKOFF_SECONDS = 5
TTS_MIN_GAP_SECONDS = 2
_last_tts_request = 0.0

# GitHub Actions compatibility for ImageMagick
if os.name == 'posix':
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})


def get_stock_image(query, video_type):
    """
    Fetches relevant stock imagery using Pixabay (primary) or Pexels (secondary).
    Returns a PIL Image object or None.
    """
    orientation_pixabay = 'horizontal' if video_type == 'long' else 'vertical'
    orientation_pexels = 'landscape' if video_type == 'long' else 'portrait'

    # 1. Try Pixabay API (checks PIXABAY_API_KEY or fallback to PEXELS_API_KEY slot)
    pixabay_api_key = os.getenv("PIXABAY_API_KEY") or os.getenv("PEXELS_API_KEY")
    if pixabay_api_key:
        try:
            params = {
                "key": pixabay_api_key,
                "q": f"finance {query}",
                "image_type": "photo",
                "orientation": orientation_pixabay,
                "safesearch": "true",
                "per_page": 3
            }
            res = requests.get("https://pixabay.com/api/", params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if data.get("hits") and len(data["hits"]) > 0:
                    image_url = data["hits"][0].get("largeImageURL") or data["hits"][0].get("webformatURL")
                    if image_url:
                        img_res = requests.get(image_url, timeout=12)
                        img_res.raise_for_status()
                        return Image.open(BytesIO(img_res.content)).convert("RGBA")
        except Exception as e:
            print(f"⚠️ Pixabay search note for '{query}': {e}")

    # 2. Try Pexels API
    pexels_api_key = os.getenv("PEXELS_API_KEY")
    if pexels_api_key:
        try:
            headers = {"Authorization": pexels_api_key}
            params = {"query": f"business {query}", "per_page": 1, "orientation": orientation_pexels}
            response = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=12)
            if response.status_code == 200:
                data = response.json()
                if data.get('photos') and len(data['photos']) > 0:
                    image_url = data['photos'][0]['src']['large2x']
                    image_response = requests.get(image_url, timeout=12)
                    image_response.raise_for_status()
                    return Image.open(BytesIO(image_response.content)).convert("RGBA")
        except Exception as e:
            print(f"⚠️ Pexels search note for '{query}': {e}")

    return None


def _throttle_tts():
    """Spaces out TTS requests to avoid triggering rate limiters."""
    global _last_tts_request
    elapsed = time.monotonic() - _last_tts_request
    if elapsed < TTS_MIN_GAP_SECONDS:
        time.sleep(TTS_MIN_GAP_SECONDS - elapsed)
    _last_tts_request = time.monotonic()


def text_to_speech(text, output_path):
    """Converts script to speech using clean PCM 16-bit WAV audio."""
    print(f"🎤 Converting script to speech...")
    temp_mp3_path = str(output_path).replace('.mp3', '_temp.mp3')
    wav_path = str(output_path.with_suffix('.wav'))

    for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
        try:
            _throttle_tts()
            tts = gTTS(text=text, lang='en', tld='com', slow=False)
            tts.save(temp_mp3_path)

            if os.path.getsize(temp_mp3_path) < 1024:
                raise gTTSError("gTTS wrote an empty or truncated audio file.")

            audio = AudioSegment.from_mp3(temp_mp3_path)
            audio.export(wav_path, format="wav", codec="pcm_s16le")
            if os.path.exists(temp_mp3_path):
                os.remove(temp_mp3_path)

            print(f"✅ Speech generated and converted to WAV successfully!")
            return Path(wav_path)

        except Exception as e:
            if os.path.exists(temp_mp3_path):
                os.remove(temp_mp3_path)

            if attempt == TTS_MAX_ATTEMPTS:
                print(f"❌ ERROR: Failed to generate speech after {TTS_MAX_ATTEMPTS} attempts: {e}")
                raise

            delay = TTS_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 2)
            print(f"⚠️ TTS attempt {attempt}/{TTS_MAX_ATTEMPTS} failed ({e}). Retrying in {delay:.1f}s...")
            time.sleep(delay)


def _call_gemini_with_fallback(prompt):
    """Calls Gemini API using the modern google-genai SDK with model fallback."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    models_to_try = [DEFAULT_GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-flash"]
    # De-duplicate while preserving order
    seen = set()
    models = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_error = None
    for model_name in models:
        try:
            print(f"🤖 Querying Gemini model: {model_name}...")
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                return response.text
        except Exception as err:
            print(f"⚠️ Model {model_name} failed: {err}. Trying fallback...")
            last_error = err

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


def generate_curriculum(previous_titles=None):
    """Generates an automated high-RPM personal finance curriculum."""
    print("🤖 Generating new high-RPM Personal Finance & Wealth curriculum...")
    history = ""
    if previous_titles:
        formatted = "\n".join([f"{i+1}. {t}" for i, t in enumerate(previous_titles)])
        history = f"The following topics have already been covered:\n{formatted}\n\nPlease generate 20 NEW, fresh, high-impact topics continuing this series.\n"

    prompt = f"""
    You are a world-class financial analyst, behavioral economist, and YouTube strategist (inspired by Morgan Housel's 'Psychology of Money' and Ray Dalio).
    {history}
    Create a curriculum for a YouTube channel called '{CHANNEL_BRAND}'.
    Target Audience: High-RPM English viewers (US, UK, Canada, Australia) interested in Personal Finance, Wealth Building, Money Psychology, and Business Breakdowns.

    Format requirements:
    - Respond with ONLY a valid JSON object.
    - The object must contain a key "lessons" which is a list of 20 lesson objects.
    - Each lesson object must contain:
      "chapter": integer (sequential),
      "part": 1,
      "title": punchy, curiosity-driven, high-CTR YouTube title (e.g. 'How McDonald\\'s Actually Makes Billions: The Secret Real Estate Model'),
      "status": "pending",
      "youtube_id": null
    """
    raw_text = _call_gemini_with_fallback(prompt)
    json_string = raw_text.strip().replace("```json", "").replace("```", "").strip()
    curriculum = json.loads(json_string)
    print("✅ New finance curriculum generated successfully!")
    return curriculum


def generate_lesson_content(lesson_title):
    """Generates slides, narration script, shorts highlight, and tags for a finance topic."""
    print(f"🤖 Generating lesson script & breakdown for: '{lesson_title}'...")
    prompt = f"""
    You are the lead financial analyst and narrator for '{CHANNEL_BRAND}'.
    The topic for today's episode is: '{lesson_title}'.

    Your style:
    - Highly engaging, authoritative, clear, and story-driven.
    - Use clear real-world examples, psychological triggers, and practical financial takeaways.
    - Avoid dry textbook jargon; explain concepts so anyone can understand while respecting their intelligence.

    Generate a JSON response with exactly three keys:
    1. "long_form_slides": A list of 6 to 8 slide objects for the video.
       Each object must have:
       - "title": A concise slide heading (3 to 6 words).
       - "content": 2 to 3 bullet points or short conversational sentences (approx 25-45 words total) delivered with high storytelling energy.
    2. "short_form_highlight": A punchy, viral 1-2 sentence hook + insight designed for YouTube Shorts (approx 20-30 seconds spoken).
    3. "hashtags": 5 to 7 high-RPM finance hashtags (e.g., "#PersonalFinance #MoneyPsychology #WealthBuilding #FinancialFreedom #Investing").

    Return ONLY raw valid JSON. Do not include markdown codeblocks or extra text.
    """
    raw_text = _call_gemini_with_fallback(prompt)
    json_string = raw_text.strip().replace("```json", "").replace("```", "").strip()
    content = json.loads(json_string)
    print("✅ Finance content generated successfully.")
    return content


def generate_visuals(output_dir, video_type, slide_content=None, thumbnail_title=None, slide_number=0, total_slides=0):
    """Generates elegant, dark-mode financial slides and thumbnails."""
    output_dir.mkdir(exist_ok=True, parents=True)
    is_thumbnail = thumbnail_title is not None

    width, height = (1920, 1080) if video_type == 'long' else (1080, 1920)
    title = thumbnail_title if is_thumbnail else slide_content.get("title", "")

    # Fetch stock background image or generate premium financial dark theme
    bg_image = get_stock_image(title, video_type)

    if not bg_image:
        # Premium dark slate / obsidian financial gradient background
        bg_image = Image.new('RGBA', (width, height), color=(15, 23, 42))  # Slate 900
    else:
        bg_image = bg_image.resize((width, height)).filter(ImageFilter.GaussianBlur(6))

    # Dark overlay to guarantee high contrast readability
    darken_layer = Image.new('RGBA', bg_image.size, (11, 15, 25, 195))
    final_bg = Image.alpha_composite(bg_image, darken_layer).convert("RGB")

    if is_thumbnail and video_type == 'long':
        w, h = final_bg.size
        if h > w:
            final_bg = final_bg.transpose(Image.ROTATE_270).resize((1920, 1080))

    draw = ImageDraw.Draw(final_bg)

    try:
        title_font = ImageFont.truetype(str(FONT_FILE), 75 if video_type == 'long' else 85)
        content_font = ImageFont.truetype(str(FONT_FILE), 42 if video_type == 'long' else 50)
        footer_font = ImageFont.truetype(str(FONT_FILE), 24 if video_type == 'long' else 32)
    except IOError:
        title_font = content_font = footer_font = FALLBACK_THUMBNAIL_FONT

    if is_thumbnail:
        # High CTR Thumbnail Styling
        # Emerald / Gold accent line on top
        draw.rectangle([0, 0, width, 16], fill=(16, 185, 129))  # Emerald-500

        # Wrap title for thumbnail
        words = title.split()
        thumb_lines = []
        cur_line = ""
        for word in words:
            test = f"{cur_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=title_font)
            if bbox[2] - bbox[0] < width * 0.85:
                cur_line = test
            else:
                thumb_lines.append(cur_line)
                cur_line = word
        thumb_lines.append(cur_line)

        line_h = title_font.getbbox("A")[3] + 20
        total_h = len(thumb_lines) * line_h
        y_pos = (height - total_h) / 2

        for line in thumb_lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            x_pos = (width - (bbox[2] - bbox[0])) / 2
            # Drop shadow
            draw.text((x_pos + 4, y_pos + 4), line, font=title_font, fill=(0, 0, 0))
            draw.text((x_pos, y_pos), line, font=title_font, fill=(255, 255, 255))
            y_pos += line_h

    else:
        # Standard Slide Layout
        header_height = int(height * 0.17)
        # Deep blue-gray header background
        draw.rectangle([0, 0, width, header_height], fill=(30, 41, 59, 230))
        # Subtle emerald accent stripe below header
        draw.rectangle([0, header_height, width, header_height + 6], fill=(16, 185, 129))

        # Title formatting
        words = title.split()
        title_lines = []
        cur = ""
        for word in words:
            test = f"{cur} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=title_font)
            if bbox[2] - bbox[0] < width * 0.88:
                cur = test
            else:
                title_lines.append(cur)
                cur = word
        title_lines.append(cur)

        line_h = title_font.getbbox("A")[3] + 12
        total_th = len(title_lines) * line_h
        y_text = (header_height - total_th) / 2

        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            x = (width - (bbox[2] - bbox[0])) / 2
            draw.text((x, y_text), line, font=title_font, fill=(255, 255, 255))
            y_text += line_h

        # Content formatting
        content = slide_content.get("content", "")
        is_special_slide = len(content.split()) < 10

        c_words = content.split()
        c_lines = []
        c_cur = ""
        for word in c_words:
            test = f"{c_cur} {word}".strip()
            if draw.textbbox((0, 0), test, font=content_font)[2] < width * 0.82:
                c_cur = test
            else:
                c_lines.append(c_cur)
                c_cur = word
        c_lines.append(c_cur)

        c_line_h = content_font.getbbox("A")[3] + 18
        total_ch = len(c_lines) * c_line_h
        y_content = (height - total_ch) / 2 if is_special_slide else header_height + 100

        for line in c_lines:
            bbox = draw.textbbox((0, 0), line, font=content_font)
            x = (width - (bbox[2] - bbox[0])) / 2
            draw.text((x, y_content), line, font=content_font, fill=(241, 245, 249))
            y_content += c_line_h

        # Footer
        footer_height = int(height * 0.06)
        draw.rectangle([0, height - footer_height, width, height], fill=(15, 23, 42, 230))
        draw.text((40, height - footer_height + 14), f"{CHANNEL_BRAND} | Financial Intelligence", font=footer_font, fill=(148, 163, 184))

        if total_slides > 0:
            slide_num_text = f"Part {slide_number} of {total_slides}"
            bbox = draw.textbbox((0, 0), slide_num_text, font=footer_font)
            draw.text((width - bbox[2] - 40, height - footer_height + 14), slide_num_text, font=footer_font, fill=(148, 163, 184))

    file_prefix = "thumbnail" if is_thumbnail else f"slide_{slide_number:02d}"
    path = output_dir / f"{file_prefix}.png"
    final_bg.save(path)
    return str(path)


def create_video(slide_paths, audio_paths, output_path, video_type):
    """Renders the final MP4 video combining slides, audio, and background music."""
    print(f"🎬 Creating {video_type} video...")
    try:
        if not slide_paths or not audio_paths or len(slide_paths) != len(audio_paths):
            raise ValueError("Mismatch between slides and audio clips, or no slides provided.")

        image_clips = []
        for i, (img_path, audio_path) in enumerate(zip(slide_paths, audio_paths)):
            audio_clip = AudioFileClip(str(audio_path))
            duration = audio_clip.duration + 0.5  # Padding
            img_clip = (
                ImageClip(img_path)
                .set_duration(duration)
                .set_audio(audio_clip)
                .fadein(0.4)
                .fadeout(0.4)
            )
            image_clips.append(img_clip)

        final_video = concatenate_videoclips(image_clips, method="compose")

        if BACKGROUND_MUSIC_PATH.exists():
            print("🎵 Adding background music...")
            bg_music = AudioFileClip(str(BACKGROUND_MUSIC_PATH)).volumex(0.04)
            if bg_music.duration < final_video.duration:
                bg_music = bg_music.fx(vfx.loop, duration=final_video.duration)
            else:
                bg_music = bg_music.subclip(0, final_video.duration)

            composite_audio = CompositeAudioClip([
                final_video.audio.volumex(1.2),
                bg_music
            ])
            final_video = final_video.set_audio(composite_audio)

        final_video.write_videofile(
            str(output_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="192k",
            preset="medium",
            threads=4
        )
        print(f"✅ {video_type.capitalize()} video created successfully!")

    except Exception as e:
        print(f"❌ ERROR during video creation: {e}")
        raise
