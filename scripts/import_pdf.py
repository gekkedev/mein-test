import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF


BULLET_CHARS: tuple = (
    "\uf0a3",  # original dingbat
    "□",        # white square
    "◻",
    "▢",
    "☐",
    "▪",
    "■",
    "•",
)
PAGE_LABEL_PREFIX = "Seite "


def build_line_text(span: dict) -> str:
    if "text" in span and span["text"]:
        return span["text"]
    return "".join(char.get("c", "") for char in span.get("chars", []))


def split_inline_options(text: str) -> List[str]:
    stripped = text.strip()
    if not stripped:
        return []

    for bullet in BULLET_CHARS:
        if bullet in stripped and not stripped.startswith(bullet):
            parts = stripped.split(bullet)
            segments: List[str] = []
            head = parts.pop(0).strip()
            if head:
                segments.append(head)
            for option in parts:
                option_text = option.strip()
                if option_text:
                    segments.append(f"{bullet}{option_text}")
            if segments:
                return segments

    return [stripped]


def starts_with_bullet(text: str) -> Optional[str]:
    for bullet in BULLET_CHARS:
        if text.startswith(bullet):
            return bullet
    return None


def load_document_lines(pdf_path: Path) -> Dict[str, list]:
    doc = fitz.open(pdf_path)
    try:
        lines: List[dict] = []
        images_by_page: Dict[int, List[dict]] = {}

        for page_index, page in enumerate(doc, start=1):
            raw = page.get_text("rawdict")
            page_lines: List[dict] = []
            page_images: List[dict] = []

            for block in raw.get("blocks", []):
                block_type = block.get("type")

                if block_type == 0:  # text block
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        text_parts = [build_line_text(span) for span in spans]
                        text = "".join(text_parts).strip()

                        if not text:
                            continue

                        line_entry = {
                            "text": text,
                            "bbox": tuple(line.get("bbox", (0, 0, 0, 0))),
                            "page": page_index,
                        }
                        page_lines.append(line_entry)

                elif block_type == 1:  # image block
                    image_bytes: Optional[bytes] = block.get("image")
                    if not image_bytes:
                        continue

                    image_entry = {
                        "bbox": tuple(block.get("bbox", (0, 0, 0, 0))),
                        "ext": block.get("ext", "png") or "png",
                        "bytes": image_bytes,
                        "page": page_index,
                    }
                    page_images.append(image_entry)

            page_lines.sort(key=lambda entry: (entry["bbox"][1], entry["bbox"][0]))
            lines.extend(page_lines)
            images_by_page[page_index] = page_images

        return {"lines": lines, "images": images_by_page}
    finally:
        doc.close()


def update_bounds(bounds: dict, page: int, bbox: tuple) -> None:
    entry = bounds.setdefault(
        page,
        {
            "top": bbox[1],
            "bottom": bbox[3],
            "left": bbox[0],
            "right": bbox[2],
        },
    )
    entry["top"] = min(entry["top"], bbox[1])
    entry["bottom"] = max(entry["bottom"], bbox[3])
    entry["left"] = min(entry["left"], bbox[0])
    entry["right"] = max(entry["right"], bbox[2])


