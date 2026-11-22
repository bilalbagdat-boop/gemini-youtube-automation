import os
import re
import sys
import json
import datetime
import time
import traceback
from pathlib import Path
from src.generator import (
    generate_curriculum,
    generate_lesson_content,
    text_to_speech,
    generate_visuals,
    create_video,
    CHANNEL_BRAND,
    PRESENTER_NAME
)
from src.uploader import upload_to_youtube

CONTENT_PLAN_FILE = Path("content_plan.json")
OUTPUT_DIR = Path("output")
LESSONS_PER_RUN = 1


def get_content_plan():
    if not CONTENT_PLAN_FILE.exists():
        print("📄 content_plan.json not found. Generating new curriculum...")
        new_plan = generate_curriculum()
        with open(CONTENT_PLAN_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_plan, f, indent=2, ensure_ascii=False)
        print(f"✅ New curriculum saved to {CONTENT_PLAN_FILE}")
        return new_plan
    else:
        try:
            with open(CONTENT_PLAN_FILE, 'r', encoding='utf-8') as f:
                plan = json.load(f)
            if not plan.get("lessons") or not isinstance(plan["lessons"], list):
                raise ValueError("⚠️ Invalid or empty lesson plan detected.")
            return plan
        except Exception as e:
            print(f"❌ ERROR loading existing plan: {e}. Regenerating...")
            new_plan = generate_curriculum()
            with open(CONTENT_PLAN_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_plan, f, indent=2, ensure_ascii=False)
            return new_plan


def update_content_plan(plan):
    with open(CONTENT_PLAN_FILE, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)


def produce_lesson_videos(lesson):
    print(f"\n▶️ Starting production for Episode: '{lesson['title']}'")
    chapter_safe = re.sub(r'[^\w]', '_', str(lesson['chapter'])).strip('_')
    part_safe = re.sub(r'[^\w]', '_', str(lesson['part'])).strip('_')
    unique_id = f"{datetime.datetime.now().strftime('%Y%m%d')}_{chapter_safe}_{part_safe}"

    lesson_content = generate_lesson_content(lesson['title'])

    print("\n--- Producing Long-Form Video ---")

    intro_slide = {
        "title": lesson['title'],
        "content": f"Episode {lesson['chapter']} • {CHANNEL_BRAND}\nMastering Money & Financial Intelligence"
    }
    outro_slide = {
        "title": "Build Your Wealth",
        "content": f"Subscribe to {CHANNEL_BRAND} for daily breakdowns on personal finance, money psychology, and financial freedom."
    }
    all_slides = [intro_slide] + lesson_content['long_form_slides'] + [outro_slide]

    slide_scripts = [
        f"Welcome back to {CHANNEL_BRAND}. In today's episode, we break down: {lesson['title']}.",
        *[s['content'] for s in lesson_content['long_form_slides']],
        f"Thank you for watching. If you found this breakdown valuable, hit the subscribe button and like the video to support {CHANNEL_BRAND}."
    ]

    slide_audio_paths = []
    for i, script in enumerate(slide_scripts):
        audio_path = OUTPUT_DIR / f"audio_slide_{i+1}_{unique_id}.mp3"
        wav_path = text_to_speech(script, audio_path)
        slide_audio_paths.append(wav_path)
    print(f"🎧 Total slide audios generated: {len(slide_audio_paths)}")

    slide_dir = OUTPUT_DIR / f"slides_long_{unique_id}"
    slide_paths = []
    for i, slide in enumerate(all_slides):
        path = generate_visuals(
            output_dir=slide_dir,
            video_type='long',
            slide_content=slide,
            slide_number=i + 1,
            total_slides=len(all_slides)
        )
        slide_paths.append(path)

    long_video_path = OUTPUT_DIR / f"long_video_{unique_id}.mp4"
    print(f"🎥 Creating long-form video at: {long_video_path}")
    create_video(slide_paths, slide_audio_paths, long_video_path, 'long')

    long_thumb_path = generate_visuals(
        output_dir=OUTPUT_DIR,
        video_type='long',
        thumbnail_title=lesson['title']
    )

    print("\n--- Producing YouTube Short ---")
    short_highlight = (lesson_content.get('short_form_highlight') or '').strip()
    short_script = f"{short_highlight}\n\nSubscribe to {CHANNEL_BRAND} for more daily wealth insights."
    short_audio_mp3_path = OUTPUT_DIR / f"short_audio_{unique_id}.mp3"
    short_audio_path = text_to_speech(short_script, short_audio_mp3_path)

    short_slide_dir = OUTPUT_DIR / f"slides_short_{unique_id}"
    short_slide_content = {
        "title": "Money Insight",
        "content": f"{short_highlight}\n\n#{CHANNEL_BRAND.replace(' ', '')}"
    }
    short_slide_path = generate_visuals(
        output_dir=short_slide_dir,
        video_type='short',
        slide_content=short_slide_content,
        slide_number=1,
        total_slides=1
    )

    short_video_path = OUTPUT_DIR / f"short_video_{unique_id}.mp4"
    print(f"🎥 Creating short video at: {short_video_path}")
    create_video([short_slide_path], [short_audio_path], short_video_path, 'short')

    short_thumb_path = generate_visuals(
        output_dir=OUTPUT_DIR,
        video_type='short',
        thumbnail_title=f"Money Tip: {lesson['title']}"
    )

    print("\n📤 Uploading to YouTube...")
    hashtags = lesson_content.get("hashtags", "#PersonalFinance #Investing #WealthBuilding")
    long_desc = (
        f"{lesson['title']}\n\n"
        f"Welcome to {CHANNEL_BRAND}. We simplify personal finance, business models, and money psychology to help you build lasting wealth.\n\n"
        f"📌 Subscribe for daily insights on financial freedom and smart money habits.\n\n"
        f"{hashtags}"
    )
    long_tags = f"Personal Finance, Money Psychology, Investing, Business Breakdown, Wealth Building, Economics, {lesson['title'].replace(' ', ', ')}"

    long_video_id = upload_to_youtube(
        long_video_path,
        lesson['title'],
        long_desc,
        long_tags,
        long_thumb_path
    )

    if long_video_id == "LOCAL_RENDER_ONLY":
        print("ℹ️ Videos rendered successfully in cloud! Skipping YouTube upload until OAuth credentials are provided.")
        return "LOCAL_RENDER_ONLY"

    if long_video_id:
        print("⏳ Waiting 30 seconds before uploading the short...")
        time.sleep(30)
        short_title = f"{short_highlight[:90].rstrip()} #Shorts"
        short_desc = (
            f"{short_highlight}\n\n"
            f"Watch the full breakdown on {CHANNEL_BRAND}: https://www.youtube.com/watch?v={long_video_id}\n\n"
            f"{hashtags}"
        )
        upload_to_youtube(
            short_video_path,
            short_title.strip(),
            short_desc,
            "PersonalFinance,Shorts,Wealth,MoneyTips",
            short_thumb_path
        )
        return long_video_id
    return None


