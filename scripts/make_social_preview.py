#!/usr/bin/env python3
"""
Generate a 1280x640 Social Preview card for the AssistantProfessorJobScraper repository
following GitHub's social preview card template and specifications.
"""

import io
import math
import os
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH = 1280
HEIGHT = 640
SAFE_MARGIN = 60  # 40pt safe border margin to ensure zero cropping

def get_font(font_name: str, size: int):
    font_paths = [
        f"C:/Windows/Fonts/{font_name}.ttf",
        f"C:/Windows/Fonts/{font_name}.TTF",
        f"{font_name}.ttf",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

def fetch_github_mark(size: int = 56) -> Image.Image:
    """Download official GitHub mark or fallback to crisp vector drawing."""
    url = "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            return img
    except Exception:
        pass

    # Fallback: Draw clean circular mark
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([(2, 2), (size - 2, size - 2)], fill=(15, 23, 42, 255))
    return img

def create_social_preview(output_path: str = "social_preview.png"):
    # 1. Base canvas with subtle refined modern background
    img = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Subtle modern background gradient
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(250 + (245 - 250) * ratio)
        g = int(252 + (248 - 252) * ratio)
        b = int(255 + (252 - 255) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))

    # Decorative subtle top accent bar (gradient: Indigo -> Blue -> Emerald)
    accent_height = 8
    for x in range(WIDTH):
        t = x / WIDTH
        if t < 0.5:
            local_t = t / 0.5
            r = int(79 + (37 - 79) * local_t)
            g = int(70 + (99 - 70) * local_t)
            b = int(229 + (235 - 229) * local_t)
        else:
            local_t = (t - 0.5) / 0.5
            r = int(37 + (16 - 37) * local_t)
            g = int(99 + (185 - 99) * local_t)
            b = int(235 + (129 - 235) * local_t)
        draw.line([(x, 0), (x, accent_height)], fill=(r, g, b, 255))

    # Inner Card with rounded border and soft shadow
    card_x0, card_y0 = SAFE_MARGIN, SAFE_MARGIN + 10
    card_x1, card_y1 = WIDTH - SAFE_MARGIN, HEIGHT - SAFE_MARGIN
    card_radius = 24

    # Soft ambient drop shadow under the card
    shadow_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.rounded_rectangle(
        [(card_x0 + 4, card_y0 + 10), (card_x1 - 4, card_y1 + 8)],
        radius=card_radius,
        fill=(15, 23, 42, 28),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(16))
    img.paste(shadow_layer, (0, 0), shadow_layer)

    # Draw Inner Card
    draw.rounded_rectangle(
        [(card_x0, card_y0), (card_x1, card_y1)],
        radius=card_radius,
        fill=(255, 255, 255, 255),
        outline=(226, 232, 240, 255),
        width=2,
    )

    # 2. Header Area: GitHub Logo + "GitHub" or repo path
    logo_size = 52
    gh_logo = fetch_github_mark(logo_size)
    
    font_bold = get_font("segoeuib", 40)
    font_title = get_font("segoeuib", 48)
    font_subtitle = get_font("segoeuib", 24)
    font_desc = get_font("segoeui", 22)
    font_badge = get_font("segoeuib", 16)
    font_meta = get_font("segoeuisl", 18)

    # Top brand row inside card (centered horizontally)
    header_y = card_y0 + 44
    gh_text = "GitHub"
    gh_text_bbox = font_bold.getbbox(gh_text)
    gh_text_w = gh_text_bbox[2] - gh_text_bbox[0]
    total_header_w = logo_size + 14 + gh_text_w
    header_x0 = (WIDTH - total_header_w) // 2

    # Paste GitHub Logo
    img.paste(gh_logo, (header_x0, header_y), gh_logo)
    # Draw GitHub text
    draw.text((header_x0 + logo_size + 14, header_y + 4), gh_text, fill=(15, 23, 42, 255), font=font_bold)

    # Repo breadcrumb / category pill
    pill_text = "ACADEMIC FACULTY JOB AGGREGATOR & AI ADVISOR"
    pill_bbox = font_badge.getbbox(pill_text)
    pill_w = pill_bbox[2] - pill_bbox[0] + 28
    pill_h = 32
    pill_x = (WIDTH - pill_w) // 2
    pill_y = header_y + logo_size + 24

    draw.rounded_rectangle(
        [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
        radius=16,
        fill=(238, 242, 255, 255),
        outline=(199, 210, 254, 255),
        width=1,
    )
    draw.text((pill_x + 14, pill_y + 6), pill_text, fill=(67, 56, 202, 255), font=font_badge)

    # 3. Main Title
    title_text = "Assistant Professor Job Scraper"
    title_bbox = font_title.getbbox(title_text)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (WIDTH - title_w) // 2
    title_y = pill_y + pill_h + 20
    draw.text((title_x, title_y), title_text, fill=(15, 23, 42, 255), font=font_title)

    # 4. Description paragraph (centered, 2 clean lines)
    desc_line1 = "Daily automated scraping across 5 job boards with dynamic CV matching,"
    desc_line2 = "calibrated 1–10 candidate fit scoring, and interactive global mapping."
    
    bbox1 = font_desc.getbbox(desc_line1)
    bbox2 = font_desc.getbbox(desc_line2)
    w1 = bbox1[2] - bbox1[0]
    w2 = bbox2[2] - bbox2[0]

    desc_y1 = title_y + 64
    desc_y2 = desc_y1 + 32
    draw.text(((WIDTH - w1) // 2, desc_y1), desc_line1, fill=(71, 85, 105, 255), font=font_desc)
    draw.text(((WIDTH - w2) // 2, desc_y2), desc_line2, fill=(71, 85, 105, 255), font=font_desc)

    # 5. Feature Badges at bottom of card
    badges = [
        ("5 Job Boards", (241, 245, 249), (71, 85, 105), (203, 213, 225)),
        ("Google Gemini AI", (236, 253, 245), (4, 120, 87), (167, 243, 208)),
        ("Dynamic CV Matching", (254, 242, 242), (185, 28, 28), (254, 202, 202)),
        ("Interactive Map & Sheets", (239, 246, 255), (29, 78, 216), (191, 219, 254)),
    ]

    badge_h = 36
    badge_widths = []
    for text, _, _, _ in badges:
        bb = font_badge.getbbox(text)
        badge_widths.append(bb[2] - bb[0] + 32)

    total_badges_w = sum(badge_widths) + (len(badges) - 1) * 16
    start_bx = (WIDTH - total_badges_w) // 2
    badge_y = desc_y2 + 54

    curr_bx = start_bx
    for idx, (text, bg_col, text_col, border_col) in enumerate(badges):
        bw = badge_widths[idx]
        draw.rounded_rectangle(
            [(curr_bx, badge_y), (curr_bx + bw, badge_y + badge_h)],
            radius=18,
            fill=(*bg_col, 255),
            outline=(*border_col, 255),
            width=1,
        )
        t_bb = font_badge.getbbox(text)
        tw = t_bb[2] - t_bb[0]
        draw.text((curr_bx + (bw - tw) // 2, badge_y + 8), text, fill=(*text_col, 255), font=font_badge)
        curr_bx += bw + 16

    # Save image
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    img_rgb = img.convert("RGB")
    img_rgb.save(output_path, "PNG", quality=100, optimize=True)
    print(f"Successfully generated social preview at: {os.path.abspath(output_path)}")
    print(f"Dimensions: {img_rgb.width} x {img_rgb.height} px")

if __name__ == "__main__":
    create_social_preview("social_preview.png")