def merge_bullets_with_text(lines: List[dict]) -> List[dict]:
    """Merge standalone bullet characters with following text lines."""
    merged = []
    i = 0
    
    while i < len(lines):
        entry = lines[i]
        text = entry["text"]
        
        # Check if this is a standalone bullet
        bullet = starts_with_bullet(text)
        if bullet and text == bullet:
            # This is a bullet-only line
            # Try to look forward for text first (preferred method)
            if i + 1 < len(lines):
                next_entry = lines[i + 1]
                next_text = next_entry["text"]
                next_bullet = starts_with_bullet(next_text)
                
                # If next line doesn't start with a bullet AND is not a question header, merge them
                if not next_bullet and not next_text.strip().startswith("Aufgabe "):
                    merged_entry = {
                        "text": bullet + next_text,
                        "bbox": entry["bbox"],  # Use bullet's bbox
                        "page": entry["page"],
                    }
                    merged.append(merged_entry)
                    i += 2  # Skip both lines
                    continue
            
            # If forward merge failed, try backward ONLY for very specific patterns
            # Allow merging bullets with previous text if:
            # 1. Previous text is very short (like "Bild N")
            # 2. Previous text ends with a period and looks like an answer (not question text)
            if merged and not starts_with_bullet(merged[-1]["text"]):
                prev_text = merged[-1]["text"].strip()
                word_count = len(prev_text.split())
                is_image_label = prev_text.startswith("Bild ") and word_count == 2
                # Allow merge if it's an image label OR if it's a complete sentence ending with period
                # that's likely an answer (not too long to be question text)
                ends_with_period = prev_text.endswith(".")
                looks_like_answer = ends_with_period and 2 <= word_count <= 10
                
                if (word_count <= 2 and is_image_label) or looks_like_answer:
                    merged[-1] = {
                        "text": bullet + prev_text,
                        "bbox": entry["bbox"],  # Use bullet's bbox
                        "page": entry["page"],
                    }
                    i += 1  # Skip the bullet
                    continue
            
            # If we can't merge, KEEP the bullet as-is (don't skip)
            # The parsing logic will treat it as an answer with empty text
            merged.append(entry)
            i += 1
            continue
        
        merged.append(entry)
        i += 1
    
    return merged


def parse_questions(lines: List[dict]):
    # Merge standalone bullets with their text first
    lines = merge_bullets_with_text(lines)
    
    questions: List[dict] = []
    current_question: Optional[dict] = None
    current_section = {"part": None, "topic": None}

    i = 0
    while i < len(lines):
        entry = lines[i]
        raw_text = entry["text"].strip()

        if not raw_text:
            i += 1
            continue

        segments = split_inline_options(raw_text)

        if not segments:
            i += 1
            continue

        for segment in segments:
            text = segment

            if text.startswith(PAGE_LABEL_PREFIX):
                continue

            # Skip page numbers like "Seite 111 von 191" (with or without bullet prefix)
            text_without_bullet = text.lstrip("\uf0a3□◻▢☐▪■•").strip()
            if text_without_bullet.startswith("Seite ") and " von " in text_without_bullet:
                continue

            # Skip copyright notices (with or without bullet prefix)
            if text_without_bullet.startswith("©") or text_without_bullet.startswith("Â©"):
                continue

            if text.startswith("Teil "):
                current_section["part"] = text
                continue

            if text.startswith("Allgemeine Fragen") or text.startswith("Bundesland") or text.startswith("Fragen für das Bundesland"):
                current_section["topic"] = text
                continue

            if text.startswith("Test") or text.startswith("Aufbau"):
                # ignore document meta sections
                continue

            if text.startswith("Hinweis"):
                continue

            if text.startswith("Aufgabe "):
                if current_question:
                    finalize_question(current_question, questions)

                number_part = text.replace("Aufgabe", "").strip()
                try:
                    question_number = int(number_part)
                except ValueError:
                    question_number = None

                current_question = {
                    "display_number": text,
                    "question_number": question_number,
                    "section": {
                        "part": current_section["part"],
                        "topic": current_section["topic"],
                    },
                    "question_lines": [],
                    "answers": [],
                    "bounds": {},
                    "pages": set(),
                }
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                current_question["state"] = "collect_question"
                continue

            if not current_question:
                continue

            bullet = starts_with_bullet(text)
            if bullet:
                option_text = text[len(bullet):].strip()
                current_question["answers"].append({"text": option_text})
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                current_question["state"] = "collect_answers"
                continue

            if current_question["state"] == "collect_answers" and current_question["answers"]:
                current_question["answers"][-1]["text"] += " " + text
                update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                current_question["pages"].add(entry["page"])
                continue

            # Skip "Bild N" labels that appear between the question and the first answer
            # These are image labels for the question's images
            if (current_question["state"] == "collect_question" and 
                text.strip() in ["Bild 1", "Bild 2", "Bild 3", "Bild 4", "Bild 5", "Bild 6"]):
                # Don't add these to the question text
                continue

            # Special case: if we're collecting question text and this line doesn't start with a bullet,
            # check if the NEXT line starts with a bullet. If so, this line is likely an answer that
            # appears before its bullet (like "Italien" in question 300).
            # ALSO: if the question ends with "…" and this line ends with ".", it's likely the first answer
            if current_question["state"] == "collect_question":
                # Check if question already ends with ellipsis and this line ends with period
                # This indicates the first answer appears before its bullet
                question_so_far = " ".join(current_question["question_lines"]).strip()
                if question_so_far.endswith("…") and text.endswith("."):
                    # This is likely the first answer that appears before its bullet
                    current_question["answers"].append({"text": text})
                    update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                    current_question["pages"].add(entry["page"])
                    current_question["state"] = "collect_answers"
                    continue
                
                # Look ahead to see if next line starts with a bullet
                if i + 1 < len(lines):
                    next_raw_text = lines[i + 1]["text"].strip()
                    next_bullet = starts_with_bullet(next_raw_text)
                    # Only treat as answer-before-bullet if:
                    # - line is short (1-3 words)
                    # - doesn't end with question markers
                    # - doesn't end with a period (which usually indicates question text)
                    if (next_bullet and 
                        len(text.split()) <= 3 and 
                        not text.endswith("…") and 
                        not text.endswith("?") and 
                        not text.endswith(".")):
                        # This line is an answer before its bullet
                        current_question["answers"].append({"text": text})
                        update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
                        current_question["pages"].add(entry["page"])
                        current_question["state"] = "collect_answers"
                        continue

            current_question["question_lines"].append(text)
            update_bounds(current_question["bounds"], entry["page"], entry["bbox"])
            current_question["pages"].add(entry["page"])

        i += 1

    if current_question:
        finalize_question(current_question, questions)

    return questions