def main():
    print(f"🚀 Starting Autonomous Video Production Pipeline for: {CHANNEL_BRAND}")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"📁 Output folder: {OUTPUT_DIR.resolve()}")

    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        plan = get_content_plan()
        pending = [(i, lesson) for i, lesson in enumerate(plan['lessons']) if lesson['status'] == 'pending']

        if not pending:
            print("🎉 All lessons produced! Generating new curriculum to continue series...")
            previous_titles = [lesson['title'] for lesson in plan['lessons']]
            new_plan = generate_curriculum(previous_titles=previous_titles)
            update_content_plan(new_plan)
            plan = new_plan
            pending = [(i, lesson) for i, lesson in enumerate(new_plan['lessons']) if lesson['status'] == 'pending']
            if not pending:
                print("⚠️ Curriculum generated but no pending lessons found.")
                return

        failed_lessons = []
        for lesson_index, lesson in pending[:LESSONS_PER_RUN]:
            try:
                video_id = produce_lesson_videos(lesson)
                if video_id:
                    for original_lesson in plan['lessons']:
                        if original_lesson['title'].strip().lower() == lesson['title'].strip().lower():
                            if video_id != "LOCAL_RENDER_ONLY":
                                original_lesson['status'] = 'complete'
                                original_lesson['youtube_id'] = video_id
                                print(f"✅ Completed episode and uploaded: {lesson['title']}")
                            else:
                                print(f"✅ Episode rendered successfully in cloud: {lesson['title']} (Upload pending YouTube credentials)")
                            break
                else:
                    print(f"❌ Upload failed (no video ID returned): {lesson['title']}")
                    failed_lessons.append(lesson['title'])
            except Exception as e:
                print(f"❌ Failed producing episode: {lesson['title']}")
                traceback.print_exc()
                failed_lessons.append(lesson['title'])
            finally:
                update_content_plan(plan)
                print("📦 Content plan saved.")

        if failed_lessons:
            print(f"\n❌ Pipeline finished with {len(failed_lessons)} failed episode(s).")
            sys.exit(1)

    except Exception as e:
        print("❌ Critical error in main()")
        traceback.print_exc()
        sys.exit(1)

    try:
        for file in OUTPUT_DIR.glob("*.wav"):
            file.unlink()
            print(f"🧹 Cleaned up: {file}")
    except Exception as e:
        print(f"⚠️ Could not clean up .wav files: {e}")


if __name__ == "__main__":
    main()