def finalize_question(current_question: dict, questions: List[dict]) -> None:
    question_text = " ".join(current_question["question_lines"]).strip()
    
    # Filter out question number if it appears at the beginning of the question text
    # Pattern: "184. " or "206. " etc.
    import re
    question_text = re.sub(r'^\d+\.\s*', '', question_text)
    
    answers = [{"text": answer["text"].strip()} for answer in current_question["answers"]]
    
    # Remove any empty answers
    answers = [ans for ans in answers if ans["text"]]
    
    # Fix incorrectly merged numeric answers (like "2 3" should be "2" and "3")
    # This happens when multiple numbers appear on the same line after a bullet
    fixed_answers = []
    for answer in answers:
        answer_text = answer["text"].strip()
        # Check if this is a pattern like "2 3" or "16 17" (numbers separated by spaces)
        parts = answer_text.split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            # Split into separate answers
            fixed_answers.append({"text": parts[0]})
            fixed_answers.append({"text": parts[1]})
        else:
            fixed_answers.append(answer)
    answers = fixed_answers
    
    # Fix concatenated answers: if we have exactly 3 answers and the last one contains
    # multiple capitalized words (like "Meinungsfreiheit Selbstjustiz"), split them
    if len(answers) == 3:
        last_answer = answers[-1]["text"]
        
        # Case 0: Pattern like "gesetzestreu. verfassungswidrig." or "eine Diktatur. eine Monarchie."
        # Two complete phrases separated by ". " (period + space)
        if ". " in last_answer:
            parts = last_answer.split(". ")
            if len(parts) == 2:
                # Add period back to first part, keep second part as-is
                answers[-1] = {"text": parts[0] + "."}
                answers.append({"text": parts[1]})
        else:
            words = last_answer.split()
            # Case 1: If last answer has 2 words and both start with capital letters, split them
            if len(words) == 2 and all(w[0].isupper() for w in words):
                answers[-1] = {"text": words[0]}
                answers.append({"text": words[1]})
            # Case 1b: Pattern like "schwarz-gelb grün-weiß-rot" (hyphenated colors)
            # Two hyphenated words separated by space
            elif len(words) == 2 and all('-' in w for w in words):
                answers[-1] = {"text": words[0]}
                answers.append({"text": words[1]})
            # Case 1c: Pattern like "Meinungsfreiheit verschiedene Parteien"
            # Capitalized word followed by lowercase words (likely two separate phrases)
            elif len(words) >= 2 and words[0][0].isupper() and words[1][0].islower():
                # Split into first word and remaining words
                answers[-1] = {"text": words[0]}
                answers.append({"text": " ".join(words[1:])})
            # Case 2: Pattern like "die Todesstrafe die Geldstrafe" (repeated article + noun)
            elif len(words) == 4:
                # Check if pattern is: article noun article noun
                if (words[0].lower() in ['die', 'der', 'das'] and 
                    words[2].lower() in ['die', 'der', 'das'] and
                    words[1][0].isupper() and words[3][0].isupper()):
                    # Split into "article noun" and "article noun"
                    answers[-1] = {"text": f"{words[0]} {words[1]}"}
                    answers.append({"text": f"{words[2]} {words[3]}"})
    
    # Fix split answers: if we have 5 or 4 answers and the last one is very short (1-2 words),
    # it's likely a continuation of the previous answer that got split
    if len(answers) >= 4:
        last_answer = answers[-1]["text"]
        word_count = len(last_answer.split())
        # Don't merge if the answer contains digits (like "6%" or "2") or is purely numeric
        contains_digit = any(c.isdigit() for c in last_answer)
        if not contains_digit and word_count <= 2:
            # Check if it's likely a continuation:
            # - Single word starting with lowercase (like "widerspreche.")
            # - Two words where first starts with lowercase
            # BUT NOT if it's a complete phrase like "die Geldstrafe" (article + noun)
            # AND NOT if previous answer also ends with period (indicates both are complete)
            is_continuation = False
            prev_answer = answers[-2]["text"]
            both_end_with_period = last_answer.rstrip().endswith('.') and prev_answer.rstrip().endswith('.')
            
            if word_count == 1 and not last_answer[0].isupper() and not both_end_with_period:
                # Don't merge if both are hyphenated (color patterns)
                if not ('-' in last_answer and '-' in prev_answer):
                    is_continuation = True
            elif word_count == 2:
                words = last_answer.split()
                # Check if it's article + noun pattern (complete answer, don't merge)
                is_article_noun = (words[0].lower() in ['die', 'der', 'das', 'den', 'dem', 'des'] and 
                                 words[1][0].isupper())
                # Check if it's adjective + noun pattern (complete answer, don't merge)
                # e.g., "verschiedene Parteien", "regelmäßige Wahlen"
                is_adjective_noun = (not words[0][0].isupper() and words[1][0].isupper())
                # Check if both current and previous are hyphenated (likely color combinations)
                both_hyphenated = '-' in last_answer and '-' in prev_answer
                if not is_article_noun and not is_adjective_noun and not last_answer[0].isupper() and not both_end_with_period and not both_hyphenated:
                    is_continuation = True
            
            if is_continuation:
                # Merge with previous answer
                answers[-2]["text"] = answers[-2]["text"].rstrip() + " " + last_answer
                answers = answers[:-1]  # Remove the last answer
    
    question_entry = {
        "id": len(questions) + 1,
        "display_number": current_question["display_number"],
        "question_number": current_question["question_number"],
        "section": current_question["section"],
        "question": question_text,
        "answers": answers,
        "pages": sorted(current_question["pages"]),
        "bounds": current_question["bounds"],
        "images": [],
    }
    questions.append(question_entry)


def assign_images(questions: List[dict], images_by_page: Dict[int, List[dict]]) -> None:
    image_claims: Dict[int, set] = defaultdict(set)

    for question in questions:
        for page, bounds in question["bounds"].items():
            page_images = images_by_page.get(page, [])
            q_top = bounds["top"]
            q_bottom = bounds["bottom"]

            for image in page_images:
                image_id = id(image["bytes"])
                if image_id in image_claims[page]:
                    continue

                img_top = image["bbox"][1]
                img_bottom = image["bbox"][3]

                overlap = min(q_bottom, img_bottom) - max(q_top, img_top)
                padding = 12

                if overlap >= -padding:
                    question.setdefault("_images", []).append({
                        "page": page,
                        "ext": image["ext"],
                        "bytes": image["bytes"],
                    })
                    image_claims[page].add(image_id)


def normalize_answer_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return " ".join(raw.split())


def question_signature(entry: dict) -> Optional[tuple]:
    question_text = normalize_answer_text(entry.get("question"))
    answers = [normalize_answer_text(opt.get("text")) for opt in entry.get("answers", [])]

    if not question_text or not answers:
        return None

    if any(not answer for answer in answers):
        return None

    return question_text, tuple(answers)


def apply_existing_correct_answers(questions: List[dict], output_json_path: Path) -> None:
    if not output_json_path.exists():
        return

    try:
        with output_json_path.open("r", encoding="utf-8") as existing_file:
            existing_payload = json.load(existing_file)
    except (json.JSONDecodeError, OSError):
        return

    stored_answers: Dict[tuple, dict] = {}

    for entry in existing_payload.get("questions", []):
        idx = entry.get("correct_answer_index")
        if not isinstance(idx, int):
            continue

        signature = question_signature(entry)

        if not signature:
            continue

        stored_answers[signature] = {
            "index": idx,
            "question_number": entry.get("question_number"),
        }

    if not stored_answers:
        return

    reused = 0
    skipped = 0

    for question in questions:
        signature = question_signature(question)
        if not signature:
            continue

        stored = stored_answers.get(signature)
        if not stored:
            continue

        answers_len = len(signature[1])

        if 0 <= stored["index"] < answers_len:
            question["correct_answer_index"] = stored["index"]
            reused += 1
        else:
            skipped += 1

    if skipped and reused:
        print(f"Skipped {skipped} stored answer(s) that no longer match question text; reused {reused}.")
    elif skipped:
        print(f"Skipped {skipped} stored answer(s) that no longer match question text.")
    elif reused:
        print(f"Reused {reused} stored answer(s) from existing dataset.")


def persist_output(
    questions: List[dict],
    output_json_path: Path,
    images_dir: Path,
    pdf_name: str,
) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)

    for question in questions:
        image_entries = []
        for idx, image in enumerate(question.pop("_images", []), start=1):
            filename = f"question_{question['id']:04d}_{idx}.{image['ext']}"
            output_path = images_dir / filename
            with output_path.open("wb") as image_file:
                image_file.write(image["bytes"])

            rel_path = os.path.relpath(output_path, start=output_json_path.parent)
            image_entries.append(Path(rel_path).as_posix())

        question["images"] = image_entries

        # remove internal-only keys
        question.pop("bounds", None)

    payload = {
        "meta": {
            "source": pdf_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "question_count": len(questions),
        },
        "questions": questions,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Einbürgerungstest PDF into JSON dataset")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF source file")
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path("data/questions.json"),
        help="Destination JSON file path",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=Path("data/images"),
        help="Directory for extracted question images",
    )

    args = parser.parse_args()

    pdf_path: Path = args.pdf_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    document = load_document_lines(pdf_path)
    questions = parse_questions(document["lines"])
    assign_images(questions, document["images"])
    apply_existing_correct_answers(questions, args.out_json)
    persist_output(questions, args.out_json, args.images_dir, pdf_path.name)

    print(f"Extracted {len(questions)} questions to {args.out_json}")


if __name__ == "__main__":
    main()
